#include <rclcpp/rclcpp.hpp>
#include <rclcpp/qos.hpp>
#include <ftservo_ros/msg/motor_commands.hpp>
#include <ftservo_ros/msg/motor_params.hpp>
#include <ftservo_ros/msg/motor_states.hpp>
#include <ftservo_ros/msg/motor_telemetries.hpp>
#include <ftservo_ros/msg/motor_joint_mapping.hpp>
#include <std_msgs/msg/bool.hpp>
#include "ftservo_ros/motor_controller.hpp"
#include "ftservo_ros/motor_config.hpp"
#include <memory>
#include <map>
#include <string>
#include <chrono>

class MotorControllerNode : public rclcpp::Node {
public:
    MotorControllerNode() : Node("motor_controller_node"), initialization_failed_(false) {
        // Объявляем параметры
        declare_parameter("config_file", "");
        declare_parameter("update_rate", 100);    // Частота критичных данных
        declare_parameter("data_rate", 10);       // Частота некритичных данных
        declare_parameter("interface", "/dev/ttyS0");
        declare_parameter("interface_baudrate", 115200);
        declare_parameter("is_sim", false);
        
        // Получаем параметры
        std::string config_file = get_parameter("config_file").as_string();
        int update_rate = get_parameter("update_rate").as_int();
        int data_rate = get_parameter("data_rate").as_int();
        std::string interface = get_parameter("interface").as_string();
        int interface_baudrate = get_parameter("interface_baudrate").as_int();
        bool is_sim = get_parameter("is_sim").as_bool();
        
        RCLCPP_INFO(get_logger(), "Loading motor configuration from: %s", config_file.c_str());
        RCLCPP_INFO(get_logger(), "Update rate (states): %d Hz", update_rate);
        RCLCPP_INFO(get_logger(), "Data rate: %d Hz", data_rate);
        RCLCPP_INFO(get_logger(), "Interface: %s", interface.c_str());
        RCLCPP_INFO(get_logger(), "Interface baudrate: %d", interface_baudrate);
        RCLCPP_INFO(get_logger(), "Simulation mode: %s", is_sim ? "enabled" : "disabled");
        
        // Загружаем конфигурацию
        if (!config_manager_.loadFromFile(config_file)) {
            RCLCPP_ERROR(get_logger(), "Failed to load motor configuration from %s", config_file.c_str());
            return;
        }
        
        // Инициализируем контроллеры
        if (!initializeControllers(interface, interface_baudrate, is_sim)) {
            RCLCPP_ERROR(get_logger(), "Failed to initialize motor controllers - node will not function properly");
            // Не завершаем работу узла, но устанавливаем флаг ошибки
            initialization_failed_ = true;
        } else {
            RCLCPP_INFO(get_logger(), "Motor controllers initialized successfully");
            initialization_failed_ = false;
        }
        
        // Создаем таймеры
        // Таймер для критичных данных (states): position, velocity, load
        states_timer_ = create_wall_timer(
            std::chrono::duration<double>(1.0 / static_cast<double>(update_rate)),
            std::bind(&MotorControllerNode::updateStatesCallback, this)
        );
        
        // Таймер для некритичных данных (telemetries): temperature, voltage, current
        telemetry_timer_ = create_wall_timer(
            std::chrono::duration<double>(1.0 / static_cast<double>(data_rate)),
            std::bind(&MotorControllerNode::updateTelemetryCallback, this)
        );
        
        // Таймер для публикации привязок (раз в секунду)
        mapping_timer_ = create_wall_timer(
            std::chrono::seconds(1),
            std::bind(&MotorControllerNode::publishMotorJointMapping, this)
        );
        
        // Создаем публикаторы
        // QoS профиль SENSOR_DATA для motor_states_pub_ (низкая задержка, высокая пропускная способность)
        auto sensor_qos = rclcpp::SensorDataQoS();
        sensor_qos.keep_last(10);
        
        motor_states_pub_ = create_publisher<ftservo_ros::msg::MotorStates>(
            "motors/states", sensor_qos);
        
        // QoS профиль для motor_telemetries_pub_ (низкая частота, полные данные)
        motor_telemetries_pub_ = create_publisher<ftservo_ros::msg::MotorTelemetries>(
            "motors/telemetries", sensor_qos);
        
        // Создаем публикатор для привязок мотор-сустав
        // QoS профиль для motor_mapping_pub_: Reliable, Transient Local, Keep Last(1)
        auto mapping_qos = rclcpp::QoS(1)
            .reliable()
            .transient_local()
            .keep_last(1);
        
        motor_mapping_pub_ = create_publisher<ftservo_ros::msg::MotorJointMapping>(
            "motors/joint_mapping", mapping_qos);
        
        // Создаем подписчики
        motor_control_cmd_sub_ = create_subscription<ftservo_ros::msg::MotorCommands>(
            "motors/commands", 1,
            std::bind(&MotorControllerNode::controlCommandCallback, this, std::placeholders::_1));
        
        // Создаем подписчик для параметров управления моторов
        motor_params_sub_ = create_subscription<ftservo_ros::msg::MotorParams>(
            "motors/params", 1,
            std::bind(&MotorControllerNode::motorParamsCallback, this, std::placeholders::_1));
        
        RCLCPP_INFO(get_logger(), "Motor controller node initialized successfully");
    }

private:
    bool initializeControllers(const std::string& interface, int baudrate, bool is_sim) {
        auto joint_names = config_manager_.getJointNames();
        
        if (joint_names.empty()) {
            RCLCPP_ERROR(get_logger(), "No motors found in configuration");
            return false;
        }
        
        RCLCPP_INFO(get_logger(), "Initializing %zu motor controllers...", joint_names.size());
        
        int success_count = 0;
        int total_count = joint_names.size();
        
        for (const auto& joint_name : joint_names) {
            try {
                const auto& config = config_manager_.getMotorConfig(joint_name);
                
                RCLCPP_INFO(get_logger(), "Initializing motor %d for joint: %s", config.id, joint_name.c_str());
                
                auto controller = std::make_unique<ftservo::MotorController>(config, is_sim);
                
                if (!controller->initialize(interface, baudrate)) {
                    RCLCPP_ERROR(get_logger(), "Failed to initialize controller for motor %d (joint: %s)", 
                                config.id, joint_name.c_str());
                    continue; // Продолжаем с другими моторами вместо полной остановки
                }
                
                // Проверяем, что мотор отвечает (только в реальном режиме)
                if (!is_sim) {
                    ftservo::MotorState test_state;
                    if (!controller->readState(test_state)) {
                        RCLCPP_WARN(get_logger(), "Motor %d (joint: %s) initialized but not responding to readState", 
                                   config.id, joint_name.c_str());
                    }
                }
                
                controllers_[joint_name] = std::move(controller);
                motor_id_to_joint_[config.id] = joint_name;  // Заполняем карту для быстрого поиска
                RCLCPP_INFO(get_logger(), "Successfully initialized controller for joint: %s (motor ID: %d)", 
                           joint_name.c_str(), config.id);
                success_count++;
                
            } catch (const std::exception& e) {
                RCLCPP_ERROR(get_logger(), "Error initializing controller for joint %s: %s", 
                           joint_name.c_str(), e.what());
                continue; // Продолжаем с другими моторами
            }
        }
        
        RCLCPP_INFO(get_logger(), "Motor initialization complete: %d/%d motors initialized successfully", 
                   success_count, total_count);
        
        // Возвращаем true только если инициализированы все моторы
        if (success_count == 0) {
            RCLCPP_ERROR(get_logger(), "No motors were initialized successfully");
            return false;
        }
        
        if (success_count < total_count) {
            RCLCPP_WARN(get_logger(), "Only %d/%d motors initialized successfully", success_count, total_count);
        }
        
        return true;
    }
    
