// RDS-2P audio_player: микшер AudioStamped по frame_id → динамик (PortAudio pull-колбэк).
// RT-колбэк только суммирует готовые float-кадры; декод формата/каналов и ресемпл — на приёме.

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <deque>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <portaudio.h>
#include <rclcpp/rclcpp.hpp>

#include <audio_common/sample_rate_converter.hpp>
#include <audio_common_msgs/msg/audio_stamped.hpp>

using namespace std::chrono_literals;

namespace {

double now_sec() {
  using clock = std::chrono::steady_clock;
  return std::chrono::duration<double>(clock::now().time_since_epoch()).count();
}

template <typename T>
inline float to_float(T s) {
  return static_cast<float>(s) /
         (static_cast<float>(std::numeric_limits<T>::max()) + 1.0f);
}
template <>
inline float to_float<float>(float s) {
  return s;
}
template <>
inline float to_float<uint8_t>(uint8_t s) {
  return (static_cast<float>(s) - 128.0f) / 128.0f;
}

} // namespace

namespace rds_2p_audio {

class AudioPlayerNode : public rclcpp::Node {
public:
  AudioPlayerNode() : Node("audio_player") {
    topic_ = declare_parameter<std::string>("topic", "/audio/output");
    device_ = declare_parameter<int>("device", -1);
    device_name_ = declare_parameter<std::string>("device_name", "");
    pulse_sink_ = declare_parameter<std::string>("pulse_sink", "");
    channels_ = declare_parameter<int>("channels", 1);
    rate_ = declare_parameter<int>("output_sample_rate", 44100);
    block_ms_ = declare_parameter<double>("block_ms", 20.0);
    latency_ms_ = declare_parameter<double>("latency_ms", 100.0);
    preroll_ms_ = declare_parameter<double>("preroll_ms", 120.0);
    evict_sec_ = declare_parameter<double>("source_evict_sec", 5.0);
    max_buffer_sec_ = declare_parameter<double>("max_source_buffer_sec", 15.0);
    int qos_depth = declare_parameter<int>("qos_depth", 50);

    if (channels_ <= 0 || rate_ <= 0 || block_ms_ <= 0.0) {
      RCLCPP_ERROR(get_logger(),
                   "Недопустимые параметры: channels=%d rate=%d block_ms=%.2f",
                   channels_, rate_, block_ms_);
      throw std::runtime_error("invalid audio parameters");
    }

    if (!pulse_sink_.empty()) {
      setenv("PULSE_SINK", pulse_sink_.c_str(), 1);
      RCLCPP_INFO(get_logger(),
                  "Установлено PULSE_SINK='%s' до открытия PortAudio-потока",
                  pulse_sink_.c_str());
    }

    if (Pa_Initialize() != paNoError) {
      throw std::runtime_error("Pa_Initialize failed");
    }

    PaDeviceIndex out = resolve_device();
    if (out == paNoDevice) {
      Pa_Terminate();
      throw std::runtime_error("no PortAudio output device");
    }
    const PaDeviceInfo *info = Pa_GetDeviceInfo(out);
    output_device_ = out;

    frames_per_block_ =
        std::max(1u, static_cast<unsigned>(std::lround(block_ms_ * 0.001 *
                                                       static_cast<double>(rate_))));
    preroll_samples_ = static_cast<size_t>(std::max(
        0.0, preroll_ms_ * 0.001 * static_cast<double>(rate_) *
                 static_cast<double>(channels_)));

    PaStreamParameters p{};
    p.device = out;
    p.channelCount = channels_;
    p.sampleFormat = paFloat32;
    // block_ms — гранулярность колбэка; latency_ms — размер буфера ALSA
    // (сглаживает джиттер планирования; малый буфер → «прирывистый» звук).
    p.suggestedLatency = latency_ms_ > 0.0
                            ? latency_ms_ / 1000.0
                            : info->defaultHighOutputLatency;
    p.hostApiSpecificStreamInfo = nullptr;

    PaError err = Pa_OpenStream(&stream_, nullptr, &p, static_cast<double>(rate_),
                                frames_per_block_, paClipOff,
                                &AudioPlayerNode::pa_callback, this);
    if (err != paNoError) {
      Pa_Terminate();
      throw std::runtime_error(std::string("Pa_OpenStream: ") + Pa_GetErrorText(err));
    }
    err = Pa_StartStream(stream_);
    if (err != paNoError) {
      Pa_CloseStream(stream_);
      Pa_Terminate();
      throw std::runtime_error(std::string("Pa_StartStream: ") + Pa_GetErrorText(err));
    }

    RCLCPP_INFO(get_logger(),
                "audio_player: sr=%d ch=%d block=%.1f ms (%u fr) latency=%.0f ms "
                "preroll=%.0f ms idx=%d (%s) subs='%s' pull-микшер",
                rate_, channels_, block_ms_, frames_per_block_, latency_ms_,
                preroll_ms_, out, info->name, topic_.c_str());

    // Аудио-шина /audio/output — BEST_EFFORT (издатели paroli/routine/test_speaker).
    // RELIABLE-подписка несовместима с BEST_EFFORT-издателями → сообщения не идут.
    auto qos = rclcpp::QoS(static_cast<size_t>(qos_depth)).best_effort();
    sub_ = create_subscription<audio_common_msgs::msg::AudioStamped>(
        topic_, qos,
        std::bind(&AudioPlayerNode::audio_callback, this, std::placeholders::_1));

    evict_timer_ = create_wall_timer(1s, std::bind(&AudioPlayerNode::evict, this));
  }

