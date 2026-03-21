/**
 * @file battery_monitor.cpp
 * @brief Нода для мониторинга состояния батареи на основе данных о токе от моторов
 * 
 * Собирает данные о потреблении тока от всех 12 двигателей и рассчитывает
 * оставшийся заряд аккумулятора с учетом постоянных токовых утечек (компьютер и др.)
 * 
 * Особенности:
 * - Начальный заряд определяется по напряжению при старте
 * - Корректировка заряда по напряжению когда все моторы выключены >5 секунд
 * - Учёт сопротивления проводки через коэффициент тока моторов
 */

#include <rclcpp/rclcpp.hpp>
#include <rclcpp/qos.hpp>
#include <sensor_msgs/msg/battery_state.hpp>
#include <ftservo_ros/msg/motor_telemetries.hpp>
#include <ftservo_ros/msg/motor_states.hpp>
#include <chrono>
#include <cmath>
#include <map>

// ==================== ПАРАМЕТРЫ БАТАРЕИ ====================
// Емкость батареи в ампер-часах (А·ч)
constexpr double BATTERY_CAPACITY_AH = 5.0;

// Минимальное напряжение батареи (В) - полная разрядка
constexpr double BATTERY_MIN_VOLTAGE = 6.0;

// Максимальное напряжение батареи (В) - полная зарядка
constexpr double BATTERY_MAX_VOLTAGE = 8.0;

// ==================== ПОСТОЯННЫЕ ТОКОВЫЕ УТЕЧКИ ====================
// Потребление тока компьютером (бортовой компьютер Orange Pi) в амперах (А)
constexpr double COMPUTER_CURRENT_DRAW_A = 0.5;

// Потребление тока датчиками и периферией (IMU, камеры и т.д.) в амперах (А)
constexpr double SENSORS_CURRENT_DRAW_A = 0.1;

// Потребление тока системными компонентами (преобразователи напряжения и т.д.) в амперах (А)
constexpr double SYSTEM_CURRENT_DRAW_A = 0.05;

// Общее постоянное потребление тока (утечки) в амперах (А)
constexpr double TOTAL_CONSTANT_CURRENT_DRAW_A = 
    COMPUTER_CURRENT_DRAW_A + SENSORS_CURRENT_DRAW_A + SYSTEM_CURRENT_DRAW_A;

// ==================== КОЭФФИЦИЕНТЫ КОРРЕКТИРОВКИ ====================
// Коэффициент для тока моторов (учёт сопротивления проводки, потерь и т.д.)
// Реальное потребление = ток_мотора × коэффициент
constexpr double MOTOR_CURRENT_COEFFICIENT = 1.05;

// ==================== ПАРАМЕТРЫ ФИЛЬТРАЦИИ ====================
// Коэффициент сглаживания для экспоненциального фильтра тока (0.0 - 1.0)
// Меньшее значение = более сильное сглаживание
constexpr double CURRENT_SMOOTHING_FACTOR = 0.3;

// ==================== ПАРАМЕТРЫ КОРРЕКТИРОВКИ ====================
// Время (в секундах), в течение которого все моторы должны быть выключены
// перед корректировкой заряда по напряжению
constexpr double MOTORS_OFF_TIME_FOR_CORRECTION_S = 5.0;

// ==================== ПАРАМЕТРЫ РАСЧЕТА ====================
// Частота обновления расчета заряда (Гц)
constexpr double BATTERY_UPDATE_RATE_HZ = 10.0;