    void updateStatesCallback() {
        // Проверяем, что инициализация прошла успешно
        if (initialization_failed_) {
            RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, 
                               "Motor controllers not properly initialized - skipping state updates");
            return;
        }
        
        // Читаем критичные данные всех моторов (позиция, скорость, нагрузка)
        auto states_msg = ftservo_ros::msg::MotorStates();
        states_msg.header.stamp = this->now();
        states_msg.header.frame_id = "base_link";
        
        for (auto& [joint_name, controller] : controllers_) {
            // Сначала обновляем симуляцию если нужно
            if (controller->isSimulationMode()) {
                controller->updateSimulation(1.0 / static_cast<double>(get_parameter("update_rate").as_int()));
            }
            
            ftservo::MotorState state;
            if (controller->readState(state)) {
                // Создаем MotorState для критичных данных движения
                auto motor_state = ftservo_ros::msg::MotorState();
                motor_state.motor_id = controller->getMotorId();
                motor_state.position = state.position;
                motor_state.velocity = state.velocity;
                motor_state.load = state.load;
                motor_state.enabled = state.enabled;
                motor_state.error = state.error;
                
                states_msg.states.push_back(motor_state);
                
                // Сохраняем полное состояние для telemetry callback
                cached_states_[joint_name] = state;
            } else {
                RCLCPP_WARN(get_logger(), "Failed to read state from motor %s", joint_name.c_str());
            }
        }
        
