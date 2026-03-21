/**
 * ROS2 узел inference для робота RDS-2P.
 *
 * Этот узел:
 * - Подписывается на /joint_states, /imu и /odom/raw для данных датчиков
 * - Выполняет inference ONNX политики
 * - Публикует команды суставов в /joint_commands с частотой 50Hz
 *
 * Топики:
 *   Подписки:
 *     /joint_states (sensor_msgs/JointState): Текущие позиции и скорости суставов
 *     /imu (sensor_msgs/Imu): Данные IMU (гироскоп, ориентация, ускорение)
 *     /odom/raw (nav_msgs/Odometry): Данные одометрии (линейная и угловая скорость)
 *     /cmd_vel (geometry_msgs/Twist): Команды скорости
 *   
 *   Публикации:
 *     /joint_commands (sensor_msgs/JointState): Целевые позиции суставов (команды) - 50Hz
 */

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <sensor_msgs/msg/joy.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <rmw/qos_profiles.h>
#include <ament_index_cpp/get_package_share_directory.hpp>

#include "rds_2p_inference/inference_controller.hpp"

#include <chrono>
#include <memory>
#include <vector>
#include <string>
#include <filesystem>
#include <cmath>
#include <array>
#include <mutex>

using namespace std::chrono_literals;

// Базовые углы по умолчанию для 12 суставов (соответствует home keyframe)
constexpr std::array<float, 12> DEFAULT_ANGLES = {
  0.0f, 0.0f, 0.0f,  // leg_block_fl_joint, hip_fl_joint, shin_fl_joint
  0.0f, 0.0f, 0.0f,  // leg_block_fr_joint, hip_fr_joint, shin_fr_joint
  0.0f, 0.0f, 0.0f,  // leg_block_bl_joint, hip_bl_joint, shin_bl_joint
  0.0f, 0.0f, 0.0f   // leg_block_br_joint, hip_br_joint, shin_br_joint
};

// Поза при roll = -90° (наклон влево)
constexpr std::array<float, 12> POSE_ROLL_NEG90 = {
  0.0f, -0.2094f, 0.424144f,  // leg_block_fl_joint, hip_fl_joint, shin_fl_joint
  0.0f, -0.2094f, 0.424144f,  // leg_block_fr_joint, hip_fr_joint, shin_fr_joint
  0.0f, 0.51303f, -0.487536f, // leg_block_bl_joint, hip_bl_joint, shin_bl_joint
  0.0f, 0.51303f, -0.487536f  // leg_block_br_joint, hip_br_joint, shin_br_joint
};

// Поза при roll = +90° (наклон вправо)
constexpr std::array<float, 12> POSE_ROLL_POS90 = {
  0.0f, 0.51303f, -0.487536f, // leg_block_fl_joint, hip_fl_joint, shin_fl_joint
  0.0f, 0.51303f, -0.487536f, // leg_block_fr_joint, hip_fr_joint, shin_fr_joint
  0.0f, -0.2094f, 0.424144f,  // leg_block_bl_joint, hip_bl_joint, shin_bl_joint
  0.0f, -0.2094f, 0.424144f   // leg_block_br_joint, hip_br_joint, shin_br_joint
};