class BatteryMonitor : public rclcpp::Node {
public:
    BatteryMonitor() : Node("battery_monitor") {
        // Инициализируем состояние батареи
        current_charge_ah_ = 0.0;  // Будет определено по напряжению при первом измерении
        last_update_time_ = this->now();
        smoothed_total_current_ = 0.0;
        all_motors_disabled_ = false;
        motors_disabled_since_ = this->now();
        initial_charge_set_ = false;
        last_measured_voltage_ = 0.0;
        
        RCLCPP_INFO(get_logger(), "Battery Monitor Node started");
        RCLCPP_INFO(get_logger(), "Battery capacity: %.2f Ah", BATTERY_CAPACITY_AH);
        RCLCPP_INFO(get_logger(), "Motor current coefficient: %.2f (accounts for wiring resistance)", 
                    MOTOR_CURRENT_COEFFICIENT);
        RCLCPP_INFO(get_logger(), "Constant current draw: %.3f A (computer: %.3f A, sensors: %.3f A, system: %.3f A)",
                    TOTAL_CONSTANT_CURRENT_DRAW_A, COMPUTER_CURRENT_DRAW_A, 
                    SENSORS_CURRENT_DRAW_A, SYSTEM_CURRENT_DRAW_A);
        RCLCPP_INFO(get_logger(), "Voltage-based correction will trigger after %.1f seconds with all motors off",
                    MOTORS_OFF_TIME_FOR_CORRECTION_S);
        RCLCPP_INFO(get_logger(), "Use --log-level to control logging: debug, info, warn, error");
        
        // QoS профиль совместимый с SensorDataQoS (BEST_EFFORT)
        auto sensor_qos = rclcpp::QoS(rclcpp::KeepLast(10))
            .best_effort()
            .durability_volatile();
        
        // Создаем подписчика на телеметрию моторов (некритичные данные: напряжение, ток)
        motor_telemetry_sub_ = create_subscription<ftservo_ros::msg::MotorTelemetries>(
            "/motors/telemetries",
            sensor_qos,
            std::bind(&BatteryMonitor::motorTelemetryCallback, this, std::placeholders::_1)
        );
        
        // Создаем подписчика на состояния моторов (критичные данные: enabled)
        motor_states_sub_ = create_subscription<ftservo_ros::msg::MotorStates>(
            "/motors/states",
            sensor_qos,
            std::bind(&BatteryMonitor::motorStatesCallback, this, std::placeholders::_1)
        );
        
        // Создаем публикатора состояния батареи
        battery_state_pub_ = create_publisher<sensor_msgs::msg::BatteryState>(
            "/battery_state",
            10
        );
        
        // Создаем таймер для периодического обновления состояния батареи
        battery_update_timer_ = create_wall_timer(
            std::chrono::duration<double>(1.0 / BATTERY_UPDATE_RATE_HZ),
            std::bind(&BatteryMonitor::updateBatteryState, this)
        );
        
        RCLCPP_INFO(get_logger(), "Subscribed to /motors/telemetries and /motors/states (BEST_EFFORT QoS)");
        RCLCPP_INFO(get_logger(), "Publishing battery state to /battery_state at %.1f Hz", BATTERY_UPDATE_RATE_HZ);
        RCLCPP_INFO(get_logger(), "Waiting for first voltage measurement to determine initial charge...");
    }

private:
    /**
     * @brief Callback для обработки состояния моторов (enabled/disabled)
     */
    void motorStatesCallback(const ftservo_ros::msg::MotorStates::SharedPtr msg) {
        // Обновляем карту состояний моторов
        for (const auto& state : msg->states) {
            motor_enabled_states_[state.motor_id] = state.enabled;
        }
        
        // Проверяем, все ли моторы выключены
        bool all_disabled = true;
        for (const auto& [motor_id, enabled] : motor_enabled_states_) {
            if (enabled) {
                all_disabled = false;
                break;
            }
        }
        
        // Обновляем состояние
        if (all_disabled && !motor_enabled_states_.empty()) {
            if (!all_motors_disabled_) {
                // Моторы только что были выключены
                all_motors_disabled_ = true;
                motors_disabled_since_ = this->now();
                RCLCPP_DEBUG(get_logger(), "All motors disabled - starting timer for voltage-based correction");
            }
        } else {
            if (all_motors_disabled_) {
                RCLCPP_DEBUG(get_logger(), "Motors enabled - voltage-based correction cancelled");
            }
            all_motors_disabled_ = false;
        }
    }
    
