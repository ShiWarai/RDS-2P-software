#include "rds_2p_inference/inference_controller.hpp"
#include <cmath>
#include <stdexcept>
#include <algorithm>
#include <iostream>
#include <fstream>

namespace rds2p {

InferenceController::InferenceController(
  const std::string& model_path,
  const std::array<float, 12>& default_angles,
  float action_scale,
  float vel_scale_x,
  float vel_scale_y,
  float vel_scale_rot,
  bool static_linvel
)
  : env_(ORT_LOGGING_LEVEL_WARNING, "RDS2P_Inference"),
    action_scale_(action_scale),
    default_angles_(default_angles),
    vel_scale_x_(vel_scale_x),
    vel_scale_y_(vel_scale_y),
    vel_scale_rot_(vel_scale_rot),
    static_linvel_(static_linvel),
    action_filter_alpha_(0.8f),
    control_frequency_(50.0)
{
  // Инициализация массивов нулями
  last_action_.fill(0.0f);
  cmd_vel_.fill(0.0f);
  static_linvel_value_.fill(0.0f);

  // Проверка существования файла модели
  std::ifstream file_check(model_path);
  if (!file_check.good()) {
    throw std::runtime_error("Model file not found: " + model_path);
  }
  file_check.close();

  // Настройка параметров сессии для выполнения на CPU
  session_options_.SetIntraOpNumThreads(1);
  session_options_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);

  // Создание сессии после настройки параметров
  try {
    session_ptr_ = std::make_unique<Ort::Session>(env_, model_path.c_str(), session_options_);
    std::cout << "ONNX session created successfully from: " << model_path << std::endl;
  } catch (const std::exception& e) {
    throw std::runtime_error("Failed to create ONNX session: " + std::string(e.what()));
  }
}

void InferenceController::set_cmd_vel(float linear_x, float linear_y, float angular_z) {
  std::lock_guard<std::mutex> lock(cmd_vel_mutex_);
  cmd_vel_[0] = linear_x * vel_scale_x_;
  cmd_vel_[1] = linear_y * vel_scale_y_;
  cmd_vel_[2] = angular_z * vel_scale_rot_;
}

std::array<float, 3> InferenceController::get_cmd_vel() const {
  std::lock_guard<std::mutex> lock(cmd_vel_mutex_);
  return cmd_vel_;
}

void InferenceController::set_default_angles(const std::array<float, 12>& angles) {
  std::lock_guard<std::mutex> lock(default_angles_mutex_);
  default_angles_ = angles;
}

void InferenceController::update_joint_states(
  const sensor_msgs::msg::JointState::SharedPtr& msg
) {
  std::lock_guard<std::mutex> lock(sensor_data_mutex_);
  latest_joint_states_ = msg;
}

void InferenceController::update_imu_data(
  const sensor_msgs::msg::Imu::SharedPtr& msg
) {
  std::lock_guard<std::mutex> lock(sensor_data_mutex_);
  latest_imu_data_ = msg;
}

void InferenceController::update_odom_data(
  const nav_msgs::msg::Odometry::SharedPtr& msg
) {
  std::lock_guard<std::mutex> lock(sensor_data_mutex_);
  latest_odom_data_ = msg;
}

bool InferenceController::can_run_inference() const {
  std::lock_guard<std::mutex> lock(sensor_data_mutex_);
  return (latest_joint_states_ != nullptr && latest_imu_data_ != nullptr);
}