class InferenceNode : public rclcpp::Node {
public:
  InferenceNode(std::shared_ptr<rds2p::InferenceController> controller)
    : Node("rds2p_inference"),
      controller_(controller),
      current_roll_rad_(0.0),
      current_pitch_rad_(0.0),
      r1_pressed_(false),
      inference_enabled_(true),
      triangle_pressed_(false)
  {
    // Имена суставов для RDS-2P (из MJCF файла)
    joint_names_ = {
      "leg_block_fl_joint", "hip_fl_joint", "shin_fl_joint",
      "leg_block_fr_joint", "hip_fr_joint", "shin_fr_joint",
      "leg_block_bl_joint", "hip_bl_joint", "shin_bl_joint",
      "leg_block_br_joint", "hip_br_joint", "shin_br_joint"
    };

    // QoS профили для датчиков (оптимизированы для минимальной задержки)
    auto sensor_qos = rclcpp::QoS(1)
      .reliability(RMW_QOS_POLICY_RELIABILITY_BEST_EFFORT)
      .durability(RMW_QOS_POLICY_DURABILITY_VOLATILE)
      .history(RMW_QOS_POLICY_HISTORY_KEEP_LAST);

    // QoS профиль для команд суставов (должен соответствовать joint_to_motor_bridge)
    auto cmd_qos = rclcpp::QoS(1)
      .reliability(RMW_QOS_POLICY_RELIABILITY_RELIABLE)
      .durability(RMW_QOS_POLICY_DURABILITY_VOLATILE)
      .history(RMW_QOS_POLICY_HISTORY_KEEP_LAST);

    // Подписки на данные датчиков
    joint_states_sub_ = this->create_subscription<sensor_msgs::msg::JointState>(
      "/joint_states",
      sensor_qos,
      std::bind(&InferenceNode::joint_states_callback, this, std::placeholders::_1)
    );

    imu_sub_ = this->create_subscription<sensor_msgs::msg::Imu>(
      "/imu",
      sensor_qos,
      std::bind(&InferenceNode::imu_callback, this, std::placeholders::_1)
    );

    // Подписка на одометрию
    odom_sub_ = this->create_subscription<nav_msgs::msg::Odometry>(
      "/odom/raw",
      sensor_qos,
      std::bind(&InferenceNode::odom_callback, this, std::placeholders::_1)
    );

    // Подписка на команды скорости
    cmd_vel_sub_ = this->create_subscription<geometry_msgs::msg::Twist>(
      "/cmd_vel",
      10,
      std::bind(&InferenceNode::cmd_vel_callback, this, std::placeholders::_1)
    );

    // Подписка на данные джойстика IMU
    joy_imu_sub_ = this->create_subscription<sensor_msgs::msg::Imu>(
      "/joy/imu",
      sensor_qos,
      std::bind(&InferenceNode::joy_imu_callback, this, std::placeholders::_1)
    );

    // Подписка на данные джойстика (для проверки кнопки R1)
    joy_sub_ = this->create_subscription<sensor_msgs::msg::Joy>(
      "/joy",
      10,
      std::bind(&InferenceNode::joy_callback, this, std::placeholders::_1)
    );

    // Публикатор команд суставов
    joint_commands_pub_ = this->create_publisher<sensor_msgs::msg::JointState>(
      "/joint_commands",
      cmd_qos
    );

    // Таймер для публикации команд с частотой 50Hz (20ms)
    timer_ = this->create_wall_timer(
      20ms,
      std::bind(&InferenceNode::timer_callback, this)
    );

    RCLCPP_INFO(this->get_logger(), "=== Инициализация Inference Node ===");
    RCLCPP_INFO(this->get_logger(), "Подписки: /joint_states, /imu, /odom/raw, /cmd_vel, /joy/imu, /joy");
    RCLCPP_INFO(this->get_logger(), "Публикация: /joint_commands (50Hz)");
    RCLCPP_INFO(this->get_logger(), "QoS оптимизирован для минимальной задержки");
    RCLCPP_INFO(this->get_logger(), "Обновление наклона активируется кнопкой R1");
    RCLCPP_INFO(this->get_logger(), "Включение/выключение инференса - кнопка треугольник");
    RCLCPP_INFO(this->get_logger(), "=== Inference Node готов! ===");
  }

private:
  void joint_states_callback(const sensor_msgs::msg::JointState::SharedPtr msg) {
    controller_->update_joint_states(msg);
  }

  void imu_callback(const sensor_msgs::msg::Imu::SharedPtr msg) {
    controller_->update_imu_data(msg);
  }

  void odom_callback(const nav_msgs::msg::Odometry::SharedPtr msg) {
    controller_->update_odom_data(msg);
  }

  void cmd_vel_callback(const geometry_msgs::msg::Twist::SharedPtr msg) {
    controller_->set_cmd_vel(
      static_cast<float>(msg->linear.x),
      static_cast<float>(msg->linear.y),
      static_cast<float>(msg->angular.z)
    );
  }