    /**
     * @brief Callback для обработки телеметрии моторов
     */
    void motorTelemetryCallback(const ftservo_ros::msg::MotorTelemetries::SharedPtr msg) {
        // Суммируем ток от всех моторов
        double total_motor_current = 0.0;
        double avg_voltage = 0.0;
        int motor_count = 0;
        
        for (const auto& telemetry : msg->telemetries) {
            // Используем поле current (ток потребления в А) с коэффициентом
            total_motor_current += std::abs(telemetry.current);
            avg_voltage += telemetry.voltage;
            motor_count++;
        }
        
        if (motor_count > 0) {
            avg_voltage /= motor_count;
            last_measured_voltage_ = avg_voltage;
            
            // Если это первое измерение - определяем начальный заряд по напряжению
            if (!initial_charge_set_) {
                current_charge_ah_ = voltageToCharge(avg_voltage);
                initial_charge_set_ = true;
                RCLCPP_INFO(get_logger(), 
                           "Initial charge determined from voltage: %.2f V -> %.2f Ah (%.1f%%)",
                           avg_voltage, current_charge_ah_, 
                           (current_charge_ah_ / BATTERY_CAPACITY_AH) * 100.0);
            }
        }
        
        // Применяем коэффициент к току моторов (учёт сопротивления)
        total_motor_current *= MOTOR_CURRENT_COEFFICIENT;
        
        // Сглаживаем значение тока с помощью экспоненциального фильтра
        smoothed_total_current_ = CURRENT_SMOOTHING_FACTOR * total_motor_current + 
                                  (1.0 - CURRENT_SMOOTHING_FACTOR) * smoothed_total_current_;
        
        RCLCPP_DEBUG(get_logger(), 
                    "Received telemetry from %d motors, total current: %.3f A (smoothed: %.3f A), avg voltage: %.2f V", 
                    motor_count, total_motor_current, smoothed_total_current_, avg_voltage);
        
        // Обновляем заряд батареи
        updateCharge();
        
        // Проверяем, нужна ли корректировка по напряжению
        checkVoltageBasedCorrection();
    }
    
    /**
     * @brief Преобразование напряжения в заряд (А·ч)
     */
    double voltageToCharge(double voltage) const {
        // Линейная аппроксимация: процент заряда = (V - V_min) / (V_max - V_min)
        double percentage = (voltage - BATTERY_MIN_VOLTAGE) / (BATTERY_MAX_VOLTAGE - BATTERY_MIN_VOLTAGE);
        percentage = std::max(0.0, std::min(1.0, percentage));
        return percentage * BATTERY_CAPACITY_AH;
    }
    
    /**
     * @brief Проверка и выполнение корректировки заряда по напряжению
     */
    void checkVoltageBasedCorrection() {
        if (!initial_charge_set_ || !all_motors_disabled_) {
            return;
        }
        
        auto current_time = this->now();
        double time_disabled = (current_time - motors_disabled_since_).seconds();
        
        // Если моторы выключены достаточно долго - корректируем заряд по напряжению
        if (time_disabled >= MOTORS_OFF_TIME_FOR_CORRECTION_S) {
            double voltage_based_charge = voltageToCharge(last_measured_voltage_);
            
            // Корректируем с небольшим весом, чтобы не было резких скачков
            // Используем среднее между текущим расчётным и измеренным
            double corrected_charge = 0.7 * current_charge_ah_ + 0.3 * voltage_based_charge;
            
            double correction_ah = corrected_charge - current_charge_ah_;
            
            if (std::abs(correction_ah) > 0.05) {  // Корректируем только если разница >50 мА·ч
                RCLCPP_INFO(get_logger(), 
                           "Voltage-based correction: %.2f V -> charge %.2f Ah (was %.2f Ah, delta: %+.3f Ah)",
                           last_measured_voltage_, corrected_charge, current_charge_ah_, correction_ah);
                current_charge_ah_ = corrected_charge;
            }
            
            // Сбрасываем таймер, чтобы не корректировать слишком часто
            motors_disabled_since_ = current_time;
        }
    }
    
