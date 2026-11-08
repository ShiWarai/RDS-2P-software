// SPDX-License-Identifier: MIT
#include <cstdint>
#include <cmath>
#include <string>
#include <vector>

#include "audio_common_msgs/msg/audio_stamped.hpp"
#include "rclcpp/qos.hpp"
#include "rclcpp/rclcpp.hpp"

namespace {

constexpr int k_pa_float32 = 1;
constexpr int k_pa_int32 = 2;
constexpr int k_pa_int16 = 8;
constexpr int k_pa_int8 = 16;
constexpr int k_pa_uint8 = 32;

/** Распаковать interleaved PCM в массив float (амплитуды в том же масштабе, что входной формат). */
bool unpack_to_float_amps(
  const audio_common_msgs::msg::AudioStamped & msg,
  std::vector<float> & samples,
  int & channels_ref,
  std::string & err)
{
  const auto & ad = msg.audio.audio_data;
  const auto & info = msg.audio.info;
  const int channels = std::max(1, info.channels);

  channels_ref = channels;

  switch (info.format) {
    case k_pa_float32: {
      if (ad.float32_data.empty()) {
        err = "empty float32 payload";
        return false;
      }
      samples.assign(ad.float32_data.begin(), ad.float32_data.end());
      break;
    }
    case k_pa_int32: {
      samples.resize(ad.int32_data.size());
      for (size_t i = 0; i < ad.int32_data.size(); ++i) {
        samples[i] = static_cast<float>(ad.int32_data[i]);
      }
      break;
    }
    case k_pa_int16: {
      samples.resize(ad.int16_data.size());
      for (size_t i = 0; i < ad.int16_data.size(); ++i) {
        samples[i] = static_cast<float>(ad.int16_data[i]);
      }
      break;
    }
    case k_pa_int8: {
      samples.resize(ad.int8_data.size());
      for (size_t i = 0; i < ad.int8_data.size(); ++i) {
        samples[i] =
          static_cast<float>(static_cast<int8_t>(ad.int8_data[i]));
      }
      break;
    }
    case k_pa_uint8: {
      samples.resize(ad.uint8_data.size());
      for (size_t i = 0; i < ad.uint8_data.size(); ++i) {
        samples[i] =
          static_cast<float>(static_cast<int16_t>(ad.uint8_data[i]) - 128);
      }
      break;
    }
    default:
      err =
        "unsupported PortAudio format " + std::to_string(info.format);
      return false;
  }

  if (samples.empty()) {
    err = "empty audio payload";
    return false;
  }
  if (
    channels > 1 &&
    (samples.size() % static_cast<size_t>(channels) != 0UL))
  {
    err = "audio length not multiple of channels";
    return false;
  }
  return true;
}

audio_common_msgs::msg::AudioStamped build_output(
  const std_msgs::msg::Header & header,
  const audio_common_msgs::msg::AudioInfo & info_in,
  const std::vector<float> & gained,
  int format)
{
  audio_common_msgs::msg::AudioStamped out;
  out.header = header;
  out.audio.info = info_in;

  switch (format) {
    case k_pa_float32:
      out.audio.info.format = k_pa_float32;
      out.audio.audio_data.float32_data.assign(
        gained.begin(), gained.end());
      break;
    case k_pa_int16: {
      out.audio.info.format = k_pa_int16;
      std::vector<int16_t> pcm(gained.size());
      for (size_t i = 0; i < gained.size(); ++i) {
        const double clipped =
          std::max(-32768.0, std::min(32767.0, std::round(static_cast<double>(gained[i]))));
        pcm[i] = static_cast<int16_t>(clipped);
      }
      out.audio.audio_data.int16_data.swap(pcm);
      break;
    }
    case k_pa_int32: {
      out.audio.info.format = k_pa_int32;
      std::vector<int32_t> pcm(gained.size());
      for (size_t i = 0; i < gained.size(); ++i) {
        double v =
          std::max(
          -2147483648.0,
          std::min(2147483647.0, std::round(static_cast<double>(gained[i]))));
        pcm[i] = static_cast<int32_t>(v);
      }
      out.audio.audio_data.int32_data.swap(pcm);
      break;
    }
    case k_pa_int8: {
      out.audio.info.format = k_pa_int8;
      std::vector<int8_t> raw(gained.size());
      for (size_t i = 0; i < gained.size(); ++i) {
        const double clipped =
          std::max(-128.0, std::min(127.0, std::round(static_cast<double>(gained[i]))));
        raw[i] = static_cast<int8_t>(static_cast<int>(clipped));
      }
      out.audio.audio_data.int8_data.swap(raw);
      break;
    }
    case k_pa_uint8: {
      out.audio.info.format = k_pa_uint8;
      std::vector<unsigned char> raw(gained.size());
      for (size_t i = 0; i < gained.size(); ++i) {
        const double centered =
          std::max(-128.0, std::min(127.0, std::round(static_cast<double>(gained[i]))));
        const int u = static_cast<int>(centered + 128.0);
        raw[i] = static_cast<unsigned char>(std::max(0, std::min(255, u)));
      }
      out.audio.audio_data.uint8_data.swap(raw);
      break;
    }
    default:
      out.audio.info.format = k_pa_float32;
      out.audio.audio_data.float32_data.assign(
        gained.begin(), gained.end());
      break;
  }
  return out;
}

}  // namespace