  void joy_callback(const sensor_msgs::msg::Joy::SharedPtr msg) {
    // Проверяем состояние кнопки R1 (кнопка 10 для PS4)
    bool r1_pressed = false;
    if (msg->buttons.size() > 10) {
      r1_pressed = (msg->buttons[10] == 1);
    }
    
    // Проверяем, было ли изменение состояния R1
    bool r1_was_pressed = false;
    {
      std::lock_guard<std::mutex> lock(r1_mutex_);
      r1_was_pressed = r1_pressed_;
      r1_pressed_ = r1_pressed;
    }
    
    // Если R1 была нажата, а теперь отпущена - возвращаемся к дефолтной позе
    if (r1_was_pressed && !r1_pressed) {
      controller_->set_default_angles(DEFAULT_ANGLES);
      RCLCPP_INFO(this->get_logger(), "R1 отпущена - возврат к дефолтной позе");
    }

    // Проверяем состояние кнопки треугольник (кнопка 3 для PS4)
    bool triangle_pressed = false;
    if (msg->buttons.size() > 3) {
      triangle_pressed = (msg->buttons[3] == 1);
    }
    
    // Проверяем, было ли изменение состояния треугольник (edge detection)
    bool triangle_was_pressed = false;
    {
      std::lock_guard<std::mutex> lock(triangle_mutex_);
      triangle_was_pressed = triangle_pressed_;
      triangle_pressed_ = triangle_pressed;
    }
    
    // Если треугольник была нажата (переход из 0 в 1) - переключаем инференс
    if (!triangle_was_pressed && triangle_pressed) {
      std::lock_guard<std::mutex> lock(inference_enabled_mutex_);
      inference_enabled_ = !inference_enabled_;
      RCLCPP_INFO(this->get_logger(), "Кнопка треугольник нажата - инференс %s", 
                  inference_enabled_ ? "включен" : "выключен");
    }
  }

