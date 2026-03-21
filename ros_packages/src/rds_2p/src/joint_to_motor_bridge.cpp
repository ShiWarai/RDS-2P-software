#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <ftservo_ros/msg/motor_commands.hpp>
#include <ftservo_ros/msg/motor_joint_mapping.hpp>
#include <std_msgs/msg/header.hpp>
#include <yaml-cpp/yaml.h>
#include <map>
#include <string>
#include <vector>
#include <fstream>
#include <optional>
#include <cmath>
#include <algorithm>
#include <limits>
#include "leg_kinematics.hpp"

class JointToMotorBridge : public rclcpp::Node {
public:
    JointToMotorBridge() : Node("joint_to_motor_bridge") {
        // Объявляем параметры
        declare_parameter("motor_command_rate", 100.0);
        declare_parameter("offsets_config_file", "");
        declare_parameter("verbose_logging", false);
        
        // Получаем параметры
        bool use_sim_time = false;
        try {
            use_sim_time = get_parameter("use_sim_time").as_bool();
        } catch (const rclcpp::exceptions::ParameterNotDeclaredException&) {
            // Параметр не объявлен, используем значение по умолчанию
            declare_parameter("use_sim_time", true);
            use_sim_time = get_parameter("use_sim_time").as_bool();
        }
        
        double motor_command_rate = get_parameter("motor_command_rate").as_double();
        std::string offsets_config_file = get_parameter("offsets_config_file").as_string();
        verbose_logging_ = get_parameter("verbose_logging").as_bool();
        
        // Загружаем конфигурацию сдвигов
        if (!offsets_config_file.empty()) {
            if (!loadJointOffsets(offsets_config_file)) {
                RCLCPP_ERROR(get_logger(), "Failed to load required configuration file: %s", offsets_config_file.c_str());
                RCLCPP_ERROR(get_logger(), "Joint to Motor Bridge initialization failed. Shutting down...");
                rclcpp::shutdown();
                return;
            }
        }
        
        // Joint to Motor Bridge initialized
        
        // Оптимальный QoS для минимальной задержки с гарантированной доставкой
        // RELIABLE - гарантированная доставка
        // VOLATILE - не сохраняем сообщения (минимальная задержка)
        // KEEP_LAST(1) - только последнее сообщение (без очереди)
        auto low_latency_qos = rclcpp::QoS(1)
            .reliability(RMW_QOS_POLICY_RELIABILITY_RELIABLE)
            .durability(RMW_QOS_POLICY_DURABILITY_VOLATILE)
            .history(RMW_QOS_POLICY_HISTORY_KEEP_LAST);
            
        // Создаем публикатор для motor commands
        motor_commands_pub_ = create_publisher<ftservo_ros::msg::MotorCommands>(
            "motors/commands", low_latency_qos);
        
        // Создаем подписчик на joint commands с тем же QoS
        joint_states_sub_ = create_subscription<sensor_msgs::msg::JointState>(
            "joint_commands", low_latency_qos,
            std::bind(&JointToMotorBridge::jointStatesCallback, this, std::placeholders::_1));
        
        // Создаем подписчик для motor_mapping с QoS: Reliable, TransientLocal, KeepLast(1)
        auto mapping_qos = rclcpp::QoS(1)
            .reliable()
            .transient_local()
            .keep_last(1);
            
        motor_mapping_sub_ = create_subscription<ftservo_ros::msg::MotorJointMapping>(
            "motors/joint_mapping", mapping_qos,
            std::bind(&JointToMotorBridge::motorMappingCallback, this, std::placeholders::_1));
        
        // Таймер больше не нужен - публикуем команды только при получении новых данных
    }

private:
    // Нахождение имени джойнта по ID мотора
    std::optional<std::string> findJointNameByMotorId(int motor_id) const {
        auto it = motor_to_joint_mapping_.find(motor_id);
        if (it != motor_to_joint_mapping_.end()) {
            return it->second;
        }
        return std::nullopt;
    }

    // Получить угол джойнта (рад) по ID мотора, если доступны mapping и состояния
    std::optional<double> getJointAngleByMotorIdRad(int motor_id) const {
        auto joint_name_opt = findJointNameByMotorId(motor_id);
        if (!joint_name_opt.has_value()) return std::nullopt;
        
        auto it = joint_states_.find(joint_name_opt.value());
        if (it == joint_states_.end()) return std::nullopt;
        return it->second.position; // предполагается в радианах
    }
    