std::array<float, 12> InferenceController::run_inference_sync() {
  std::array<float, 12> zero_commands;
  zero_commands.fill(0.0f);

  if (!can_run_inference()) {
    return zero_commands;
  }

  // Копирование данных датчиков в локальные переменные
  sensor_msgs::msg::JointState::SharedPtr joint_states;
  sensor_msgs::msg::Imu::SharedPtr imu_data;
  
  {
    std::lock_guard<std::mutex> lock(sensor_data_mutex_);
    joint_states = latest_joint_states_;
    imu_data = latest_imu_data_;
  }

  try {
    // Извлечение позиций и скоростей суставов
    if (joint_states->position.size() != 12 || joint_states->velocity.size() != 12) {
      std::cerr << "Invalid joint state size: positions=" << joint_states->position.size()
                << ", velocities=" << joint_states->velocity.size() << std::endl;
      return zero_commands;
    }

    std::array<float, 12> joint_positions;
    std::array<float, 12> joint_velocities;
    for (size_t i = 0; i < 12; ++i) {
      joint_positions[i] = static_cast<float>(joint_states->position[i]);
      joint_velocities[i] = static_cast<float>(joint_states->velocity[i]);
    }

    // Извлечение данных IMU
    std::array<float, 3> gyro = {
      static_cast<float>(imu_data->angular_velocity.x),
      static_cast<float>(imu_data->angular_velocity.y),
      static_cast<float>(imu_data->angular_velocity.z)
    };

    // Преобразование кватерниона в матрицу поворота для вычисления гравитации
    std::array<float, 4> quat = {
      static_cast<float>(imu_data->orientation.w),
      static_cast<float>(imu_data->orientation.x),
      static_cast<float>(imu_data->orientation.y),
      static_cast<float>(imu_data->orientation.z)
    };
    
    auto imu_xmat = quaternion_to_rotation_matrix(quat);
    
    // Вычисление вектора гравитации: R^T * [0, 0, -1]
    std::array<float, 3> gravity_base = {0.0f, 0.0f, -1.0f};
    std::array<float, 3> gravity;
    for (size_t i = 0; i < 3; ++i) {
      gravity[i] = 0.0f;
      for (size_t j = 0; j < 3; ++j) {
        gravity[i] += imu_xmat[j][i] * gravity_base[j];  // Умножение с транспонированием
      }
    }

    // Обработка данных одометрии - извлечение линейной скорости из /odom/raw
    std::array<float, 3> linvel = {0.0f, 0.0f, 0.0f};
    nav_msgs::msg::Odometry::SharedPtr odom_data;
    {
      std::lock_guard<std::mutex> lock(sensor_data_mutex_);
      odom_data = latest_odom_data_;
    }
    
    if (odom_data != nullptr) {
      // Извлечение линейной скорости из одометрии (в системе координат base_link)
      // Обнуление малых значений (меньше 0.0001) для фильтрации шума
      constexpr float threshold = 0.0001f;
      auto& twist = odom_data->twist.twist.linear;
      linvel[0] = (std::abs(twist.x) < threshold) ? 0.0f : static_cast<float>(twist.x);
      linvel[1] = (std::abs(twist.y) < threshold) ? 0.0f : static_cast<float>(twist.y);
      linvel[2] = (std::abs(twist.z) < threshold) ? 0.0f : static_cast<float>(twist.z);
    }

    // Вычисление углов суставов относительно значений по умолчанию
    std::array<float, 12> current_default_angles;
    {
      std::lock_guard<std::mutex> lock(default_angles_mutex_);
      current_default_angles = default_angles_;
    }
    std::array<float, 12> joint_angles;
    for (size_t i = 0; i < 12; ++i) {
      joint_angles[i] = joint_positions[i] - current_default_angles[i];
    }

    // Получение команды скорости
    auto cmd_vel = get_cmd_vel();

    // Подготовка наблюдения (48 измерений)
    // linvel(3) + gyro(3) + gravity(3) + joint_angles(12) + joint_velocities(12) + last_action(12) + cmd_vel(3)
    std::vector<float> obs(48);
    size_t idx = 0;
    
    // Копирование linvel
    for (size_t i = 0; i < 3; ++i) obs[idx++] = linvel[i];
    
    // Копирование gyro
    for (size_t i = 0; i < 3; ++i) obs[idx++] = gyro[i];
    
    // Копирование gravity
    for (size_t i = 0; i < 3; ++i) obs[idx++] = gravity[i];
    
    // Копирование joint_angles
    for (size_t i = 0; i < 12; ++i) obs[idx++] = joint_angles[i];
    
    // Копирование joint_velocities
    for (size_t i = 0; i < 12; ++i) obs[idx++] = joint_velocities[i];
    
    // Копирование last_action
    for (size_t i = 0; i < 12; ++i) obs[idx++] = last_action_[i];
    
    // Копирование cmd_vel
    for (size_t i = 0; i < 3; ++i) obs[idx++] = cmd_vel[i];

    // Запуск ONNX inference
    std::vector<int64_t> input_shape = {1, 48};
    
    auto memory_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
      memory_info, obs.data(), obs.size(), input_shape.data(), input_shape.size()
    );

    // Получение имен входов и выходов
    const char* input_names[] = {"obs"};
    const char* output_names[] = {"continuous_actions"};

    // Выполнение inference
    auto output_tensors = session_ptr_->Run(
      Ort::RunOptions{nullptr},
      input_names, &input_tensor, 1,
      output_names, 1
    );

    // Извлечение выходных данных
    float* output_data = output_tensors[0].GetTensorMutableData<float>();
    
    // Применение мягкой фильтрации для стабильности
    std::array<float, 12> filtered_action;
    for (size_t i = 0; i < 12; ++i) {
      filtered_action[i] = action_filter_alpha_ * output_data[i] + 
                          (1.0f - action_filter_alpha_) * last_action_[i];
    }

    // Мягкое ограничение углов для предотвращения экстремальных позиций
    const float max_angle_limit = 1.0f;
    for (size_t i = 0; i < 12; ++i) {
      filtered_action[i] = std::clamp(filtered_action[i], -max_angle_limit, max_angle_limit);
    }

    last_action_ = filtered_action;

    // Вычисление финальных команд для суставов
    std::array<float, 12> joint_commands;
    {
      std::lock_guard<std::mutex> lock(default_angles_mutex_);
      for (size_t i = 0; i < 12; ++i) {
        joint_commands[i] = filtered_action[i] * action_scale_ + default_angles_[i];
      }
    }

    return joint_commands;

  } catch (const std::exception& e) {
    std::cerr << "Inference error: " << e.what() << std::endl;
    return zero_commands;
  }
}

