#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <ftservo_ros/msg/motor_states.hpp>
#include <ftservo_ros/msg/motor_joint_mapping.hpp>
#include <std_msgs/msg/header.hpp>
#include <yaml-cpp/yaml.h>
#include <map>
#include <unordered_map>
#include <string>
#include <vector>
#include <fstream>
#include <optional>
#include <cmath>
#include <algorithm>

class MotorToJointBridge : public rclcpp::Node {
public:
    MotorToJointBridge() : Node("motor_to_joint_bridge") {
        // Объявляем параметры
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
        
        std::string offsets_config_file = get_parameter("offsets_config_file").as_string();
        verbose_logging_ = get_parameter("verbose_logging").as_bool();
        
        // Загружаем конфигурацию сдвигов
        if (!offsets_config_file.empty()) {
            if (!loadJointOffsets(offsets_config_file)) {
                RCLCPP_ERROR(get_logger(), "Failed to load required configuration file: %s", offsets_config_file.c_str());
                RCLCPP_ERROR(get_logger(), "Motor to Joint Bridge initialization failed. Shutting down...");
                rclcpp::shutdown();
                return;
            }
        }
        
        // Motor to Joint Bridge initialized
        
        // Оптимальный QoS для минимальной задержки с гарантированной доставкой
        // RELIABLE - гарантированная доставка
        // VOLATILE - не сохраняем сообщения (минимальная задержка)
        // KEEP_LAST(1) - только последнее сообщение (без очереди)
        auto low_latency_qos = rclcpp::QoS(1)
            .reliability(RMW_QOS_POLICY_RELIABILITY_RELIABLE)
            .durability(RMW_QOS_POLICY_DURABILITY_VOLATILE)
            .history(RMW_QOS_POLICY_HISTORY_KEEP_LAST);
        
        // Создаем публикатор для joint_states
        joint_state_pub_ = create_publisher<sensor_msgs::msg::JointState>(
            "joint_states", low_latency_qos);
        
        // Создаем подписчик на motor states (совместимый с motor_controller_node)
        motor_states_sub_ = create_subscription<ftservo_ros::msg::MotorStates>(
            "motors/states", rclcpp::SensorDataQoS(),
            std::bind(&MotorToJointBridge::motorStatesCallback, this, std::placeholders::_1));
        
        // Создаем подписчик для motor_mapping с QoS: Reliable, TransientLocal, KeepLast(1)
        auto mapping_qos = rclcpp::QoS(1)
            .reliable()
            .transient_local()
            .keep_last(1);
            
        motor_mapping_sub_ = create_subscription<ftservo_ros::msg::MotorJointMapping>(
            "motors/joint_mapping", mapping_qos,
            std::bind(&MotorToJointBridge::motorMappingCallback, this, std::placeholders::_1));
    }

private:
    // -------------------- КОНСТАНТЫ КИНЕМАТИКИ НОГИ (из inverse_kinematic/leg.py) --------------------
    // Длины сегментов
    static constexpr double L_leg_ = 10.255;        // длина голени
    static constexpr double L_hip_ = 10.0;          // длина бедра
    static constexpr double L_caromyslo_ = 3.191;   // длина каромысла голени
    static constexpr double L_tyaga_ = 10.0;        // длина длинной тяги голени
    static constexpr double L_side_A_ = 2.4;        // длина стороны A качалки
    static constexpr double L_side_B_ = 2.7;        // длина стороны B качалки
    static constexpr double L_side_C_angle_deg_ = 90.0; // угол в градусах
    static constexpr double L_mala_tyaga_ = 2.8;    // длина малой тяги
    static constexpr double L_richag_3_ = 2.4;      // длина рычага двигателя 3

    // Смещение оси двигателя 3
    static constexpr double offset_3_x_ = 2.0;
    static constexpr double offset_3_y_ = -2.0;

    // Угол каромысла в радианах (pi - 32.2°)
    static constexpr double L_caromyslo_angle_rad_ = M_PI - (32.2 * M_PI / 180.0);

    struct Point { double x; double y; };

