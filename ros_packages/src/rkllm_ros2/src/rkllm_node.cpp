// ROS 2 node: multimodal RKLLM + RKNN vision encoder (rknn-llm multimodal demo).
// SPDX-License-Identifier: Apache-2.0

#include <algorithm>
#include <atomic>
#include <cctype>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <opencv2/opencv.hpp>

#include "cv_bridge/cv_bridge.h"
#include "image_enc.h"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_action/rclcpp_action.hpp"
#include "rkllm.h"
#include "rkllm_ros2/action/chat_completion.hpp"
#include "sensor_msgs/image_encodings.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "std_msgs/msg/string.hpp"
#include "std_srvs/srv/trigger.hpp"

using namespace std::chrono_literals;

namespace rkllm_ros2_node {

class RunSession {
public:
  void AppendToken(const char * text)
  {
    if (!text || text[0] == '\0') {
      return;
    }
    std::lock_guard<std::mutex> lk(mtx_);
    accumulated_ += text;
  }

  std::string AccumulatedCopy()
  {
    std::lock_guard<std::mutex> lk(mtx_);
    return accumulated_;
  }

  void MarkFinish(const RKLLMResult * result)
  {
    std::lock_guard<std::mutex> lk(mtx_);
    if (result != nullptr) {
      last_perf_ = result->perf;
      perf_valid_ = true;
    }
    finished_ = true;
    cv_.notify_all();
  }

  void MarkError()
  {
    std::lock_guard<std::mutex> lk(mtx_);
    error_ = true;
    finished_ = true;
    cv_.notify_all();
  }

  void WaitFinish()
  {
    std::unique_lock<std::mutex> lk(mtx_);
    cv_.wait(lk, [this] { return finished_; });
  }

  bool ErrorCopy()
  {
    std::lock_guard<std::mutex> lk(mtx_);
    return error_;
  }

  bool PerfCopy(RKLLMPerfStat * out_perf)
  {
    std::lock_guard<std::mutex> lk(mtx_);
    if (!perf_valid_ || out_perf == nullptr) {
      return false;
    }
    *out_perf = last_perf_;
    return true;
  }

private:
  mutable std::mutex mtx_;
  std::condition_variable cv_;
  bool finished_{false};
  bool error_{false};
  std::string accumulated_;
  RKLLMPerfStat last_perf_{};
  bool perf_valid_{false};
};

struct CallbackUserdata {
  rclcpp::Node * node{nullptr};
  RunSession * session{nullptr};
  std::function<void(const std::string &, const std::string &)> on_feedback;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr chunk_pub;
};

static int LlmCallback(RKLLMResult * result, void * userdata, LLMCallState state)
{
  if (userdata == nullptr) {
    return 0;
  }
  auto * cb = static_cast<CallbackUserdata *>(userdata);
  if (!cb || !cb->session || !cb->on_feedback) {
    return 0;
  }

  switch (state) {
    case RKLLM_RUN_NORMAL:
      if (result != nullptr && result->text != nullptr && result->text[0] != '\0') {
        const std::string token(result->text);
        cb->session->AppendToken(result->text);

        try {
          cb->on_feedback(token, cb->session->AccumulatedCopy());
        } catch (const std::exception & e) {
          if (cb->node != nullptr) {
            RCLCPP_WARN(cb->node->get_logger(), "publish_feedback failed: %s", e.what());
          }
        }

        if (cb->chunk_pub) {
          std_msgs::msg::String chunk_msg;
          chunk_msg.data = token;
          cb->chunk_pub->publish(chunk_msg);
        }
      }
      break;
    case RKLLM_RUN_FINISH:
      cb->session->MarkFinish(result);
      break;
    case RKLLM_RUN_ERROR:
      if (cb->node != nullptr) {
        RCLCPP_ERROR(cb->node->get_logger(), "RKLLM_RUN_ERROR");
      }
      cb->session->MarkError();
      break;
    default:
      break;
  }
  return 0;
}

static cv::Mat ExpandToSquare(const cv::Mat & img, const cv::Scalar & background_color)
{
  const int width = img.cols;
  const int height = img.rows;
  if (width == height) {
    return img.clone();
  }
  const int size = std::max(width, height);
  cv::Mat result(size, size, img.type(), background_color);
  const int x_offset = (size - width) / 2;
  const int y_offset = (size - height) / 2;
  cv::Rect roi(x_offset, y_offset, width, height);
  img.copyTo(result(roi));
  return result;
}

static bool HasValidImage(const sensor_msgs::msg::Image & img)
{
  return img.height > 0 && img.width > 0 && !img.data.empty();
}

/** Trim ASCII whitespace (как в multimodal_model_demo sanitize_user_input). */
static std::string TrimCopy(std::string s)
{
  const auto not_space = [](unsigned char c) { return !std::isspace(c); };
  auto start = std::find_if(s.begin(), s.end(), not_space);
  auto end = std::find_if(s.rbegin(), s.rend(), not_space).base();
  if (start >= end) {
    return {};
  }
  return std::string(start, end);
}

static bool StartsWith(const std::string & s, const std::string & prefix)
{
  return s.size() >= prefix.size() &&
         std::equal(prefix.begin(), prefix.end(), s.begin());
}

/** Убирает случайные префиксы user:/robot: из вставок в терминал (demo). */
static std::string SanitizeUserMessage(std::string input)
{
  input = TrimCopy(std::move(input));
  while (true) {
    if (StartsWith(input, "user:")) {
      input = TrimCopy(input.substr(5));
      continue;
    }
    if (StartsWith(input, "robot:")) {
      input = TrimCopy(input.substr(6));
      continue;
    }
    break;
  }
  return input;
}

class RkllmNode : public rclcpp::Node {
public:
  using ChatCompletion = rkllm_ros2::action::ChatCompletion;
  using GoalHandleChatCompletion = rclcpp_action::ServerGoalHandle<ChatCompletion>;