std::array<std::array<float, 3>, 3> InferenceController::quaternion_to_rotation_matrix(
  const std::array<float, 4>& quat
) const {
  float w = quat[0], x = quat[1], y = quat[2], z = quat[3];

  // Нормализация кватерниона
  float norm = std::sqrt(w*w + x*x + y*y + z*z);
  w /= norm; x /= norm; y /= norm; z /= norm;

  // Преобразование в матрицу поворота
  std::array<std::array<float, 3>, 3> R;
  R[0][0] = 1.0f - 2.0f*(y*y + z*z);
  R[0][1] = 2.0f*(x*y - w*z);
  R[0][2] = 2.0f*(x*z + w*y);
  
  R[1][0] = 2.0f*(x*y + w*z);
  R[1][1] = 1.0f - 2.0f*(x*x + z*z);
  R[1][2] = 2.0f*(y*z - w*x);
  
  R[2][0] = 2.0f*(x*z - w*y);
  R[2][1] = 2.0f*(y*z + w*x);
  R[2][2] = 1.0f - 2.0f*(x*x + y*y);

  return R;
}

std::array<float, 3> InferenceController::matrix_vector_multiply(
  const std::array<std::array<float, 3>, 3>& mat,
  const std::array<float, 3>& vec
) const {
  std::array<float, 3> result;
  for (size_t i = 0; i < 3; ++i) {
    result[i] = 0.0f;
    for (size_t j = 0; j < 3; ++j) {
      result[i] += mat[i][j] * vec[j];
    }
  }
  return result;
}

} // namespace rds2p