    static double hypot2(double dx, double dy) { return std::sqrt(dx * dx + dy * dy); }

    // Пересечение окружностей (аналог circle_intersection в leg.py)
    static std::vector<Point> circleIntersection(double x1, double y1, double r1,
                                                 double x2, double y2, double r2) {
        const double eps = 1e-6;
        const double d = hypot2(x2 - x1, y2 - y1);
        if (d > r1 + r2 + eps || d < std::abs(r1 - r2) - eps || (std::abs(d) < eps && std::abs(r1 - r2) < eps)) {
            return {}; // Нет пересечений
        }
        const double a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d);
        const double h_sq = std::max(0.0, r1 * r1 - a * a);
        const double h = std::sqrt(h_sq);
        const double xm = x1 + a * (x2 - x1) / d;
        const double ym = y1 + a * (y2 - y1) / d;
        if (h < eps) {
            return { { xm, ym } }; // Касание, одна точка
        }
        const double rx = h * (y2 - y1) / d;
        const double ry = h * (x1 - x2) / d;
        Point p1 { xm + rx, ym + ry };
        Point p2 { xm - rx, ym - ry };
        return { p1, p2 };
    }

    // Обновление кэша конфигураций joints
    void updateJointConfigCache() {
        joint_config_cache_.clear();
        for (const auto& joint_name : joint_names_) {
            JointConfig config;
            
            // Получаем motor_id через инвертированный mapping
            auto motor_it = joint_to_motor_mapping_.find(joint_name);
            if (motor_it == joint_to_motor_mapping_.end()) {
                continue; // Пропускаем joint без mapping
            }
            config.motor_id = motor_it->second;
            
            // Получаем конфигурацию оси
            config.axis_rotate = getAxisRotate(joint_name);
            config.reversed_axis = isReversedAxis(joint_name);
            
            // Проверяем, является ли это суставом голени
            config.is_shin_joint = (joint_name.rfind("shin_", 0) == 0) &&
                                   (joint_name.size() >= 6 && joint_name.find("_joint") != std::string::npos);
            
            // Для shin joints вычисляем hip_joint_name
            if (config.is_shin_joint) {
                const size_t prefix_len = 5; // len("shin_")
                const size_t joint_pos = joint_name.rfind("_joint");
                if (joint_pos != std::string::npos && joint_pos > prefix_len) {
                    std::string suffix = joint_name.substr(prefix_len, joint_pos - prefix_len);
                    config.hip_joint_name = "hip_" + suffix + "_joint";
                }
            } else {
                config.hip_joint_name = "";
            }
            
            joint_config_cache_[joint_name] = config;
        }
    }

    // Вычисление угла между бедром и голенью (в радианах) по углам двух моторов (в радианах)
    // Порт из compute_angle_between_hip_and_shin в leg.py
    std::optional<double> computeKneeAngleFromMotorsRad(double theta2_motor_rad, double theta3_motor_rad) const {
        // В leg.py: theta2 = deg2rad(theta2_deg + 180) — добавляем 180° (π рад)
        const double theta2 = theta2_motor_rad + M_PI;
        const double theta3 = theta3_motor_rad;

        // Точки K и R
        const double K_x = L_hip_ * std::cos(theta2);
        const double K_y = L_hip_ * std::sin(theta2);
        const double R_x = offset_3_x_ + L_richag_3_ * std::cos(theta3);
        const double R_y = offset_3_y_ + L_richag_3_ * std::sin(theta3);

        // Находим P как пересечение окружностей: центр (0,0), r=L_side_B и центр (R), r=L_mala_tyaga
        auto P_candidates = circleIntersection(0.0, 0.0, L_side_B_, R_x, R_y, L_mala_tyaga_);
        if (P_candidates.empty()) return std::nullopt;
        // Выбираем P с наибольшим Y (как в leg.py)
        Point P = *std::max_element(P_candidates.begin(), P_candidates.end(), [](const Point& a, const Point& b){ return a.y < b.y; });
        const double P_x = P.x;
        const double P_y = P.y;

        // Угол альфа и точка D на качалке
        const double alpha = std::atan2(P_y, P_x) + (L_side_C_angle_deg_ * M_PI / 180.0);
        const double D_x = L_side_A_ * std::cos(alpha);
        const double D_y = L_side_A_ * std::sin(alpha);

        // Находим B_ext как пересечение окружностей: центр D, r=L_tyaga и центр K, r=L_caromyslo
        auto B_candidates = circleIntersection(D_x, D_y, L_tyaga_, K_x, K_y, L_caromyslo_);
        if (B_candidates.empty()) return std::nullopt;
        // Выбираем B_ext, как в direct_kinematics: по минимальному |180 - deg(theta_leg_candidate)|
        auto select_score = [&](const Point& p) {
            double theta_leg_candidate = std::atan2(p.y - K_y, p.x - K_x) - theta2 - L_caromyslo_angle_rad_;
            theta_leg_candidate = std::fmod(theta_leg_candidate, 2.0 * M_PI);
            if (theta_leg_candidate < 0.0) theta_leg_candidate += 2.0 * M_PI;
            double knee_angle_candidate_deg = 180.0 - (theta_leg_candidate * 180.0 / M_PI);
            return std::abs(knee_angle_candidate_deg);
        };
        Point B_ext = *std::min_element(B_candidates.begin(), B_candidates.end(), [&](const Point& a, const Point& b){
            return select_score(a) < select_score(b);
        });

        // Угол голени относительно бедра
        const double psi = std::atan2(B_ext.y - K_y, B_ext.x - K_x);
        double theta_leg = std::fmod(psi - theta2 - L_caromyslo_angle_rad_, 2.0 * M_PI);
        if (theta_leg < 0.0) theta_leg += 2.0 * M_PI;

        // Итоговый «реальный» угол между бедром и голенью по leg.py: 180° - deg(theta_leg)
        const double knee_angle_deg = 180.0 - (theta_leg * 180.0 / M_PI);
        // Приведём к радианам и в диапазон [-pi, pi] для ROS
        double knee_angle_rad = knee_angle_deg * M_PI / 180.0;
        // Нормализуем
        while (knee_angle_rad > M_PI) knee_angle_rad -= 2.0 * M_PI;
        while (knee_angle_rad < -M_PI) knee_angle_rad += 2.0 * M_PI;
        return knee_angle_rad;
    }

    // -------------------- CALLBACK ФУНКЦИИ --------------------
    
    void motorStatesCallback(const ftservo_ros::msg::MotorStates::SharedPtr msg) {
        // Обновляем данные моторов
        for (const auto& motor_state : msg->states) {
            motor_states_[motor_state.motor_id] = motor_state;
        }
        
        // Устанавливаем флаг, что данные получены
        data_received_ = true;
        
        // Публикуем joint_states немедленно после получения новых данных
        publishJointStates();
    }
    
    void motorMappingCallback(const ftservo_ros::msg::MotorJointMapping::SharedPtr msg) {
        // Очищаем старые привязки
        motor_to_joint_mapping_.clear();
        joint_to_motor_mapping_.clear();
        joint_names_.clear();
        
        // Заполняем новые привязки (основной и инвертированный mapping)
        for (const auto& binding : msg->bindings) {
            motor_to_joint_mapping_[binding.motor_id] = binding.joint_name;
            joint_to_motor_mapping_[binding.joint_name] = binding.motor_id;
            joint_names_.push_back(binding.joint_name);
        }
        
        RCLCPP_DEBUG(get_logger(), "Received motor-joint mapping with %zu bindings", msg->bindings.size());
        
        // Устанавливаем флаг, что привязки получены
        mapping_received_ = true;
        
        // Обновляем кэш конфигураций
        updateJointConfigCache();
    }
    
    // -------------------- ОСНОВНАЯ ЛОГИКА --------------------
    
    void publishJointStates() {
        
        if (!mapping_received_ || joint_names_.empty()) {
            return;
        }
        
        if (!data_received_) {
            // Публикуем нулевые значения, если данные моторов еще не получены
            auto joint_state_msg = sensor_msgs::msg::JointState();
            joint_state_msg.header.stamp = this->now();
            joint_state_msg.header.frame_id = "";
            joint_state_msg.name = joint_names_;
            joint_state_msg.position.resize(joint_names_.size(), 0.0);
            joint_state_msg.velocity.resize(joint_names_.size(), 0.0);
            joint_state_msg.effort.resize(joint_names_.size(), 0.0);
            joint_state_pub_->publish(joint_state_msg);
            return;
        }
        
        auto joint_state_msg = sensor_msgs::msg::JointState();
        joint_state_msg.header.stamp = this->now();
        joint_state_msg.header.frame_id = "";
        
        // Заполняем имена joints
        joint_state_msg.name = joint_names_;
        
        // Заполняем позиции, скорости и усилия
        joint_state_msg.position.resize(joint_names_.size());
        joint_state_msg.velocity.resize(joint_names_.size());
        joint_state_msg.effort.resize(joint_names_.size());
        
        for (size_t i = 0; i < joint_names_.size(); ++i) {
            const std::string& joint_name = joint_names_[i];
            
            // Получаем конфигурацию из кэша (O(1) поиск)
            auto config_it = joint_config_cache_.find(joint_name);
            if (config_it == joint_config_cache_.end()) {
                // Если нет конфигурации — устанавливаем нулевые значения
                joint_state_msg.position[i] = 0.0;
                joint_state_msg.velocity[i] = 0.0;
                joint_state_msg.effort[i] = 0.0;
                continue;
            }
            
            const auto& config = config_it->second;
            int motor_id = config.motor_id;
            
            // Проверяем наличие данных мотора
            auto motor_it = motor_states_.find(motor_id);
            if (motor_it == motor_states_.end()) {
                // Если данные мотора недоступны, устанавливаем нулевые значения
                joint_state_msg.position[i] = 0.0;
                joint_state_msg.velocity[i] = 0.0;
                joint_state_msg.effort[i] = 0.0;
                continue;
            }
            
            const auto& motor_state = motor_it->second;
            
            // Используем кэшированные значения конфигурации
            const double axis_rotate = config.axis_rotate;
            const bool reversed_axis = config.reversed_axis;

            if (config.is_shin_joint) {
                // Для суставов голени вычисляем реальный угол по двум моторам (бедро и «третий» мотор)
                // Используем кэшированный hip_joint_name
                if (!config.hip_joint_name.empty()) {
                    // Получаем motor_id для hip joint из кэша
                    auto hip_config_it = joint_config_cache_.find(config.hip_joint_name);
                    if (hip_config_it != joint_config_cache_.end()) {
                        int hip_motor_id = hip_config_it->second.motor_id;
                        auto hip_motor_it = motor_states_.find(hip_motor_id);
                        
                        if (hip_motor_it != motor_states_.end()) {
                            // Угол второго мотора (для голени) — это угол мотора бедра
                            double theta2_motor_rad = hip_motor_it->second.position;
                            double theta3_motor_rad = motor_state.position;

                            auto knee_opt = computeKneeAngleFromMotorsRad(theta2_motor_rad, theta3_motor_rad);
                            if (knee_opt.has_value()) {
                                // Публикуем смежный угол: π - (угол из функции)
                                double knee_pub = M_PI - knee_opt.value();
                                while (knee_pub > M_PI) knee_pub -= 2.0 * M_PI;
                                while (knee_pub < -M_PI) knee_pub += 2.0 * M_PI;
                                double angle_raw = knee_pub;
                                if (reversed_axis) angle_raw = -angle_raw;
                                joint_state_msg.position[i] = angle_raw + axis_rotate;
                            } else {
                                // Фолбэк: если геометрия не дала решения — публикуем как мотор
                                double angle_raw = motor_state.position;
                                if (reversed_axis) angle_raw = -angle_raw;
                                joint_state_msg.position[i] = angle_raw + axis_rotate;
                            }
                        } else {
                            // Нет данных мотора бедра — публикуем как мотор
                            double angle_raw = motor_state.position;
                            if (reversed_axis) angle_raw = -angle_raw;
                            joint_state_msg.position[i] = angle_raw + axis_rotate;
                        }
                    } else {
                        // Нет конфигурации бедра — публикуем как мотор
                        double angle_raw = motor_state.position;
                        if (reversed_axis) angle_raw = -angle_raw;
                        joint_state_msg.position[i] = angle_raw + axis_rotate;
                    }
                } else {
                    // Нет hip_joint_name — публикуем как мотор
                    double angle_raw = motor_state.position;
                    if (reversed_axis) angle_raw = -angle_raw;
                    joint_state_msg.position[i] = angle_raw + axis_rotate;
                }

                // Скорость и усилие — применяем коэффициенты кинематики
                joint_state_msg.velocity[i] = motor_state.velocity / shin_velocity_multiplier_;
                joint_state_msg.effort[i] = motor_state.load * shin_effort_multiplier_;

                // Периодический лог входов/выхода функции для передней правой ноги (shin_fr_joint)
                const bool is_front_right_shin = (joint_name == std::string("shin_fr_joint"));
                const rclcpp::Time now_time = this->now();
            } else {
                // Обычные джойнты публикуем напрямую с учётом настроек оси
                double angle_raw = motor_state.position;

                if (reversed_axis) 
                    angle_raw = -angle_raw;

                joint_state_msg.position[i] = angle_raw + axis_rotate;
                joint_state_msg.velocity[i] = motor_state.velocity;
                joint_state_msg.effort[i] = motor_state.load;
            }
        }
        
        // Публикуем joint_states
        joint_state_pub_->publish(joint_state_msg);
        
        // Published joint states
        
        // Периодический лог состояния (каждые 1000 публикаций)
        static int log_counter = 0;
        if (++log_counter >= 1000) {
            log_counter = 0;
            RCLCPP_INFO(get_logger(), 
                "Bridge status: %zu joints mapped, %zu motor states received, verbose_logging=%s",
                joint_names_.size(), motor_states_.size(), verbose_logging_ ? "ON" : "OFF");
        }
    }
    
    // -------------------- УТИЛИТЫ --------------------
    
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
            
            RCLCPP_INFO(get_logger(), "Loading joint axis config from: %s", config_file.c_str());
            
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
                    
                    RCLCPP_INFO(get_logger(), "Loaded axis config for %s: axis_rotate=%.4f, reversed_axis=%s",
                                joint_name.c_str(), axis_rotate, reversed_axis ? "true" : "false");
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
    
    // -------------------- ЧЛЕНЫ КЛАССА --------------------
    
    // Публикаторы
    rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr joint_state_pub_;
    
    // Подписчики
    rclcpp::Subscription<ftservo_ros::msg::MotorStates>::SharedPtr motor_states_sub_;
    rclcpp::Subscription<ftservo_ros::msg::MotorJointMapping>::SharedPtr motor_mapping_sub_;
    
    // Структура конфигурации joint
    struct JointConfig {
        int motor_id;
        double axis_rotate;
        bool reversed_axis;
        bool is_shin_joint;
        std::string hip_joint_name;  // Для shin joints (пустая для обычных)
    };
    
    // Данные
    std::unordered_map<int, ftservo_ros::msg::MotorState> motor_states_;
    std::unordered_map<int, std::string> motor_to_joint_mapping_;
    std::unordered_map<std::string, int> joint_to_motor_mapping_;  // Инвертированный mapping для быстрого поиска
    std::vector<std::string> joint_names_;
    
    // Конфигурация осей joints
    std::unordered_map<std::string, double> joint_axis_rotate_;
    std::unordered_map<std::string, bool> joint_reversed_axis_;
    
    // Кэш конфигураций joints
    std::unordered_map<std::string, JointConfig> joint_config_cache_;
    
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
    
    auto node = std::make_shared<MotorToJointBridge>();
    
    rclcpp::spin(node);
    
    rclcpp::shutdown();
    return 0;
}