    // Получить угол джойнта (рад) по имени джойнта
    std::optional<double> getJointAngleByJointNameRad(const std::string& joint_name) const {
        auto it = joint_states_.find(joint_name);
        if (it == joint_states_.end()) return std::nullopt;
        return it->second.position; // предполагается в радианах
    }
    

    // Функция для расчета угла последнего двигателя голени с использованием обратной кинематики
    // Параметры: motor_2_angle_rad - угол мотора 2 (бедра) в радианах, hip_shin_angle_rad - угол между бедром и голенью в радианах
    // Возвращает: угол мотора для голени в радианах или std::nullopt если расчет невозможен
    std::optional<double> calculateShinMotorAngle(double motor_2_angle_rad, double hip_shin_angle_rad) const {
        // Используем новую функцию обратной кинематики для расчета угла мотора голени
        auto shin_motor_angle_rad = rds_2p::LegKinematics::inverseKinematicsForShinMotor(motor_2_angle_rad, hip_shin_angle_rad);
        
        if (shin_motor_angle_rad.has_value()) {
            // Возвращаем вычисленный угол мотора голени в радианах
            return shin_motor_angle_rad.value();
        } else {
            // Если вычисление невозможно, возвращаем std::nullopt
            return std::nullopt;
        }
    }
    



    void jointStatesCallback(const sensor_msgs::msg::JointState::SharedPtr msg) {
        // Обновляем данные джойнтов
        for (size_t i = 0; i < msg->name.size() && i < msg->position.size(); ++i) {
            joint_states_[msg->name[i]] = {msg->position[i], 
                                          i < msg->velocity.size() ? msg->velocity[i] : 0.0,
                                          i < msg->effort.size() ? msg->effort[i] : 0.0};
        }
        
        // Устанавливаем флаг, что данные получены
        data_received_ = true;
        
        // Публикуем команды моторов сразу после получения новых данных
        publishMotorCommands();
        
        // Простое логирование периодически
        static int command_count = 0;
        if (++command_count % 100 == 0) {  // Каждые 100 сообщений
            RCLCPP_DEBUG(get_logger(), "Received joint commands: %zu joints", msg->name.size());
        }
    }
    
    void motorMappingCallback(const ftservo_ros::msg::MotorJointMapping::SharedPtr msg) {
        // Очищаем старые привязки
        motor_to_joint_mapping_.clear();
        motor_ids_.clear();
        
        // Заполняем новые привязки
        for (const auto& binding : msg->bindings) {
            motor_to_joint_mapping_[binding.motor_id] = binding.joint_name;
            motor_ids_.push_back(binding.motor_id);
        }
        
        // Received motor-joint mapping
        
        // Устанавливаем флаг, что привязки получены
        mapping_received_ = true;
    }
    