  ~AudioPlayerNode() override {
    if (stream_) {
      Pa_AbortStream(stream_);
      Pa_CloseStream(stream_);
    }
    Pa_Terminate();
  }

private:
  struct Source {
    std::deque<float> buf; // interleaved float @ rate_, channels_
    audio_common::SampleRateConverter src;
    int in_channels = 0;
    int in_rate = 0;
    double last_active = 0.0;
    bool playing = false; // preroll: играем только после накопления запаса
    // диагностика: есть ли «прерывания» (блоки без данных у активного источника)
    bool ever_had_data = false;
    int empty_streak = 0;
    double last_data_t = 0.0;
    double max_gap_ms = 0.0;
    unsigned long data_blocks = 0;
    unsigned long gap_blocks = 0;
    // посэмпловая точность: частичный блок = слышимый рывок
    unsigned long samples_out = 0;
    unsigned long samples_req = 0;
    unsigned long partial_blocks = 0;
    size_t min_depth = static_cast<size_t>(-1);
  };

  PaDeviceIndex resolve_device() {
    int count = Pa_GetDeviceCount();
    if (!device_name_.empty()) {
      for (int i = 0; i < count; ++i) {
        const PaDeviceInfo *d = Pa_GetDeviceInfo(i);
        if (d && d->maxOutputChannels > 0 &&
            std::string(d->name).find(device_name_) != std::string::npos) {
          return i;
        }
      }
      RCLCPP_WARN(get_logger(),
                  "Устройство с подстрокой '%s' не найдено; fallback на индекс/default",
                  device_name_.c_str());
    }
    if (device_ >= 0 && device_ < count) {
      return device_;
    }
    return Pa_GetDefaultOutputDevice();
  }

  void audio_callback(const audio_common_msgs::msg::AudioStamped::SharedPtr msg) {
    const auto &info = msg->audio.info;
    int in_ch = info.channels;
    if (in_ch <= 0 || info.rate <= 0) {
      return;
    }

    std::vector<float> native;
    if (!decode(msg->audio.audio_data, info.format, in_ch, info.chunk, native)) {
      return;
    }

    std::lock_guard<std::mutex> lk(mutex_);
    const std::string key = msg->header.frame_id.empty() ? std::string("_")
                                                          : msg->header.frame_id;
    Source &s = sources_[key];

    // Ресет ресемплера при смене формата источника.
    if (s.in_channels != in_ch || s.in_rate != info.rate) {
      s.src = audio_common::SampleRateConverter{};
      s.buf.clear();
      s.in_channels = in_ch;
      s.in_rate = info.rate;
    }

    std::vector<float> ready = to_output_layout(native, in_ch);
    if (ready.empty()) {
      return;
    }

    if (info.rate != rate_) {
      ready = s.src.convert(ready, channels_, info.rate, rate_);
    }

    s.buf.insert(s.buf.end(), ready.begin(), ready.end());

    const size_t cap = static_cast<size_t>(
        std::max(0.0, max_buffer_sec_) * static_cast<double>(rate_) *
        static_cast<double>(channels_));
    if (cap > 0 && s.buf.size() > cap) {
      s.buf.erase(s.buf.begin(), s.buf.begin() + (s.buf.size() - cap));
    }
    s.last_active = now_sec();
  }

