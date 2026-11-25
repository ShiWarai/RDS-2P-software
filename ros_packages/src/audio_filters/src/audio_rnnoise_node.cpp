// SPDX-License-Identifier: MIT
// RNNoise (linked static) copyright Xiph / BSD-3-Clause — see package README.

extern "C" {
#include <rnnoise.h>
}
#include <soxr.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <deque>
#include <memory>
#include <string>
#include <vector>

#include "audio_common_msgs/msg/audio_stamped.hpp"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp/qos.hpp"

namespace {

constexpr int k_pa_float32 = 1;
constexpr int k_pa_int32 = 2;
constexpr int k_pa_int16 = 8;
constexpr int k_pa_int8 = 16;
constexpr int k_pa_uint8 = 32;

constexpr double k_rn_hz = 48000.0;

bool extract_mono_pcm_f32_amplitude(
  const audio_common_msgs::msg::AudioStamped & msg,
  std::vector<float> & out_mono_amp,
  std::string & err)
{
  const auto & ad = msg.audio.audio_data;
  const auto & info = msg.audio.info;
  const int channels = std::max(1, info.channels);
  std::vector<float> flat;

  switch (info.format) {
    case k_pa_float32:
      flat.assign(ad.float32_data.begin(), ad.float32_data.end());
      break;
    case k_pa_int32: {
      flat.resize(ad.int32_data.size());
      for (size_t i = 0; i < ad.int32_data.size(); ++i) {
        flat[i] =
          static_cast<float>(ad.int32_data[i]);
      }
      break;
    }
    case k_pa_int16: {
      flat.resize(ad.int16_data.size());
      for (size_t i = 0; i < ad.int16_data.size(); ++i) {
        flat[i] = static_cast<float>(ad.int16_data[i]);
      }
      break;
    }
    case k_pa_int8: {
      flat.resize(ad.int8_data.size());
      for (size_t i = 0; i < ad.int8_data.size(); ++i) {
        flat[i] =
          static_cast<float>(static_cast<int8_t>(ad.int8_data[i]));
      }
      break;
    }
    case k_pa_uint8: {
      flat.resize(ad.uint8_data.size());
      for (size_t i = 0; i < ad.uint8_data.size(); ++i) {
        flat[i] =
          static_cast<float>(static_cast<int16_t>(ad.uint8_data[i]) - 128);
      }
      break;
    }
    default:
      err = "unsupported PortAudio format code " +
        std::to_string(info.format);
      return false;
  }

  if (flat.empty()) {
    err = "empty audio payload";
    return false;
  }

  const size_t frames = flat.size() / static_cast<size_t>(channels);
  if (frames * static_cast<size_t>(channels) != flat.size()) {
    err = "audio length not multiple of channels";
    return false;
  }

  out_mono_amp.resize(frames);
  if (channels == 1) {
    for (size_t f = 0; f < frames; ++f) {
      out_mono_amp[f] = flat[f];
    }
  } else {
    for (size_t f = 0; f < frames; ++f) {
      double acc = 0.0;
      for (int c = 0; c < channels; ++c) {
        acc += static_cast<double>(flat[f * static_cast<size_t>(channels) + static_cast<size_t>(c)]);
      }
      out_mono_amp[f] = static_cast<float>(acc / static_cast<double>(channels));
    }
  }
  return true;
}

void amps_to_mono_i16_bounded(
  const std::vector<float> & amps,
  std::vector<int16_t> & out_pcm)
{
  out_pcm.resize(amps.size());
  for (size_t i = 0; i < amps.size(); ++i) {
    double v =
      std::max(-32768.0, std::min(32767.0, std::round(static_cast<double>(amps[i]))));
    out_pcm[i] = static_cast<int16_t>(v);
  }
}

}  // namespace

class AudioRnnoiseNode final : public rclcpp::Node
{
public:
  AudioRnnoiseNode()
  : Node("audio_rnnoise")
  {
    input_topic_ = declare_parameter<std::string>("input_topic", "/audio/input");
    output_topic_ = declare_parameter<std::string>("output_topic", "/audio/input/clean");
    qos_depth_ = declare_parameter<int>("qos_depth", 50);
    out_chunk_frames_ = declare_parameter<int>("output_chunk_frames", 1024);
    passthrough_format_on_output_ =
      declare_parameter<bool>("preserve_input_format_for_output", true);

    qos_depth_ = std::max(10, qos_depth_);
    out_chunk_frames_ = std::max(64, out_chunk_frames_);

    rclcpp::QoS qos(rclcpp::KeepLast(static_cast<size_t>(qos_depth_)));
    qos.best_effort();

    publisher_ =
      create_publisher<audio_common_msgs::msg::AudioStamped>(
      output_topic_, qos);

    subscription_ =
      create_subscription<audio_common_msgs::msg::AudioStamped>(
      input_topic_, qos,
      std::bind(
        &AudioRnnoiseNode::on_audio,
        this, std::placeholders::_1));

    RCLCPP_INFO(
      get_logger(),
      "audio_rnnoise_node: '%s' -> '%s', qos_depth=%d, out_chunk_frames=%d",
      input_topic_.c_str(),
      output_topic_.c_str(),
      qos_depth_,
      out_chunk_frames_);
  }