    void publishMotorCommands() {
        if (!mapping_received_ || motor_ids_.empty() || !data_received_) {
            return;
        }
        
        auto motor_commands_msg = ftservo_ros::msg::MotorCommands();
        motor_commands_msg.header.stamp = this->now();
        motor_commands_msg.header.frame_id = "";
        
        // Заполняем команды для каждого мотора
        motor_commands_msg.commands.resize(motor_ids_.size());
        
        for (size_t i = 0; i < motor_ids_.size(); ++i) {
            int motor_id = motor_ids_[i];
            auto& command = motor_commands_msg.commands[i];
            command.motor_id = motor_id;
            
            // Получаем имя джойнта для этого мотора
            auto joint_name_opt = findJointNameByMotorId(motor_id);
            if (!joint_name_opt.has_value()) {
                // Пропускаем мотор, если нет привязки (не обнуляем)
                continue;
            }
            
            const std::string& joint_name = joint_name_opt.value();
            
            // Проверяем, есть ли данные для этого джойнта
            auto joint_it = joint_states_.find(joint_name);
            if (joint_it == joint_states_.end()) {
                // Пропускаем мотор, если нет данных (не обнуляем)
                continue;
            }
            
            const auto& joint_state = joint_it->second;
            
            // Конфигурация оси: поворот и инверсия
            const double axis_rotate = getAxisRotate(joint_name);
            const bool reversed_axis = isReversedAxis(joint_name);

            // Проверяем, является ли это суставом голени
            bool is_shin_joint = (joint_name.rfind("shin_", 0) == 0) &&
                                 (joint_name.size() >= 6 && joint_name.find("_joint") != std::string::npos);

            if (is_shin_joint) {
                // Используем обратную кинематику для расчета угла мотора голени
                // Определяем суффикс ноги между 'shin_' и '_joint' (как в motor_to_joint_bridge)
                std::string suffix;
                const size_t prefix_len = 5; // len("shin_")
                const size_t joint_pos = joint_name.rfind("_joint");
                if (joint_pos != std::string::npos && joint_pos > prefix_len) {
                    suffix = joint_name.substr(prefix_len, joint_pos - prefix_len); // например fl, fr, bl, br
                }
                
                // Находим соответствующий hip-джойнт для этой ноги
                std::string hip_joint_name = std::string("hip_") + suffix + std::string("_joint");
                auto hip_angle_opt = getJointAngleByJointNameRad(hip_joint_name);
                
                if (hip_angle_opt.has_value()) {
                    // Получаем углы мотора бедра и угла между бедром и голенью
                    double hip_motor_angle_rad = hip_angle_opt.value();
                    double hip_shin_angle_rad = joint_state.position; // угол текущего shin джойнта
                    
                    // Применяем сдвиги к углам мотора бедра и угла между бедром и голенью
                    double hip_axis_rotate = getAxisRotate(hip_joint_name);
                    double knee_axis_rotate = M_PI / 2.0; // π/2 для модели URDF
                    double adjusted_hip_motor_angle = hip_motor_angle_rad - hip_axis_rotate;
                    double adjusted_hip_shin_angle = hip_shin_angle_rad + knee_axis_rotate;
                    
                    // Вычисляем угол мотора голени с помощью обратной кинематики
                    auto calculated_shin_angle = calculateShinMotorAngle(adjusted_hip_motor_angle, adjusted_hip_shin_angle);
                    
                    if (calculated_shin_angle.has_value()) {
                        // Используем вычисленный угол напрямую без дополнительной инверсии
                        double motor_angle = calculated_shin_angle.value();
                        
                        command.target_position = motor_angle;
                        // Применяем обратные коэффициенты кинематики для скорости
                        command.target_velocity = joint_state.velocity * shin_velocity_multiplier_;
                        command.target_acceleration = 0.0;
                        // Усилие не отправляется в команды моторов (используется только для feedback)
                    } else {
                        // Если расчет невозможен, НЕ ОТПРАВЛЯЕМ данные на мотор
                        continue; // Пропускаем этот мотор
                    }
                } else {
                    // Если нет данных о бедре, НЕ ОТПРАВЛЯЕМ данные на мотор
                    continue; // Пропускаем этот мотор
                }
            } else {
                // Обычные джойнты преобразуем напрямую с учётом настроек оси
                double joint_angle = joint_state.position;
                double motor_angle = joint_angle;
                
                // Применяем обратные преобразования
                motor_angle = motor_angle - axis_rotate;
                if (reversed_axis) 
                    motor_angle = -motor_angle;

                command.target_position = motor_angle;
                command.target_velocity = joint_state.velocity;
                command.target_acceleration = 0.0;
            }
        }
        
        // Публикуем motor commands
        motor_commands_pub_->publish(motor_commands_msg);
        
        // Published motor commands
        
        // Периодический лог состояния (каждые 1000 публикаций)
        static int log_counter = 0;
        if (++log_counter >= 1000) {
            log_counter = 0;
            RCLCPP_INFO(get_logger(), 
                "Bridge status: %zu motors mapped, %zu joint states received, verbose_logging=%s",
                motor_ids_.size(), joint_states_.size(), verbose_logging_ ? "ON" : "OFF");
        }
    }
    