  // Декод сообщения → interleaved float в нативных каналах.
  bool decode(const audio_common_msgs::msg::AudioData &data, int format,
              int in_ch, int chunk, std::vector<float> &out) {
    size_t frames = 0;
    const float *f32 = nullptr;
    std::vector<float> tmp;

    auto load = [&](const auto &arr, auto conv) {
      frames = arr.size() / static_cast<size_t>(in_ch);
      if (chunk > 0) {
        frames = std::min(frames, static_cast<size_t>(chunk));
      }
      tmp.resize(frames * in_ch);
      for (size_t i = 0; i < frames * in_ch; ++i) {
        tmp[i] = conv(arr[i]);
      }
      return !tmp.empty();
    };

    switch (format) {
    case paFloat32:
      if (!load(data.float32_data, [](float x) { return x; })) return false;
      break;
    case paInt32:
      if (!load(data.int32_data, [](int32_t x) { return to_float(x); })) return false;
      break;
    case paInt16:
      if (!load(data.int16_data, [](int16_t x) { return to_float(x); })) return false;
      break;
    case paInt8:
      if (!load(data.int8_data, [](int8_t x) { return to_float(x); })) return false;
      break;
    case paUInt8:
      if (!load(data.uint8_data, [](uint8_t x) { return to_float(x); })) return false;
      break;
    default:
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
                           "Неподдерживаемый формат %d", format);
      return false;
    }
    (void)f32;
    out = std::move(tmp);
    return true;
  }

  // Конверт каналов нативный→выходные (mono<->stereo; иное — усреднением/дублем).
  std::vector<float> to_output_layout(const std::vector<float> &in, int in_ch) {
    if (in_ch == channels_) {
      return in;
    }
    const size_t frames = in.size() / static_cast<size_t>(in_ch);
    std::vector<float> out(frames * channels_, 0.0f);
    for (size_t fr = 0; fr < frames; ++fr) {
      for (int c = 0; c < channels_; ++c) {
        // маппинг выходного канала на входной (при mono→stereo дублирует,
        // при stereo→mono усредняет выше); общий случай: берём входной c, если есть.
        int sc = c;
        if (in_ch == 1) {
          sc = 0;
        } else if (c >= in_ch) {
          sc = c % in_ch;
        }
        out[fr * channels_ + c] = in[fr * in_ch + sc];
      }
    }
    if (in_ch == 2 && channels_ == 1) {
      for (size_t fr = 0; fr < frames; ++fr) {
        out[fr] = 0.5f * (in[2 * fr] + in[2 * fr + 1]);
      }
    }
    return out;
  }