  ~AudioRnnoiseNode() override
  {
    if (up_converter_) {
      soxr_delete(up_converter_);
      up_converter_ = nullptr;
    }
    if (down_converter_) {
      soxr_delete(down_converter_);
      down_converter_ = nullptr;
    }
    rn_st_.reset();
  }

private:
  void reset_pipeline(const char *why)
  {
    RCLCPP_WARN(get_logger(), "Reset RNNoise/soxr pipeline: %s", why);
    rn_st_.reset();
    if (up_converter_) {
      soxr_delete(up_converter_);
      up_converter_ = nullptr;
    }
    if (down_converter_) {
      soxr_delete(down_converter_);
      down_converter_ = nullptr;
    }
    native_f_accum_.clear();
    hi_accum_.clear();
    post_rn_48_.clear();
    down_native_accum_.clear();
    initialized_ = false;
    in_hz_ = 0.0;
    frame_rn_ = 0;
  }

  void ensure_pipeline_locked(double in_hz)
  {
    if (initialized_ && std::abs(in_hz_ - in_hz) < 1.0 &&
      rn_st_)
    {
      return;
    }
    reset_pipeline("parameter / stream change");

    frame_rn_ = rnnoise_get_frame_size();
    if (frame_rn_ <= 0) {
      frame_rn_ = 480;
      RCLCPP_WARN(
        get_logger(),
        "rnnoise_get_frame_size() invalid; fallback %d",
        frame_rn_);
    }

    rn_st_.reset(rnnoise_create(nullptr));
    if (!rn_st_) {
      throw std::runtime_error("rnnoise_create failed");
    }

    soxr_error_t ue = nullptr;
    up_converter_ =
      soxr_create(in_hz, k_rn_hz, 1u, &ue, nullptr, nullptr, nullptr);
    if (!up_converter_ || ue) {
      throw std::runtime_error(
        std::string("soxr_create up failed: ") +
        std::string(ue ? ue : ""));
    }

    soxr_error_t de = nullptr;
    down_converter_ =
      soxr_create(k_rn_hz, in_hz, 1u, &de, nullptr, nullptr, nullptr);
    if (!down_converter_ || de) {
      throw std::runtime_error(
        std::string("soxr_create down failed: ") +
        std::string(de ? de : ""));
    }

    in_hz_ = in_hz;
    initialized_ = true;
  }

  void run_up_resample_locked()
  {
    while (!native_f_accum_.empty()) {
      size_t nin = std::min(static_cast<size_t>(4096), native_f_accum_.size());
      float inbuf[4096];
      for (size_t i = 0; i < nin; ++i) {
        inbuf[i] = native_f_accum_.front();
        native_f_accum_.pop_front();
      }

      std::vector<float> obuf(
        static_cast<size_t>(
          std::ceil(static_cast<double>(nin) * (k_rn_hz / in_hz_)) + 96.0));

      size_t idone = 0;
      size_t odone = 0;
      soxr_error_t e =
        soxr_process(
        up_converter_, inbuf,
        nin, &idone, obuf.data(), obuf.size(), &odone);
      if (e) {
        RCLCPP_ERROR(get_logger(), "soxr up: %s", soxr_strerror(e));
        break;
      }
      if (idone != nin) {
        RCLCPP_WARN(
          get_logger(),
          "soxr up partial input consume %zu vs %zu", idone,
          nin);
      }
      for (size_t j = 0; j < odone; ++j) {
        hi_accum_.push_back(obuf[j]);
      }
    }
  }

  void run_rn_noise_locked()
  {
    std::vector<float> frame(static_cast<size_t>(frame_rn_));
    while (hi_accum_.size() >= static_cast<size_t>(frame_rn_)) {
      for (size_t i = 0; i < static_cast<size_t>(frame_rn_); ++i) {
        frame[i] = hi_accum_.front();
        hi_accum_.pop_front();
      }
      rnnoise_process_frame(rn_st_.get(), frame.data(), frame.data());
      for (size_t i = 0; i < frame.size(); ++i) {
        post_rn_48_.push_back(frame[i]);
      }
    }
  }

  void run_down_resample_locked()
  {
    while (!post_rn_48_.empty()) {
      size_t nin =
        std::min(static_cast<size_t>(4096), post_rn_48_.size());
      float inbuf[4096];
      for (size_t i = 0; i < nin; ++i) {
        inbuf[i] = post_rn_48_.front();
        post_rn_48_.pop_front();
      }

      std::vector<float> obuf(
        static_cast<size_t>(
          std::ceil(static_cast<double>(nin) * (in_hz_ / k_rn_hz)) + 96.0));

      size_t idone = 0;
      size_t odone = 0;
      soxr_error_t e =
        soxr_process(
        down_converter_, inbuf,
        nin, &idone, obuf.data(), obuf.size(), &odone);
      if (e) {
        RCLCPP_ERROR(get_logger(), "soxr down: %s", soxr_strerror(e));
        break;
      }
      for (size_t j = 0; j < odone; ++j) {
        down_native_accum_.push_back(obuf[j]);
      }
    }
  }