    /**
     * @brief Обновление заряда батареи на основе потребленного тока
     */
    void updateCharge() {
        if (!initial_charge_set_) {
            return;  // Ждём первого измерения напряжения
        }
        
        auto current_time = this->now();
        double dt = (current_time - last_update_time_).seconds();
        
        // Защита от деления на ноль и слишком больших временных интервалов
        if (dt <= 0.0 || dt > 1.0) {
            last_update_time_ = current_time;
            return;
        }
        
        // Общий ток = ток моторов (с коэффициентом) + постоянные утечки
        double total_current = smoothed_total_current_ + TOTAL_CONSTANT_CURRENT_DRAW_A;
        
        // Рассчитываем потребленный заряд: Q = I * t
        // dt в секундах, поэтому делим на 3600 для перевода в часы
        double consumed_charge_ah = total_current * (dt / 3600.0);
        
        // Уменьшаем текущий заряд
        current_charge_ah_ -= consumed_charge_ah;
        
        // Ограничиваем заряд в диапазоне [0, BATTERY_CAPACITY_AH]
        if (current_charge_ah_ < 0.0) {
            current_charge_ah_ = 0.0;
            RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000, 
                               "Battery fully discharged!");
        } else if (current_charge_ah_ > BATTERY_CAPACITY_AH) {
            current_charge_ah_ = BATTERY_CAPACITY_AH;
        }
        
        last_update_time_ = current_time;
        