/** Усиление громкости: тот же формат AudioStamped, что на входе. */
class AudioGainNode final : public rclcpp::Node
{
public:
  AudioGainNode()
  : Node("audio_gain")
  {
    input_topic_ = declare_parameter<std::string>("input_topic", "/audio/input");
    output_topic_ =
      declare_parameter<std::string>("output_topic", "/audio/input/boosted");

    qos_depth_ = declare_parameter<int>("qos_depth", 50);
    gain_linear_ = declare_parameter<double>("gain_linear", 2.0);

    qos_depth_ = std::max(10, qos_depth_);
    gain_linear_ = std::max(1e-6, gain_linear_);

    rclcpp::QoS qos(rclcpp::KeepLast(static_cast<size_t>(qos_depth_)));
    qos.best_effort();

    pub_ =
      create_publisher<audio_common_msgs::msg::AudioStamped>(
      output_topic_, qos);
    sub_ =
      create_subscription<audio_common_msgs::msg::AudioStamped>(
      input_topic_,
      qos,
      std::bind(&AudioGainNode::on_audio, this, std::placeholders::_1));

    RCLCPP_INFO(
      get_logger(),
      "audio_gain_node: '%s' -> '%s', gain_linear=%.3f, qos_depth=%d",
      input_topic_.c_str(),
      output_topic_.c_str(),
      gain_linear_,
      qos_depth_);

    param_cb_handle_ =
      add_on_set_parameters_callback(
      std::bind(
        &AudioGainNode::on_param_change, this, std::placeholders::_1));
  }

private:
  rcl_interfaces::msg::SetParametersResult on_param_change(
    const std::vector<rclcpp::Parameter> & params)
  {
    for (const auto & p : params) {
      if (p.get_name() == "gain_linear") {
        double g = p.as_double();
        if (g < 1e-6) {
          rcl_interfaces::msg::SetParametersResult r;
          r.successful = false;
          r.reason = "gain_linear must be >= 1e-6";
          return r;
        }
        gain_linear_ = g;
        RCLCPP_INFO(get_logger(), "gain_linear set to %.6f", gain_linear_);
      }
    }
    rcl_interfaces::msg::SetParametersResult ok;
    ok.successful = true;
    return ok;
  }

  void apply_gain_inplace(std::vector<float> & s) const
  {
    const double g = static_cast<double>(gain_linear_);
    for (auto & x : s) {
      x = static_cast<float>(static_cast<double>(x) * g);
    }
  }

  void on_audio(const audio_common_msgs::msg::AudioStamped::SharedPtr msg)
  {
    if (msg->audio.info.rate <= 0) {
      return;
    }

    std::vector<float> samps;
    int chans = 1;
    std::string ex_err;
    if (!unpack_to_float_amps(*msg, samps, chans, ex_err)) {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 5000,
        "gain drop: %s", ex_err.c_str());
      return;
    }
    (void)chans;

    last_format_ = msg->audio.info.format;
    apply_gain_inplace(samps);

    audio_common_msgs::msg::AudioStamped out =
      build_output(
      msg->header, msg->audio.info,
      samps, last_format_);
    pub_->publish(out);
  }

  std::string input_topic_;
  std::string output_topic_;
  int qos_depth_{50};
  double gain_linear_{2.0};
  int last_format_{k_pa_int16};

  rclcpp::Publisher<audio_common_msgs::msg::AudioStamped>::SharedPtr pub_;
  rclcpp::Subscription<audio_common_msgs::msg::AudioStamped>::SharedPtr sub_;

  OnSetParametersCallbackHandle::SharedPtr param_cb_handle_;
};

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<AudioGainNode>());
  rclcpp::shutdown();
  return 0;
}