  explicit RkllmNode()
  : Node("rkllm_ros2")
  {
    declare_parameter<std::string>("encoder_model_path", "");
    declare_parameter<std::string>("llm_model_path", "");
    declare_parameter<int>("max_new_tokens", 2048);
    declare_parameter<int>("max_context_len", 4096);
    declare_parameter<int>("rknn_core_num", 3);
    declare_parameter<std::string>("img_start", "<|vision_start|>");
    declare_parameter<std::string>("img_end", "<|vision_end|>");
    declare_parameter<std::string>("img_content", "<|image_pad|>");
    declare_parameter<int>("top_k", 20);
    declare_parameter<double>("top_p", 0.8);
    declare_parameter<double>("temperature", 0.7);
    declare_parameter<double>("repeat_penalty", 1.0);
    declare_parameter<double>("frequency_penalty", 0.0);
    declare_parameter<double>("presence_penalty", 0.0);
    declare_parameter<bool>("persist_session_kv", true);
    declare_parameter<std::string>("text_chunk_topic", "~/text_chunks");
    declare_parameter<std::string>("text_topic", "~/text");
    declare_parameter<bool>("apply_chat_template", false);
    // Если true — вызывается rkllm_set_chat_template (ОТКЛЮЧАЕТ встроенный разбор шаблона из .rkllm).
    // Для Qwen3-VL из multimodal_model_demo см. закомментированный вызов в upstream main.cpp — обычно оставляют авто-шаблон.
    declare_parameter<std::string>(
      "chat_template_system",
      "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n");
    declare_parameter<std::string>("chat_template_prefix", "<|im_start|>user\n");
    declare_parameter<std::string>(
      "chat_template_postfix", "<|im_end|>\n<|im_start|>assistant\n");
    declare_parameter<double>("clear_kv_after_idle_sec", 0.0);

    encoder_path_ = get_parameter("encoder_model_path").as_string();
    llm_path_ = get_parameter("llm_model_path").as_string();
    max_new_tokens_ = get_parameter("max_new_tokens").as_int();
    max_context_len_ = get_parameter("max_context_len").as_int();
    rknn_core_num_ = get_parameter("rknn_core_num").as_int();
    apply_chat_template_ = get_parameter("apply_chat_template").as_bool();
    chat_template_system_ = get_parameter("chat_template_system").as_string();
    if (chat_template_system_.empty()) {
      chat_template_system_ =
        "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n";
    }
    chat_template_prefix_ = get_parameter("chat_template_prefix").as_string();
    chat_template_postfix_ = get_parameter("chat_template_postfix").as_string();
    persist_session_kv_ = get_parameter("persist_session_kv").as_bool();
    clear_kv_after_idle_sec_ = get_parameter("clear_kv_after_idle_sec").as_double();

    if (encoder_path_.empty() || llm_path_.empty()) {
      RCLCPP_FATAL(
        get_logger(),
        "encoder_model_path и llm_model_path обязательны (непустые строки). "
        "Задайте параметры или аргументы launch.");
      throw std::runtime_error("rkllm_ros2: model paths not set");
    }

    chunk_pub_ = create_publisher<std_msgs::msg::String>(
      get_parameter("text_chunk_topic").as_string(), 10);
    text_pub_ = create_publisher<std_msgs::msg::String>(
      get_parameter("text_topic").as_string(),
      rclcpp::QoS(1).transient_local());

    if (!LoadModels()) {
      throw std::runtime_error("rkllm_ros2: LoadModels failed");
    }

    action_server_ = rclcpp_action::create_server<ChatCompletion>(
      this,
      "~/complete",
      std::bind(&RkllmNode::HandleGoal, this, std::placeholders::_1, std::placeholders::_2),
      std::bind(&RkllmNode::HandleCancel, this, std::placeholders::_1),
      std::bind(&RkllmNode::HandleAccepted, this, std::placeholders::_1));

    clear_kv_srv_ = create_service<std_srvs::srv::Trigger>(
      "~/clear_kv_cache",
      [this](
        const std::shared_ptr<std_srvs::srv::Trigger::Request>,
        std::shared_ptr<std_srvs::srv::Trigger::Response> response) {
        std::lock_guard<std::mutex> lk(busy_mtx_);
        if (busy_) {
          response->success = false;
          response->message = "busy";
          return;
        }
        if (llm_handle_ == nullptr) {
          response->success = false;
          response->message = "no llm handle";
          return;
        }
        const int cret = rkllm_clear_kv_cache(llm_handle_, 1, nullptr, nullptr);
        response->success = (cret == 0);
        response->message =
          (cret == 0) ? "ok" : ("rkllm_clear_kv_cache ret=" + std::to_string(cret));
      });

    last_llm_activity_ = std::chrono::steady_clock::now();
    if (clear_kv_after_idle_sec_ > 0.0) {
      idle_timer_ = create_wall_timer(
        std::chrono::seconds(5),
        std::bind(&RkllmNode::OnIdleKvTimer, this));
      RCLCPP_INFO(
        get_logger(),
        "Авто-сброс KV после %.1f с без запросов к LLM (тик таймера 5 с)",
        clear_kv_after_idle_sec_);
    }

    RCLCPP_INFO(
      get_logger(),
      "rkllm_ros2 ready; encoder=%s llm=%s; ChatCompletion ~/complete (text + optional image)",
      encoder_path_.c_str(), llm_path_.c_str());
  }