        RCLCPP_DEBUG(get_logger(), 
                    "Charge update: dt=%.3fs, I_motors=%.3fA, I_const=%.3fA, I_total=%.3fA, consumed=%.6fAh, remaining=%.3fAh (%.1f%%)",
                    dt, smoothed_total_current_, TOTAL_CONSTANT_CURRENT_DRAW_A, 
                    total_current, consumed_charge_ah, current_charge_ah_, 
                    (current_charge_ah_ / BATTERY_CAPACITY_AH) * 100.0);
    }
    
    /**
     * @brief Периодическое обновление и публикация состояния батареи
     */
    void updateBatteryState() {
        if (!initial_charge_set_) {
            // Ещё не получили первое измерение напряжения
            return;
        }
        
        auto battery_msg = sensor_msgs::msg::BatteryState();
        
        // Заполняем заголовок
        battery_msg.header.stamp = this->now();
        battery_msg.header.frame_id = "base_link";
        
        // Рассчитываем процент заряда (0.0 - 1.0)
        double percentage = current_charge_ah_ / BATTERY_CAPACITY_AH;
        battery_msg.percentage = std::max(0.0, std::min(1.0, percentage));
        
        // Используем последнее измеренное напряжение
        battery_msg.voltage = last_measured_voltage_;
        
        // Текущий потребляемый ток (моторы + постоянные утечки)
        battery_msg.current = -(smoothed_total_current_ + TOTAL_CONSTANT_CURRENT_DRAW_A);
        // Отрицательное значение означает разряд (стандарт ROS)
        
        // Емкость и заряд
        battery_msg.capacity = BATTERY_CAPACITY_AH;
        battery_msg.charge = current_charge_ah_;
        battery_msg.design_capacity = BATTERY_CAPACITY_AH;
        
        // Технология и наличие батареи
        battery_msg.power_supply_technology = sensor_msgs::msg::BatteryState::POWER_SUPPLY_TECHNOLOGY_LION;
        battery_msg.present = true;
        
        // Определяем статус питания
        if (battery_msg.percentage > 0.95) {
            battery_msg.power_supply_status = sensor_msgs::msg::BatteryState::POWER_SUPPLY_STATUS_FULL;
        } else if (battery_msg.current < 0) {
            battery_msg.power_supply_status = sensor_msgs::msg::BatteryState::POWER_SUPPLY_STATUS_DISCHARGING;
        } else if (battery_msg.current > 0) {
            battery_msg.power_supply_status = sensor_msgs::msg::BatteryState::POWER_SUPPLY_STATUS_CHARGING;
        } else {
            battery_msg.power_supply_status = sensor_msgs::msg::BatteryState::POWER_SUPPLY_STATUS_NOT_CHARGING;
        }
        
        // Определяем состояние здоровья батареи
        if (battery_msg.percentage < 0.1) {
            battery_msg.power_supply_health = sensor_msgs::msg::BatteryState::POWER_SUPPLY_HEALTH_DEAD;
        } else {
            battery_msg.power_supply_health = sensor_msgs::msg::BatteryState::POWER_SUPPLY_HEALTH_GOOD;
        }
        
        // Публикуем сообщение
        battery_state_pub_->publish(battery_msg);
        
        // Логируем состояние батареи периодически
        static int log_counter = 0;
        if (++log_counter >= (BATTERY_UPDATE_RATE_HZ * 5)) {  // Каждые 5 секунд
            log_counter = 0;
            double total_current_val = smoothed_total_current_ + TOTAL_CONSTANT_CURRENT_DRAW_A;
            double remaining_time_minutes = (total_current_val > 0.01) ? 
                                           (current_charge_ah_ / total_current_val) * 60.0 : 0.0;
            
            std::string motors_status = all_motors_disabled_ ? " [MOTORS OFF]" : "";
            
            RCLCPP_INFO(get_logger(), 
                       "Battery: %.1f%% (%.3f Ah / %.2f Ah), Voltage: %.2f V, Current: %.3f A (motors: %.3f A + const: %.3f A), Est. time: %.1f min%s",
                       battery_msg.percentage * 100.0, 
                       current_charge_ah_, 
                       BATTERY_CAPACITY_AH,
                       battery_msg.voltage,
                       total_current_val,
                       smoothed_total_current_,
                       TOTAL_CONSTANT_CURRENT_DRAW_A,
                       remaining_time_minutes,
                       motors_status.c_str());
            
            // Предупреждения о низком заряде
            if (battery_msg.percentage < 0.2) {
                RCLCPP_WARN(get_logger(), "Low battery warning: %.1f%%", battery_msg.percentage * 100.0);
            }
            if (battery_msg.percentage < 0.1) {
                RCLCPP_ERROR(get_logger(), "Critical battery level: %.1f%% - Please recharge immediately!", 
                           battery_msg.percentage * 100.0);
            }
        }
    }

    // Подписчики и публикаторы
    rclcpp::Subscription<ftservo_ros::msg::MotorTelemetries>::SharedPtr motor_telemetry_sub_;
    rclcpp::Subscription<ftservo_ros::msg::MotorStates>::SharedPtr motor_states_sub_;
    rclcpp::Publisher<sensor_msgs::msg::BatteryState>::SharedPtr battery_state_pub_;
    rclcpp::TimerBase::SharedPtr battery_update_timer_;
    
    // Состояние батареи
    double current_charge_ah_;          // Текущий заряд в А·ч
    rclcpp::Time last_update_time_;     // Время последнего обновления
    double smoothed_total_current_;     // Сглаженное значение общего тока моторов (А)
    bool initial_charge_set_;           // Флаг: определён ли начальный заряд
    double last_measured_voltage_;      // Последнее измеренное напряжение
    
    // Состояние моторов для корректировки
    std::map<uint8_t, bool> motor_enabled_states_;  // Карта состояний моторов (ID -> enabled)
    bool all_motors_disabled_;                       // Флаг: все моторы выключены
    rclcpp::Time motors_disabled_since_;             // Время, с которого все моторы выключены
};

int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    
    auto node = std::make_shared<BatteryMonitor>();
    
    RCLCPP_INFO(node->get_logger(), "Battery Monitor Node is running...");
    
    rclcpp::spin(node);
    
    rclcpp::shutdown();
    return 0;
}