  void evict() {
    const double now = now_sec();
    std::string diag;
    {
      std::lock_guard<std::mutex> lk(mutex_);
      for (auto it = sources_.begin(); it != sources_.end();) {
        // текущий (ещё не закрытый) разрыв, если источник сейчас «молчит»
        if (it->second.ever_had_data && it->second.empty_streak > 0) {
          const double cur = (now - it->second.last_data_t) * 1000.0;
          if (cur > it->second.max_gap_ms) {
            it->second.max_gap_ms = cur;
          }
        }
        if (now - it->second.last_active > evict_sec_) {
          it = sources_.erase(it);
        } else {
          if (it->second.ever_had_data) {
            const Source &s = it->second;
            const double cov = s.samples_req > 0
                ? 100.0 * static_cast<double>(s.samples_out) / s.samples_req
                : 100.0;
            const double min_depth_ms =
                (s.min_depth == static_cast<size_t>(-1))
                    ? 0.0
                    : 1000.0 * s.min_depth /
                          (static_cast<double>(rate_) * channels_);
            diag += it->first + ": cov=" +
                    std::to_string(static_cast<int>(cov)) + "% partial=" +
                    std::to_string(s.partial_blocks) + " max_gap=" +
                    std::to_string(static_cast<int>(s.max_gap_ms)) +
                    "ms min_buf=" + std::to_string(static_cast<int>(min_depth_ms)) +
                    "ms  ";
          }
          ++it;
        }
      }
    }
    if (!diag.empty()) {
      RCLCPP_INFO(get_logger(), "[diag] %s", diag.c_str());
    }
  }

  static int pa_callback(const void *, void *output, unsigned long nFrames,
                         const PaStreamCallbackTimeInfo *,
                         PaStreamCallbackFlags, void *user) {
    auto *self = static_cast<AudioPlayerNode *>(user);
    float *out = static_cast<float *>(output);
    const size_t total = static_cast<size_t>(nFrames) * self->channels_;
    std::fill(out, out + total, 0.0f);

    std::lock_guard<std::mutex> lk(self->mutex_);
    const double t = now_sec();
    for (auto &kv : self->sources_) {
      Source &s = kv.second;
      std::deque<float> &buf = s.buf;

      // preroll: копим запас перед стартом; это сглаживает джиттер подачи
      if (!s.playing) {
        if (buf.size() >= self->preroll_samples_) {
          s.playing = true;
        } else {
          continue; // ещё буферизуем — не играем и не считаем разрывом
        }
      }

      size_t have = std::min(buf.size(), total);
      const bool had = have > 0;
      for (size_t i = 0; i < have; ++i) {
        out[i] += buf[i];
      }
      buf.erase(buf.begin(), buf.begin() + have);

      s.samples_req += total;
      s.samples_out += have;
      if (have < total) {
        ++s.partial_blocks;
      }
      if (buf.size() < s.min_depth) {
        s.min_depth = buf.size();
      }
      if (had) {
        if (s.ever_had_data && s.empty_streak > 0) {
          const double gap_ms = (t - s.last_data_t) * 1000.0;
          if (gap_ms > s.max_gap_ms) {
            s.max_gap_ms = gap_ms;
          }
        }
        s.ever_had_data = true;
        s.empty_streak = 0;
        s.last_data_t = t;
        ++s.data_blocks;
      } else if (s.ever_had_data) {
        ++s.empty_streak;
        ++s.gap_blocks;
      }

      // полный дренаж (источник отстал/пауза между фразами) → ре-преролл
      if (buf.empty()) {
        s.playing = false;
      }
    }
    return paContinue;
  }

  std::string topic_;
  int device_ = -1;
  std::string device_name_;
  std::string pulse_sink_;
  int channels_ = 1;
  int rate_ = 44100;
  double block_ms_ = 20.0;
  double latency_ms_ = 100.0;
  double preroll_ms_ = 120.0;
  size_t preroll_samples_ = 0;
  double evict_sec_ = 5.0;
  double max_buffer_sec_ = 15.0;

  PaStream *stream_ = nullptr;
  PaDeviceIndex output_device_ = paNoDevice;
  unsigned frames_per_block_ = 0;

  std::mutex mutex_;
  std::map<std::string, Source> sources_;

  rclcpp::Subscription<audio_common_msgs::msg::AudioStamped>::SharedPtr sub_;
  rclcpp::TimerBase::SharedPtr evict_timer_;
};

} // namespace rds_2p_audio

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<rds_2p_audio::AudioPlayerNode>());
  } catch (const std::exception &e) {
    RCLCPP_ERROR(rclcpp::get_logger("audio_player"), "audio_player упал: %s", e.what());
  }
  rclcpp::shutdown();
  return 0;
}