  ~RkllmNode() override
  {
    if (llm_handle_ != nullptr) {
      rkllm_destroy(llm_handle_);
      llm_handle_ = nullptr;
    }
    release_imgenc(&rknn_ctx_);
    memset(&rknn_ctx_, 0, sizeof(rknn_ctx_));
  }

  RkllmNode(const RkllmNode &) = delete;
  RkllmNode & operator=(const RkllmNode &) = delete;

private:
  bool LoadModels()
  {
    RKLLMParam param = rkllm_createDefaultParam();
    param.model_path = llm_path_.c_str();
    param.top_k = get_parameter("top_k").as_int();
    param.top_p = static_cast<float>(get_parameter("top_p").as_double());
    param.temperature = static_cast<float>(get_parameter("temperature").as_double());
    param.repeat_penalty = static_cast<float>(get_parameter("repeat_penalty").as_double());
    param.frequency_penalty = static_cast<float>(get_parameter("frequency_penalty").as_double());
    param.presence_penalty = static_cast<float>(get_parameter("presence_penalty").as_double());
    param.max_new_tokens = max_new_tokens_;
    param.max_context_len = max_context_len_;
    param.skip_special_token = true;
    param.extend_param.base_domain_id = 1;

    img_start_owned_ = get_parameter("img_start").as_string();
    img_end_owned_ = get_parameter("img_end").as_string();
    img_content_owned_ = get_parameter("img_content").as_string();
    param.img_start = img_start_owned_.c_str();
    param.img_end = img_end_owned_.c_str();
    param.img_content = img_content_owned_.c_str();

    const int ret_init = rkllm_init(&llm_handle_, &param, LlmCallback);
    if (ret_init != 0) {
      RCLCPP_FATAL(get_logger(), "rkllm_init failed ret=%d", ret_init);
      return false;
    }

    if (apply_chat_template_) {
      const int tret = rkllm_set_chat_template(
        llm_handle_,
        chat_template_system_.c_str(),
        chat_template_prefix_.c_str(),
        chat_template_postfix_.c_str());
      if (tret != 0) {
        RCLCPP_WARN(
          get_logger(),
          "rkllm_set_chat_template failed ret=%d (мультиход может вести себя странно)", tret);
      } else {
        RCLCPP_INFO(get_logger(), "rkllm_set_chat_template applied (ручной ChatML; отключён авто-шаблон RKLLM)");
      }
    } else {
      RCLCPP_INFO(
        get_logger(),
        "rkllm_set_chat_template отключён — используется встроенный шаблон модели "
        "(рекомендуется для Qwen3-VL из rknn-llm multimodal_model_demo)");
    }

    memset(&rknn_ctx_, 0, sizeof(rknn_ctx_));
    const int ret_enc = init_imgenc(encoder_path_.c_str(), &rknn_ctx_, rknn_core_num_);
    if (ret_enc != 0) {
      RCLCPP_FATAL(get_logger(), "init_imgenc failed ret=%d", ret_enc);
      rkllm_destroy(llm_handle_);
      llm_handle_ = nullptr;
      return false;
    }

    const auto n_tokens = static_cast<size_t>(rknn_ctx_.model_image_token);
    const auto embed_sz = static_cast<size_t>(rknn_ctx_.model_embed_size);
    const auto n_out = static_cast<size_t>(rknn_ctx_.io_num.n_output);
    rkllm_image_embed_len_ = n_tokens * embed_sz * n_out;
    img_vec_.resize(rkllm_image_embed_len_);
    std::fill(img_vec_.begin(), img_vec_.end(), 0.0F);

    image_width_ = static_cast<size_t>(rknn_ctx_.model_width);
    image_height_ = static_cast<size_t>(rknn_ctx_.model_height);
    n_image_tokens_ = n_tokens;

    return true;
  }