  void emit_output_locked(const std_msgs::msg::Header & header_tpl)
  {
    const int chunk_publish =
      (last_publish_chunk_hint_ > 0) ?
      std::max(64, last_publish_chunk_hint_) :
      out_chunk_frames_;

    while (down_native_accum_.size() >=
      static_cast<size_t>(chunk_publish))
    {
      std::vector<float> slice(
        down_native_accum_.begin(),
        down_native_accum_.begin() + chunk_publish);
      down_native_accum_.erase(
        down_native_accum_.begin(),
        down_native_accum_.begin() + chunk_publish);

      audio_common_msgs::msg::AudioStamped out;
      out.header = header_tpl;
      out.audio.info.rate = last_rate_;
      out.audio.info.channels = 1;
      out.audio.info.chunk = chunk_publish;

      if (passthrough_format_on_output_ &&
        last_fmt_ == k_pa_float32)
      {
        out.audio.info.format = k_pa_float32;
        std::vector<float> f(chunk_publish);
        for (size_t i = 0; i < slice.size(); ++i) {
          f[i] = slice[i];  // amplitude as demo rnnoise_demo
        }
        out.audio.audio_data.float32_data.swap(f);
      } else if (
        passthrough_format_on_output_ && last_fmt_ == k_pa_int16)
      {
        out.audio.info.format = k_pa_int16;
        std::vector<int16_t> i16(chunk_publish);
        for (size_t i = 0; i < slice.size(); ++i) {
          const double clipped =
            std::max(-32768.0, std::min(32767.0, std::round(static_cast<double>(slice[i]))));
          i16[i] = static_cast<int16_t>(clipped);
        }
        out.audio.audio_data.int16_data.swap(i16);
      } else {
        out.audio.info.format = k_pa_int16;
        amps_to_mono_i16_bounded(slice, out_fifo_i16_help_);
        out.audio.audio_data.int16_data.swap(out_fifo_i16_help_);
      }

      publisher_->publish(out);
    }
  }

  void on_audio(const audio_common_msgs::msg::AudioStamped::SharedPtr msg)
  {
    std::vector<float> mono_amp;
    std::string extract_err;

    const int sr = msg->audio.info.rate;
    if (sr <= 0) {
      return;
    }
    if (
      initialized_ &&
      (sr != last_rate_ ||
      msg->audio.info.format != last_fmt_ ||
      msg->audio.info.channels != last_channels_))
    {
      reset_pipeline("audio stream format/rate/channel change mid-run");
    }
    last_fmt_ = msg->audio.info.format;
    last_channels_ = msg->audio.info.channels;
    last_rate_ = sr;

    last_publish_chunk_hint_ = msg->audio.info.chunk;
    header_tpl_ = msg->header;

    if (!extract_mono_pcm_f32_amplitude(*msg, mono_amp, extract_err)) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(),
        5000, "drop frame: %s", extract_err.c_str());
      return;
    }

    try {
      ensure_pipeline_locked(static_cast<double>(sr));
    } catch (const std::exception & e) {
      RCLCPP_ERROR(get_logger(), "pipeline init failed: %s", e.what());
      return;
    }

    for (float v : mono_amp) {
      native_f_accum_.push_back(v);
    }

    run_up_resample_locked();
    run_rn_noise_locked();
    run_down_resample_locked();
    emit_output_locked(header_tpl_);
  }

  std::string input_topic_;
  std::string output_topic_;
  int qos_depth_{50};
  int out_chunk_frames_{1024};
  bool passthrough_format_on_output_{true};

  std_msgs::msg::Header header_tpl_;

  rclcpp::Publisher<audio_common_msgs::msg::AudioStamped>::SharedPtr
    publisher_;
  rclcpp::Subscription<
    audio_common_msgs::msg::AudioStamped>::SharedPtr subscription_;

  struct RnnoiseDestructor
  {
    void operator()(DenoiseState * p) const
    {
      if (p) {
        rnnoise_destroy(p);
      }
    }
  };

  bool initialized_{false};
  double in_hz_{0.0};
  int frame_rn_{0};
  std::unique_ptr<DenoiseState, RnnoiseDestructor> rn_st_;
  soxr_t up_converter_{nullptr};
  soxr_t down_converter_{nullptr};

  std::deque<float> native_f_accum_;
  std::deque<float> hi_accum_;
  std::deque<float> post_rn_48_;
  std::deque<float> down_native_accum_;

  int last_fmt_{k_pa_int16};
  int last_channels_{1};
  int last_rate_{0};
  int last_publish_chunk_hint_{0};

  std::vector<int16_t> out_fifo_i16_help_;
};

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<AudioRnnoiseNode>());
  rclcpp::shutdown();
  return 0;
}