    // Загрузка конфигурации сдвигов из YAML файла
    bool loadJointOffsets(const std::string& config_file) {
        try {
            // Проверяем существование файла
            std::ifstream file_check(config_file);
            if (!file_check.good()) {
                RCLCPP_ERROR(get_logger(), "Configuration file does not exist or is not readable: %s", config_file.c_str());
                return false;
            }
            file_check.close();
            
            // Loading joint axis config
            
            YAML::Node config = YAML::LoadFile(config_file);
            
            if (!config["joint_offsets"]) {
                RCLCPP_ERROR(get_logger(), "Configuration file is missing 'joint_offsets' section: %s", config_file.c_str());
                return false;
            }
            
            // Загружаем коэффициенты кинематики
            if (config["kinematics_coefficients"]) {
                YAML::Node kin_coeffs = config["kinematics_coefficients"];
                if (kin_coeffs["shin_velocity_multiplier"]) {
                    shin_velocity_multiplier_ = kin_coeffs["shin_velocity_multiplier"].as<double>();
                    RCLCPP_INFO(get_logger(), "Loaded shin_velocity_multiplier: %.3f", shin_velocity_multiplier_);
                }
                if (kin_coeffs["shin_effort_multiplier"]) {
                    shin_effort_multiplier_ = kin_coeffs["shin_effort_multiplier"].as<double>();
                    RCLCPP_INFO(get_logger(), "Loaded shin_effort_multiplier: %.3f", shin_effort_multiplier_);
                }
            } else {
                RCLCPP_INFO(get_logger(), "No kinematics_coefficients found, using defaults: speed=%.3f, effort=%.3f", 
                           shin_velocity_multiplier_, shin_effort_multiplier_);
            }
            
            YAML::Node offsets = config["joint_offsets"];
            
            if (offsets.size() == 0) {
                RCLCPP_WARN(get_logger(), "Configuration file contains empty 'joint_offsets' section: %s", config_file.c_str());
                return true; // Пустая конфигурация допустима
            }
            
            int loaded_count = 0;
            for (const auto& joint : offsets) {
                try {
                    std::string joint_name = joint.first.as<std::string>();
                    
                    // Новые поля: axis_rotate (double), reversed_axis (bool)
                    // Обратная совместимость: position_offset -> axis_rotate
                    double axis_rotate = 0.0;
                    bool reversed_axis = false;

                    if (joint.second["axis_rotate"]) {
                        axis_rotate = joint.second["axis_rotate"].as<double>();
                    } else if (joint.second["position_offset"]) {
                        axis_rotate = joint.second["position_offset"].as<double>();
                        RCLCPP_WARN(get_logger(),
                                    "Joint '%s': 'position_offset' is deprecated, use 'axis_rotate' instead.",
                                    joint_name.c_str());
                    }

                    if (joint.second["reversed_axis"]) {
                        reversed_axis = joint.second["reversed_axis"].as<bool>();
                    }

                    joint_axis_rotate_[joint_name] = axis_rotate;
                    joint_reversed_axis_[joint_name] = reversed_axis;
                    loaded_count++;
                    
                    // Loaded axis config for joint
                } catch (const std::exception& e) {
                    RCLCPP_WARN(get_logger(), "Failed to parse joint configuration: %s", e.what());
                    continue;
                }
            }
            
            RCLCPP_INFO(get_logger(), "Successfully loaded %d joint axis entries from configuration file", loaded_count);
            return true;
            
        } catch (const YAML::Exception& e) {
            RCLCPP_ERROR(get_logger(), "YAML parsing error in file %s: %s", config_file.c_str(), e.what());
            return false;
        } catch (const std::exception& e) {
            RCLCPP_ERROR(get_logger(), "Failed to load joint offsets from %s: %s", 
                       config_file.c_str(), e.what());
            return false;
        }
    }
    
    // Доступ к настройкам оси
    double getAxisRotate(const std::string& joint_name) const {
        auto it = joint_axis_rotate_.find(joint_name);
        if (it != joint_axis_rotate_.end()) return it->second;
        return 0.0;
    }
    bool isReversedAxis(const std::string& joint_name) const {
        auto it = joint_reversed_axis_.find(joint_name);
        if (it != joint_reversed_axis_.end()) return it->second;
        return false;
    }
    
    // Структура для хранения состояния джойнта
    struct JointState {
        double position;
        double velocity;
        double effort;
    };
    
    // Публикаторы
    rclcpp::Publisher<ftservo_ros::msg::MotorCommands>::SharedPtr motor_commands_pub_;
    
    // Подписчики
    rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr joint_states_sub_;
    rclcpp::Subscription<ftservo_ros::msg::MotorJointMapping>::SharedPtr motor_mapping_sub_;
    
    
    // Данные
    std::map<std::string, JointState> joint_states_;
    std::map<int, std::string> motor_to_joint_mapping_;
    std::vector<int> motor_ids_;
    
    // Конфигурация осей joints
    std::map<std::string, double> joint_axis_rotate_;
    std::map<std::string, bool> joint_reversed_axis_;
    
    // Коэффициенты кинематики для суставов голени
    double shin_velocity_multiplier_ = 1.0;
    double shin_effort_multiplier_ = 1.0;
    
    // Флаги состояния
    bool data_received_ = false;
    bool mapping_received_ = false;
    bool verbose_logging_ = false;
};

int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    
    auto node = std::make_shared<JointToMotorBridge>();
    
    rclcpp::spin(node);
    
    rclcpp::shutdown();
    return 0;
}