  void TouchLlmActivity()
  {
    std::lock_guard<std::mutex> lk(idle_mtx_);
    last_llm_activity_ = std::chrono::steady_clock::now();
  }

  void OnIdleKvTimer()
  {
    if (clear_kv_after_idle_sec_ <= 0.0) {
      return;
    }
    std::lock_guard<std::mutex> busy_lk(busy_mtx_);
    if (busy_) {
      return;
    }
    double idle_s = 0.0;
    {
      std::lock_guard<std::mutex> il(idle_mtx_);
      idle_s = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - last_llm_activity_).count();
    }
    if (idle_s < clear_kv_after_idle_sec_) {
      return;
    }
    if (llm_handle_ == nullptr) {
      return;
    }
    const int cret = rkllm_clear_kv_cache(llm_handle_, 1, nullptr, nullptr);
    {
      std::lock_guard<std::mutex> il(idle_mtx_);
      last_llm_activity_ = std::chrono::steady_clock::now();
    }
    if (cret == 0) {
      RCLCPP_INFO(
        get_logger(),
        "KV сброшен после %.0f с тишины (clear_kv_after_idle_sec=%.0f)",
        idle_s, clear_kv_after_idle_sec_);
    } else {
      RCLCPP_WARN(
        get_logger(),
        "Авто-сброс KV не удался ret=%d (idle %.0f с)",
        cret, idle_s);
    }
  }