  void joy_imu_callback(const sensor_msgs::msg::Imu::SharedPtr msg) {
    // Извлечение кватерниона
    double w = msg->orientation.w;
    double x = msg->orientation.x;
    double y = msg->orientation.y;
    double z = msg->orientation.z;

    // Вычисление pitch и roll из кватерниона
    // Roll (крен) - вращение вокруг оси X
    double roll = std::atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y));
    
    // Pitch (тангаж) - вращение вокруг оси Y
    double pitch = std::asin(2.0 * (w * y - z * x));

    // Сохраняем текущий roll и pitch
    {
      std::lock_guard<std::mutex> lock(roll_mutex_);
      current_roll_rad_ = roll;
      current_pitch_rad_ = pitch;
    }

    // Проверяем, нажата ли кнопка R1
    bool r1_pressed = false;
    {
      std::lock_guard<std::mutex> lock(r1_mutex_);
      r1_pressed = r1_pressed_;
    }

    // Обновляем default_angles на основе roll и pitch только если R1 нажата
    if (r1_pressed) {
      update_default_angles_from_roll_pitch(roll, pitch);
    }
  }

  void update_default_angles_from_roll_pitch(double roll_rad, double pitch_rad) {
    // Преобразуем roll и pitch из радиан в градусы
    double roll_deg = roll_rad * 180.0 / M_PI;
    double pitch_deg = pitch_rad * 180.0 / M_PI;
    
    // Ограничиваем roll диапазоном от -45° до +45°
    roll_deg = std::clamp(roll_deg, -45.0, 45.0);
    
    // Ограничиваем pitch диапазоном от -60° до +60°
    pitch_deg = std::clamp(pitch_deg, -60.0, 60.0);
    
    // Вычисляем коэффициент интерполяции для roll (0.0 для -45°, 1.0 для +45°)
    double alpha_roll = (roll_deg + 45.0) / 90.0;
    
    // Вычисляем коэффициент интерполяции для pitch (0.0 для -60°, 1.0 для +60°)
    // pitch = -60° -> leg_block = -0.4, pitch = +60° -> leg_block = +0.4
    double alpha_pitch = (pitch_deg + 60.0) / 120.0;
    double leg_block_value = -0.4 + alpha_pitch * 0.8;  // от -0.4 до +0.4
    
    // Интерполируем между двумя позами для roll (влияет на hip и shin - индексы 1,2,4,5,7,8,10,11)
    std::array<float, 12> interpolated_angles;
    for (size_t i = 0; i < 12; ++i) {
      // Для первых суставов (leg_block) используем pitch: индексы 0, 3, 6, 9
      if (i % 3 == 0) {
        interpolated_angles[i] = static_cast<float>(leg_block_value);
      } else {
        // Для hip и shin используем roll: индексы 1,2,4,5,7,8,10,11
        interpolated_angles[i] = static_cast<float>(
          POSE_ROLL_NEG90[i] * (1.0 - alpha_roll) + POSE_ROLL_POS90[i] * alpha_roll
        );
      }
    }
    
    // Обновляем default_angles в контроллере
    controller_->set_default_angles(interpolated_angles);
  }

  void timer_callback() {
    // Проверяем, включен ли инференс
    bool inference_enabled = true;
    {
      std::lock_guard<std::mutex> lock(inference_enabled_mutex_);
      inference_enabled = inference_enabled_;
    }
    
    if (!inference_enabled) {
      // Если инференс выключен, не публикуем ничего
      return;
    }

    // Проверяем, можно ли запустить inference
    if (!controller_->can_run_inference()) {
      // Если данных нет, просто не публикуем ничего
      static int warning_count = 0;
      if (warning_count % 50 == 0) {  // Логируем каждую секунду (50Hz)
        RCLCPP_WARN(this->get_logger(), 
                    "Inference не готов - данные датчиков недоступны. Публикация пропущена.");
      }
      warning_count++;
      return;
    }

    // Выполняем inference синхронно
    std::array<float, 12> joint_commands = controller_->run_inference_sync();

    // Создаем сообщение JointState
    auto msg = std::make_shared<sensor_msgs::msg::JointState>();
    msg->header.stamp = this->get_clock()->now();
    msg->header.frame_id = "base_link";
    msg->name = joint_names_;
    msg->position.assign(joint_commands.begin(), joint_commands.end());
    msg->velocity.clear();
    msg->effort.clear();

    // Публикуем команды суставов
    joint_commands_pub_->publish(*msg);
    RCLCPP_DEBUG(this->get_logger(), "Опубликованы команды суставов в /joint_commands");
  }

  std::shared_ptr<rds2p::InferenceController> controller_;
  std::vector<std::string> joint_names_;

  // Текущий roll и pitch джойстика (в радианах)
  double current_roll_rad_;
  double current_pitch_rad_;
  std::mutex roll_mutex_;

  // Состояние кнопки R1
  bool r1_pressed_;
  std::mutex r1_mutex_;

  // Состояние инференса (включен/выключен)
  bool inference_enabled_;
  std::mutex inference_enabled_mutex_;

  // Состояние кнопки треугольник
  bool triangle_pressed_;
  std::mutex triangle_mutex_;

  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr joint_states_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr imu_sub_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odom_sub_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr joy_imu_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Joy>::SharedPtr joy_sub_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr joint_commands_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);

  int exit_code = 0;
  std::shared_ptr<InferenceNode> node;
  
  try {
    // Настройка inference контроллера
    // Используем определенный выше массив DEFAULT_ANGLES
    std::array<float, 12> default_angles = DEFAULT_ANGLES;

    // Получаем директорию share пакета для пути к модели
    std::string pkg_share_dir = ament_index_cpp::get_package_share_directory("rds_2p_inference");
    std::string model_path = (std::filesystem::path(pkg_share_dir) / "models" / "rds2p_policy.onnx").string();

    auto controller = std::make_shared<rds2p::InferenceController>(
      model_path,
      default_angles
      // Все остальные параметры используют значения по умолчанию из конструктора
    );

    // Создаем и запускаем ROS узел
    node = std::make_shared<InferenceNode>(controller);
    
    RCLCPP_INFO(rclcpp::get_logger("main"), "Узел создан, запускаем spin...");
    rclcpp::spin(node);
    RCLCPP_INFO(rclcpp::get_logger("main"), "Spin завершен");

  } catch (const std::exception& e) {
    RCLCPP_ERROR(rclcpp::get_logger("main"), "Исключение в main: %s", e.what());
    exit_code = 1;
  }

  // Явно сбрасываем узел перед завершением для освобождения ресурсов
  node.reset();
  
  RCLCPP_INFO(rclcpp::get_logger("main"), "Завершение работы...");
  rclcpp::shutdown();
  return exit_code;
}

