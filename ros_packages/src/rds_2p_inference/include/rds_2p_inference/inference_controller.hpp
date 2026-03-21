#ifndef RDS_2P_INFERENCE_INFERENCE_CONTROLLER_HPP_
#define RDS_2P_INFERENCE_INFERENCE_CONTROLLER_HPP_

#include <string>
#include <array>
#include <memory>
#include <mutex>

#include <onnxruntime_cxx_api.h>
#include <sensor_msgs/msg/joint_state.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <nav_msgs/msg/odometry.hpp>

namespace rds2p {

class InferenceController {
public:
  InferenceController(
    const std::string& model_path,
    const std::array<float, 12>& default_angles = {},
    float action_scale = 0.18f,
    float vel_scale_x = 0.5f,
    float vel_scale_y = 0.5f,
    float vel_scale_rot = 1.0f,
    bool static_linvel = true
  );

  void set_cmd_vel(float linear_x, float linear_y, float angular_z);
  std::array<float, 3> get_cmd_vel() const;

  void set_default_angles(const std::array<float, 12>& angles);

  void update_joint_states(const sensor_msgs::msg::JointState::SharedPtr& msg);
  void update_imu_data(const sensor_msgs::msg::Imu::SharedPtr& msg);
  void update_odom_data(const nav_msgs::msg::Odometry::SharedPtr& msg);
  
  bool can_run_inference() const;
  std::array<float, 12> run_inference_sync();

private:
  std::array<std::array<float, 3>, 3> quaternion_to_rotation_matrix(
    const std::array<float, 4>& quat
  ) const;
  
  std::array<float, 3> matrix_vector_multiply(
    const std::array<std::array<float, 3>, 3>& mat,
    const std::array<float, 3>& vec
  ) const;

  // ONNX Runtime
  Ort::Env env_;
  Ort::SessionOptions session_options_;
  std::unique_ptr<Ort::Session> session_ptr_;

  // Control parameters
  float action_scale_;
  std::array<float, 12> default_angles_;
  mutable std::mutex default_angles_mutex_;
  float vel_scale_x_, vel_scale_y_, vel_scale_rot_;
  bool static_linvel_;
  std::array<float, 3> static_linvel_value_;
  float action_filter_alpha_;
  float control_frequency_;

  // State
  std::array<float, 12> last_action_;
  std::array<float, 3> cmd_vel_;
  mutable std::mutex cmd_vel_mutex_;

  // Sensor data (protected by mutex)
  mutable std::mutex sensor_data_mutex_;
  sensor_msgs::msg::JointState::SharedPtr latest_joint_states_;
  sensor_msgs::msg::Imu::SharedPtr latest_imu_data_;
  nav_msgs::msg::Odometry::SharedPtr latest_odom_data_;
};

} // namespace rds2p

#endif // RDS_2P_INFERENCE_INFERENCE_CONTROLLER_HPP_