        // Публикуем только критичные данные
        motor_states_pub_->publish(states_msg);
    }
    
    void updateTelemetryCallback() {
        // Проверяем, что инициализация прошла успешно
        if (initialization_failed_) {
            RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, 
                               "Motor controllers not properly initialized - skipping telemetry updates");
            return;
        }
        
        // Публикуем некритичные данные (температура, напряжение, ток)
        auto telemetry_msg = ftservo_ros::msg::MotorTelemetries();
        telemetry_msg.header.stamp = this->now();
        telemetry_msg.header.frame_id = "base_link";
        
        for (auto& [joint_name, controller] : controllers_) {
            // Используем кешированные данные из updateStatesCallback
            auto it = cached_states_.find(joint_name);
            if (it != cached_states_.end()) {
                const auto& state = it->second;
                
                // Создаем MotorTelemetry только для некритичных данных
                auto motor_telemetry = ftservo_ros::msg::MotorTelemetry();
                motor_telemetry.motor_id = controller->getMotorId();
                motor_telemetry.joint_name = joint_name;
                motor_telemetry.effort = state.effort;
                motor_telemetry.temperature = state.temperature;
                motor_telemetry.voltage = state.voltage;
                motor_telemetry.current = state.current;
                motor_telemetry.error_code = state.error_code;
                
                telemetry_msg.telemetries.push_back(motor_telemetry);
            }
        }
        
        // Публикуем только некритичные данные
        motor_telemetries_pub_->publish(telemetry_msg);
    }
    
    void controlCommandCallback(const ftservo_ros::msg::MotorCommands::SharedPtr msg) {
        if (initialization_failed_) {
            RCLCPP_WARN(get_logger(), "Node not properly initialized, ignoring control command");
            return;
        }
        
        RCLCPP_DEBUG(get_logger(), "Received control command array with %zu commands", msg->commands.size());
        
        std::vector<uint8_t> motor_ids;
        std::vector<uint16_t> positions;
        std::vector<uint16_t> speeds;
        std::vector<uint8_t> accelerations;  // Изменено на uint8_t для совместимости с FTServo
        
        for (const auto& cmd : msg->commands) {
            int motor_id = cmd.motor_id;
            
            auto joint_it = motor_id_to_joint_.find(motor_id);
            if (joint_it == motor_id_to_joint_.end()) {
                RCLCPP_WARN(get_logger(), "Received control command for unknown motor ID: %d", motor_id);
                continue;
            }
            
            auto controller_it = controllers_.find(joint_it->second);
            if (controller_it == controllers_.end()) {
                RCLCPP_WARN(get_logger(), "Controller not found for motor ID: %d", motor_id);
                continue;
            }

            auto& controller = controller_it->second;
            
            // Проверяем, включен ли мотор перед отправкой команд
            if (!controller->getCurrentState().enabled) {
                continue;
            }
            
            motor_ids.push_back(controller->getMotorId());
            positions.push_back(controller->radiansToMotorUnits(cmd.target_position));
            speeds.push_back(controller->radiansPerSecToMotorUnits(cmd.target_velocity));
            accelerations.push_back(static_cast<uint8_t>(controller->accelerationToMotorUnits(cmd.target_acceleration)));
        }
        
        // Синхронная отправка команд управления (без изменения enabled состояния)
        if (!motor_ids.empty() && !controllers_.empty()) {
            bool is_sim = get_parameter("is_sim").as_bool();

            for(size_t i = 0; i < motor_ids.size(); i++) {
                RCLCPP_INFO(get_logger(), "motor_ids: %u", motor_ids[i]);
                RCLCPP_INFO(get_logger(), "positions: %u", positions[i]);
                RCLCPP_INFO(get_logger(), "speeds: %u", speeds[i]);
                RCLCPP_INFO(get_logger(), "accelerations: %u", accelerations[i]);
            }

            if (is_sim) {
                // В режиме симуляции используем исходные значения напрямую (безопасные методы не нужны)
                for (const auto& cmd : msg->commands) {
                    int motor_id = cmd.motor_id;
                    auto joint_it = motor_id_to_joint_.find(motor_id);
                    if (joint_it != motor_id_to_joint_.end()) {
                        auto controller_it = controllers_.find(joint_it->second);
                        if (controller_it != controllers_.end()) {
                            auto& controller = controller_it->second;
                            
                            // Проверяем, включен ли мотор перед отправкой команд (в симуляции тоже)
                            if (!controller->getCurrentState().enabled) {
                                continue;
                            }
                            
                            controller->setTargetPosition(cmd.target_position);
                            controller->setTargetVelocity(cmd.target_velocity);
                            controller->setTargetAcceleration(cmd.target_acceleration);
                        }
                    }
                }
            } else {
                // В реальном режиме отправляем команды
                auto& first_controller = controllers_.begin()->second;
                std::vector<uint16_t> times(motor_ids.size(), 0);  // Время = 0

                first_controller->syncWritePos(
                    motor_ids.data(), motor_ids.size(),
                    positions.data(), times.data(), speeds.data(), accelerations.data()
                );
            }
        }
    }
    
    void publishMotorJointMapping() {
        auto mapping_msg = ftservo_ros::msg::MotorJointMapping();
        mapping_msg.header.stamp = this->now();
        mapping_msg.header.frame_id = "motor_mapping";
        
        auto joint_names = config_manager_.getJointNames();
        for (const auto& joint_name : joint_names) {
            const auto& config = config_manager_.getMotorConfig(joint_name);
            
            auto binding = ftservo_ros::msg::MotorJointBinding();
            binding.motor_id = config.id;
            binding.joint_name = joint_name;
            binding.motor_name = joint_name;  // Используем joint_name как motor_name
            binding.motor_type = config.motor_type;
            binding.reversed = config.reversed;
            
            // Рассчитываем zero_offset в радианах
            double motor_units_per_radian = config.type_config.conversion.motor_units_per_radian;
            binding.zero_offset = config.zero_offset_units / motor_units_per_radian;
            
            // Рассчитываем пределы в радианах
            binding.min_position = (config.min_position_units - config.zero_offset_units) / motor_units_per_radian;
            binding.max_position = (config.max_position_units - config.zero_offset_units) / motor_units_per_radian;
            
            // Получаем максимальные значения из type_config
            binding.max_velocity = config.type_config.max_velocity;
            binding.max_acceleration = config.type_config.max_acceleration;
            
            mapping_msg.bindings.push_back(binding);
        }
        
        motor_mapping_pub_->publish(mapping_msg);
    }
    
    void motorParamsCallback(const ftservo_ros::msg::MotorParams::SharedPtr msg) {
        if (initialization_failed_) {
            RCLCPP_WARN(get_logger(), "Node not properly initialized, ignoring motor params");
            return;
        }
        
        RCLCPP_DEBUG(get_logger(), "Received motor params with %zu parameters", msg->params.size());
        
        for (const auto& param : msg->params) {
            int motor_id = param.motor_id;
            
            auto joint_it = motor_id_to_joint_.find(motor_id);
            if (joint_it == motor_id_to_joint_.end()) {
                RCLCPP_WARN(get_logger(), "Received params for unknown motor ID: %d", motor_id);
                continue;
            }
            
            auto controller_it = controllers_.find(joint_it->second);
            if (controller_it == controllers_.end()) {
                RCLCPP_WARN(get_logger(), "Controller not found for motor ID: %d", motor_id);
                continue;
            }

            auto& controller = controller_it->second;
            
            // Устанавливаем состояние enabled
            RCLCPP_INFO(get_logger(), "Setting motor %d enabled to %d", motor_id, param.enabled);
            controller->setEnabled(param.enabled);
            
            // MotorParam теперь используется только для включения/выключения и прямых записей в регистры
            
            // Если требуется прямая запись в регистры
            if (param.use_direct_write && !param.register_addresses.empty() && !param.register_values.empty()) {
                // TODO: Реализовать прямую запись в регистры через библиотеку FTServo
                RCLCPP_INFO(get_logger(), "Direct register write requested for motor %d", motor_id);
                // Здесь можно добавить вызов методов библиотеки для записи в регистры
            }
            
            RCLCPP_INFO(get_logger(), "Motor %d %s", motor_id, param.enabled ? "enabled" : "disabled");
        }
    }

    ftservo::MotorConfigManager config_manager_;
    std::map<std::string, std::unique_ptr<ftservo::MotorController>> controllers_;
    std::map<int, std::string> motor_id_to_joint_;  // Карта ID -> имя сустава для быстрого поиска
    
    // Публикаторы
    rclcpp::Publisher<ftservo_ros::msg::MotorStates>::SharedPtr motor_states_pub_;
    rclcpp::Publisher<ftservo_ros::msg::MotorTelemetries>::SharedPtr motor_telemetries_pub_;
    rclcpp::Publisher<ftservo_ros::msg::MotorJointMapping>::SharedPtr motor_mapping_pub_;
    
    // Подписчики
    rclcpp::Subscription<ftservo_ros::msg::MotorCommands>::SharedPtr motor_control_cmd_sub_;
    rclcpp::Subscription<ftservo_ros::msg::MotorParams>::SharedPtr motor_params_sub_;
    
    // Таймеры
    rclcpp::TimerBase::SharedPtr states_timer_;      // Таймер для критичных данных (update_rate)
    rclcpp::TimerBase::SharedPtr telemetry_timer_;   // Таймер для некритичных данных (data_rate)
    rclcpp::TimerBase::SharedPtr mapping_timer_;
    
    // Кеш состояний для использования в telemetry callback
    std::map<std::string, ftservo::MotorState> cached_states_;
    
    // Флаг состояния инициализации
    bool initialization_failed_;
};

int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    
    auto node = std::make_shared<MotorControllerNode>();
    
    rclcpp::spin(node);
    
    rclcpp::shutdown();
    return 0;
} 