  rclcpp_action::GoalResponse HandleGoal(
    const rclcpp_action::GoalUUID & uuid,
    std::shared_ptr<const ChatCompletion::Goal> goal)
  {
    (void)uuid;
    (void)goal;
    std::lock_guard<std::mutex> lk(busy_mtx_);
    if (busy_) {
      return rclcpp_action::GoalResponse::REJECT;
    }
    busy_ = true;
    return rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
  }

  rclcpp_action::CancelResponse HandleCancel(
    const std::shared_ptr<GoalHandleChatCompletion> goal_handle)
  {
    (void)goal_handle;
    if (llm_handle_ != nullptr) {
      rkllm_abort(llm_handle_);
    }
    return rclcpp_action::CancelResponse::ACCEPT;
  }

  void HandleAccepted(const std::shared_ptr<GoalHandleChatCompletion> goal_handle)
  {
    std::thread{[this, goal_handle]() { ExecuteCompletion(goal_handle); }}.detach();
  }

  void ExecuteCompletion(const std::shared_ptr<GoalHandleChatCompletion> goal_handle)
  {
    using SteadyClock = std::chrono::steady_clock;
    auto wall_ms = [](SteadyClock::time_point a, SteadyClock::time_point b) {
      return std::chrono::duration<double, std::milli>(b - a).count();
    };

    struct BusyRelease {
      std::mutex & mtx;
      bool & busy_flag;
      explicit BusyRelease(std::mutex & m, bool & b)
      : mtx(m), busy_flag(b) {}
      ~BusyRelease()
      {
        std::lock_guard<std::mutex> lk(mtx);
        busy_flag = false;
      }
    } release(busy_mtx_, busy_);

    struct MarkActivity {
      RkllmNode * self;
      explicit MarkActivity(RkllmNode * s)
      : self(s) {}
      ~MarkActivity()
      {
        if (self != nullptr) {
          self->TouchLlmActivity();
        }
      }
    } mark_activity{this};

    const SteadyClock::time_point t_goal_start = SteadyClock::now();

    auto result = std::make_shared<ChatCompletion::Result>();
    result->success = false;
    result->message.clear();
    result->text.clear();
    result->prefill_time_ms = 0.F;
    result->generate_time_ms = 0.F;
    result->generate_tokens = 0;

    const auto goal = goal_handle->get_goal();

    const std::string user_text = SanitizeUserMessage(goal->user_message);
    if (user_text.empty()) {
      result->message = "empty user_message";
      goal_handle->abort(result);
      return;
    }

    if (!persist_session_kv_) {
      if (!goal->keep_history) {
        const int cret = rkllm_clear_kv_cache(llm_handle_, 1, nullptr, nullptr);
        if (cret != 0) {
          RCLCPP_WARN(get_logger(), "rkllm_clear_kv_cache failed ret=%d", cret);
        }
      }
    }

    const SteadyClock::time_point t_after_kv_phase = SteadyClock::now();
    const double kv_sanitize_ms = wall_ms(t_goal_start, t_after_kv_phase);

    RKLLMInput rkllm_input;
    memset(&rkllm_input, 0, sizeof(RKLLMInput));
    rkllm_input.role = "user";

    std::vector<char> prompt_buf;
    const bool use_image = HasValidImage(goal->image);

    double cv_resize_ms = 0.;
    double imgenc_ms = 0.;

    if (use_image) {
      const SteadyClock::time_point t_cv_start = SteadyClock::now();
      cv_bridge::CvImageConstPtr cv_ptr;
      try {
        cv_ptr = cv_bridge::toCvCopy(goal->image, sensor_msgs::image_encodings::RGB8);
      } catch (const cv_bridge::Exception & e) {
        result->message = std::string("cv_bridge: ") + e.what();
        goal_handle->abort(result);
        return;
      }

      cv::Mat img = cv_ptr->image;
      const cv::Scalar background_color(127.5, 127.5, 127.5);
      cv::Mat square_img = ExpandToSquare(img, background_color);
      cv::Mat resized_img;
      const cv::Size new_size(static_cast<int>(image_width_), static_cast<int>(image_height_));
      cv::resize(square_img, resized_img, new_size, 0, 0, cv::INTER_LINEAR);

      const SteadyClock::time_point t_cv_end = SteadyClock::now();
      cv_resize_ms = wall_ms(t_cv_start, t_cv_end);

      const SteadyClock::time_point t_enc_start = SteadyClock::now();
      const int ret_img = run_imgenc(&rknn_ctx_, resized_img.data, img_vec_.data());
      const SteadyClock::time_point t_enc_end = SteadyClock::now();
      imgenc_ms = wall_ms(t_enc_start, t_enc_end);
      if (ret_img != 0) {
        result->message = "run_imgenc failed ret=" + std::to_string(ret_img);
        goal_handle->abort(result);
        return;
      }

      const std::string multimodal_prompt = std::string("<image>") + user_text;
      prompt_buf.assign(multimodal_prompt.begin(), multimodal_prompt.end());
      prompt_buf.push_back('\0');

      rkllm_input.input_type = RKLLM_INPUT_MULTIMODAL;
      rkllm_input.multimodal_input.prompt = prompt_buf.data();
      rkllm_input.multimodal_input.image_embed = img_vec_.data();
      rkllm_input.multimodal_input.n_image_tokens = n_image_tokens_;
      rkllm_input.multimodal_input.n_image = 1;
      rkllm_input.multimodal_input.image_height = image_height_;
      rkllm_input.multimodal_input.image_width = image_width_;
    } else {
      prompt_buf.assign(user_text.begin(), user_text.end());
      prompt_buf.push_back('\0');
      rkllm_input.input_type = RKLLM_INPUT_PROMPT;
      rkllm_input.prompt_input = prompt_buf.data();
    }

    RKLLMInferParam infer_params;
    memset(&infer_params, 0, sizeof(RKLLMInferParam));
    infer_params.mode = RKLLM_INFER_GENERATE;
    infer_params.keep_history = persist_session_kv_ ? 1 : (goal->keep_history ? 1 : 0);

    if (goal->max_new_tokens != 0 &&
      goal->max_new_tokens != max_new_tokens_)
    {
      RCLCPP_WARN_THROTTLE(
        get_logger(), *get_clock(), 5000,
        "goal.max_new_tokens=%d ignored (RKLLM uses init-time max_new_tokens=%d)",
        goal->max_new_tokens, max_new_tokens_);
    }

    RunSession session;
    CallbackUserdata userdata;
    userdata.node = this;
    userdata.session = &session;
    userdata.on_feedback =
      [goal_handle](const std::string & token, const std::string & accum) {
        auto feedback = std::make_shared<ChatCompletion::Feedback>();
        feedback->token = token;
        feedback->text = accum;
        goal_handle->publish_feedback(feedback);
      };
    userdata.chunk_pub = chunk_pub_;

    std::atomic<bool> poll_stop{false};
    std::thread cancel_poll([this, goal_handle, &poll_stop]() {
      while (rclcpp::ok() && !poll_stop.load(std::memory_order_acquire)) {
        if (goal_handle->is_canceling()) {
          if (llm_handle_ != nullptr) {
            rkllm_abort(llm_handle_);
          }
          break;
        }
        std::this_thread::sleep_for(50ms);
      }
    });

    const SteadyClock::time_point t_llm_start = SteadyClock::now();
    const int ret_run = rkllm_run(llm_handle_, &rkllm_input, &infer_params, &userdata);
    const SteadyClock::time_point t_llm_end = SteadyClock::now();
    const double rkllm_run_wall_ms = wall_ms(t_llm_start, t_llm_end);

    poll_stop.store(true, std::memory_order_release);
    cancel_poll.join();

    session.WaitFinish();

    result->text = session.AccumulatedCopy();

    if (goal_handle->is_canceling()) {
      result->success = false;
      result->message = "canceled";
      goal_handle->canceled(result);
      return;
    }

    if (ret_run != 0 || session.ErrorCopy()) {
      result->success = false;
      result->message =
        session.ErrorCopy() ? "RKLLM_RUN_ERROR" :
        ("rkllm_run failed ret=" + std::to_string(ret_run));
      goal_handle->abort(result);
      return;
    }

    RKLLMPerfStat perf{};
    float rk_prefill_ms = 0.F;
    float rk_gen_ms = 0.F;
    int gen_tokens = 0;
    if (session.PerfCopy(&perf)) {
      result->prefill_time_ms = perf.prefill_time_ms;
      result->generate_time_ms = perf.generate_time_ms;
      result->generate_tokens = perf.generate_tokens;
      rk_prefill_ms = perf.prefill_time_ms;
      rk_gen_ms = perf.generate_time_ms;
      gen_tokens = perf.generate_tokens;
    }

    const SteadyClock::time_point t_goal_end = SteadyClock::now();
    const double goal_wall_total_ms = wall_ms(t_goal_start, t_goal_end);
    const double prep_after_kv_ms = wall_ms(t_after_kv_phase, t_llm_start);

    RCLCPP_INFO(
      get_logger(),
      "timing goal multimodal=%s goal_wall_total_ms=%.1f kv_sanitize_ms=%.1f prep_after_kv_ms=%.1f "
      "(cv_resize_ms=%.1f imgenc_ms=%.1f) rkllm_run_wall_ms=%.1f rk_prefill_ms=%.1f rk_generate_ms=%.1f tokens=%d",
      use_image ? "yes" : "no",
      goal_wall_total_ms,
      kv_sanitize_ms,
      prep_after_kv_ms,
      cv_resize_ms,
      imgenc_ms,
      rkllm_run_wall_ms,
      static_cast<double>(rk_prefill_ms),
      static_cast<double>(rk_gen_ms),
      static_cast<int>(gen_tokens));

    result->success = true;
    result->message = "ok";

    std_msgs::msg::String full_msg;
    full_msg.data = result->text;
    text_pub_->publish(full_msg);

    goal_handle->succeed(result);
  }

  LLMHandle llm_handle_{nullptr};
  rknn_app_context_t rknn_ctx_{};

  std::string encoder_path_;
  std::string llm_path_;
  int max_new_tokens_{2048};
  int max_context_len_{4096};
  int rknn_core_num_{3};

  std::string img_start_owned_;
  std::string img_end_owned_;
  std::string img_content_owned_;

  size_t n_image_tokens_{0};
  size_t rkllm_image_embed_len_{0};
  std::vector<float> img_vec_;
  size_t image_width_{0};
  size_t image_height_{0};

  std::mutex busy_mtx_;
  bool busy_{false};

  std::mutex idle_mtx_;
  std::chrono::steady_clock::time_point last_llm_activity_;
  double clear_kv_after_idle_sec_{0.0};
  rclcpp::TimerBase::SharedPtr idle_timer_;

  bool persist_session_kv_{true};

  bool apply_chat_template_{false};
  std::string chat_template_system_;
  std::string chat_template_prefix_;
  std::string chat_template_postfix_;

  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr chunk_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr text_pub_;

  rclcpp_action::Server<ChatCompletion>::SharedPtr action_server_;
  rclcpp::Service<std_srvs::srv::Trigger>::SharedPtr clear_kv_srv_;
};

}  // namespace rkllm_ros2_node

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  try {
    auto node = std::make_shared<rkllm_ros2_node::RkllmNode>();
    rclcpp::spin(node);
  } catch (const std::exception & e) {
    RCLCPP_FATAL(rclcpp::get_logger("rkllm_ros2"), "%s", e.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
