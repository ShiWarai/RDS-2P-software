#include "ftservo_ros/motor_controller.hpp"
#include "SCSCL.hpp"
#include <iostream>
#include <algorithm>
#include <cmath>

namespace ftservo {

// Инициализация статического семафора
std::mutex MotorController::serial_mutex_;

// Константы для преобразования единиц (будут загружены из конфига)

MotorController::MotorController(const MotorConfig& config, bool is_sim)
    : SCSCL()  // Вызываем конструктор базового класса
    , config_(config)
    , is_sim_(is_sim)
    , target_position_(0.0)
    , target_velocity_(0.0)
    , target_acceleration_(0.0)
    , current_position_(0.0)
    , current_velocity_(0.0)
    , previous_enabled_(false)
    , transition_start_time_(0.0)
    , target_voltage_(8.4)
    , target_current_(0.1)
{
    // Инициализация состояния
    current_state_.position = 0.0;
    current_state_.velocity = 0.0;
    current_state_.load = 0.0;
    current_state_.effort = 0.0;
    current_state_.current = 0.0;
    current_state_.temperature = 25.0;
    current_state_.voltage = 12.0;
    current_state_.enabled = false;  // По умолчанию моторы отключены
    current_state_.error = false;
    current_state_.error_code = 0;
    current_state_.error_message = "";
    
    // В симуляции инициализируем позицию в безопасных пределах
    if (is_sim_) {
        // Вычисляем границы в радианах
        double min_rad = (config_.min_position_units - config_.zero_offset_units) / config_.type_config.conversion.motor_units_per_radian;
        double max_rad = (config_.max_position_units - config_.zero_offset_units) / config_.type_config.conversion.motor_units_per_radian;
        
        // Применяем reversed для корректных границ
        if (config_.reversed) {
            std::swap(min_rad, max_rad);
            min_rad = -min_rad;
            max_rad = -max_rad;
        }
        
        // Устанавливаем начальную позицию в центре допустимого диапазона
        current_position_ = (min_rad + max_rad) / 2.0;
        target_position_ = current_position_;
    }
}

MotorController::~MotorController() {
    // Базовый класс SCSCL сам закроет соединение
}

bool MotorController::initialize(const std::string& interface, int baud_rate) {
    if (is_sim_) {
        std::cout << "Motor " << static_cast<int>(config_.id) << " initialized in simulation mode" << std::endl;
        // В симуляции состояние enabled контролируется командами, не устанавливаем здесь
        return true;
    }
    
    // Используем метод базового класса SCSCL
    if (!begin(baud_rate, interface.c_str())) {
        std::cerr << "Failed to initialize SCS controller for motor " 
                  << static_cast<int>(config_.id) << std::endl;
        return false;
    }
    
    // Проверяем связь с мотором
    if (Ping(config_.id) == -1) {
        std::cerr << "Failed to ping motor " << static_cast<int>(config_.id) << std::endl;
        return false;
    }
    
    std::cout << "Motor " << static_cast<int>(config_.id) << " initialized successfully" << std::endl;
    // Не устанавливаем enabled здесь - это будет контролироваться командами
    return true;
}

bool MotorController::readState(MotorState& state) {
    if (is_sim_) {
        state = current_state_;
        return true;
    }
    
    // Блокируем доступ к последовательной линии в реальном режиме
    std::lock_guard<std::mutex> lock(serial_mutex_);
    
    // Читаем данные с мотора используя методы базового класса
    if (FeedBack(config_.id) == -1) {
        current_state_.error = true;
        current_state_.error_message = "Communication error";
        state = current_state_;
        return false;
    }
    
    // Читаем позицию
    int pos = ReadPos(-1);
    if (pos != -1) {
        current_state_.position = motorUnitsToRadians(pos);
    }
    
    // Читаем скорость
    int speed = ReadSpeed(-1);
    if (speed != -1) {
        current_state_.velocity = motorUnitsToRadiansPerSec(speed);
    }
    
    // Читаем нагрузку
    int load = ReadLoad(-1);
    if (load != -1) {
        current_state_.load = load / 10.0;  // Преобразование в % (0.1% единиц)
    } else {
        current_state_.load = 0.0;
    }
    
    // Читаем ток
    int current = ReadCurrent(-1);
    if (current != -1) {
        // Рассчитываем ток и усилие отдельно
        current_state_.current = current * config_.type_config.current_scale;  // Ток в А
        current_state_.effort = current * config_.type_config.effort_scale;    // Усилие в Н⋅м (на основе тока)
    }
    
    // Читаем температуру
    int temp = ReadTemper(-1);
    if (temp != -1) {
        current_state_.temperature = temp;
    }
    
    // Читаем напряжение
    int voltage = ReadVoltage(-1);
    if (voltage != -1) {
        current_state_.voltage = voltage * config_.type_config.voltage_scale;  // Используем voltage_scale из типа
    }
    
    // Читаем состояние торка (включен/выключен)
    int torque = readByte(config_.id, SCSCL_TORQUE_ENABLE);
    if (torque != -1) {
        current_state_.enabled = (torque == 1);
    }
    
    // Сбрасываем ошибки если связь восстановлена
    if (!current_state_.error) {
        current_state_.error_code = 0;
        current_state_.error_message = "";
    }
    
    state = current_state_;
    return true;
}

bool MotorController::setTargetPosition(double position) {
    if (is_sim_) {
        // ЗАЩИТА ПО ГРАНИЦАМ В СИМУЛЯЦИИ
        // Вычисляем границы в радианах
        double min_rad = (config_.min_position_units - config_.zero_offset_units) / config_.type_config.conversion.motor_units_per_radian;
        double max_rad = (config_.max_position_units - config_.zero_offset_units) / config_.type_config.conversion.motor_units_per_radian;
        
        // Применяем reversed для корректных границ
        if (config_.reversed) {
            std::swap(min_rad, max_rad);
            min_rad = -min_rad;
            max_rad = -max_rad;
        }
        
        // Ограничиваем целевую позицию в допустимых пределах
        target_position_ = std::clamp(position, min_rad, max_rad);
        
        return true;
    }
    
    // Блокируем доступ к последовательной линии в реальном режиме
    std::lock_guard<std::mutex> lock(serial_mutex_);
    
    // Преобразуем в единицы мотора
    int motor_units = radiansToMotorUnits(position);
    
    // Отправляем команду используя метод базового класса
    if (WritePos(config_.id, motor_units, 0, 0, 0) == -1) {
        current_state_.error = true;
        current_state_.error_message = "Failed to set position";
        return false;
    }
    
    return true;
}

bool MotorController::setTargetVelocity(double velocity) {
    // Ограничиваем скорость пределами
    velocity = std::clamp(velocity, 0.0, config_.type_config.max_velocity);
    
    if (is_sim_) {
        target_velocity_ = velocity;
        return true;
    }
    
    // Блокируем доступ к последовательной линии в реальном режиме
    std::lock_guard<std::mutex> lock(serial_mutex_);
    
    // Преобразуем в единицы мотора
    int motor_units = radiansPerSecToMotorUnits(velocity);
    
    // Отправляем команду скорости используя writeWord в регистр GOAL_SPEED 
    if (writeWord(config_.id, SCSCL_GOAL_SPEED_L, motor_units) == -1) {
        current_state_.error = true;
        current_state_.error_message = "Failed to set velocity";
        return false;
    }
    
    return true;
}

bool MotorController::setTargetAcceleration(double acceleration) {
    // Ограничиваем ускорение пределами
    acceleration = std::clamp(acceleration, 0.0, config_.type_config.max_acceleration);
    
    if (is_sim_) {
        target_acceleration_ = acceleration;
        return true;
    }
    
    // Блокируем доступ к последовательной линии в реальном режиме
    std::lock_guard<std::mutex> lock(serial_mutex_);
    
    // Преобразуем в единицы мотора
    int motor_units = accelerationToMotorUnits(acceleration);
    // Отправляем команду ускорения используя метод базового класса
    if (writeWord(config_.id, SCSCL_GOAL_ACCELERATION, motor_units) == -1) {
        current_state_.error = true;
        current_state_.error_message = "Failed to set acceleration";
        return false;
    }
    
    return true;
}


bool MotorController::enable() {
    if (is_sim_) {
        current_state_.enabled = true;
        return true;
    }
    
    // Блокируем доступ к последовательной линии в реальном режиме
    std::lock_guard<std::mutex> lock(serial_mutex_);
    
    // Включаем мотор используя специальный метод
    if (EnableTorque(config_.id, 1) == -1) {
        current_state_.error = true;
        current_state_.error_message = "Failed to enable motor";
        return false;
    }
    
    current_state_.enabled = true;
    return true;
}

bool MotorController::disable() {
    if (is_sim_) {
        current_state_.enabled = false;
        return true;
    }
    
    // Блокируем доступ к последовательной линии в реальном режиме
    std::lock_guard<std::mutex> lock(serial_mutex_);
    
    // Выключаем мотор используя специальный метод
    if (EnableTorque(config_.id, 0) == -1) {
        current_state_.error = true;
        current_state_.error_message = "Failed to disable motor";
        return false;
    }
    
    current_state_.enabled = false;
    return true;
}

bool MotorController::setEnabled(bool enabled) {
    if (is_sim_) {
        current_state_.enabled = enabled;
        return true;
    }
    
    if (enabled) {
        bool result = enable();
        return result;
    } else {
        bool result = disable();
        return result;
    }
}

void MotorController::updateSimulation(double dt) {
    if (!is_sim_) return;
    
    // Отслеживаем изменение состояния enabled для плавных переходов
    static double simulation_time = 0.0;
    simulation_time += dt;
    
    if (current_state_.enabled != previous_enabled_) {
        // Состояние изменилось, начинаем переход
        transition_start_time_ = simulation_time;
        previous_enabled_ = current_state_.enabled;
    }
    
    // Симуляция с правильной интерпретацией скорости и ускорения как ограничений
    double position_error = target_position_ - current_position_;
    
    // Если мотор отключен, устанавливаем нулевые значения движения
    if (!current_state_.enabled) {
        current_state_.velocity = 0.0;
        current_state_.load = 0.0;
        
        // Плавный переход к нормальным значениям напряжения и тока
        double transition_duration = 0.5; // 0.5 секунды на переход
        double elapsed = simulation_time - transition_start_time_;
        double progress = std::min(elapsed / transition_duration, 1.0);
        
        // Интерполяция к нормальным значениям
        double start_voltage = target_voltage_;
        double start_current = target_current_;
        double end_voltage = 8.4;  // Нормальное напряжение
        double end_current = 0.1;  // Минимальный ток в режиме ожидания
        
        current_state_.voltage = start_voltage + (end_voltage - start_voltage) * progress;
        current_state_.current = start_current + (end_current - start_current) * progress;
        current_state_.effort = current_state_.current * config_.type_config.effort_scale / config_.type_config.current_scale;
        
        // Обновляем целевые значения для следующего перехода
        target_voltage_ = end_voltage;
        target_current_ = end_current;
        
        current_state_.error = false;
        return;
    }
    
    // Скорость и ускорение - это ограничения, а не постоянные значения
    // Если скорость близка к нулю, используем максимальную (как в Feetech)
    double velocity_limit = target_velocity_;
    if (std::abs(velocity_limit) < 0.001) {
        velocity_limit = config_.type_config.max_velocity;  // Нулевая скорость = максимальная
    } else {
        velocity_limit = std::clamp(velocity_limit, 0.0, config_.type_config.max_velocity);
    }
    
    // Если есть ошибка позиции, вычисляем скорость движения
    double velocity = 0.0;
    if (std::abs(position_error) > 0.01) {
        velocity = position_error * config_.type_config.pid_kp;  // Простой P-регулятор
        velocity = std::clamp(velocity, -velocity_limit, velocity_limit);
    }
    
    // Обновляем позицию
    current_position_ += velocity * dt;
    
    // ЗАЩИТА ПО ГРАНИЦАМ В СИМУЛЯЦИИ
    // Вычисляем границы в радианах
    double min_rad = (config_.min_position_units - config_.zero_offset_units) / config_.type_config.conversion.motor_units_per_radian;
    double max_rad = (config_.max_position_units - config_.zero_offset_units) / config_.type_config.conversion.motor_units_per_radian;
    
    // Применяем reversed для корректных границ
    if (config_.reversed) {
        std::swap(min_rad, max_rad);
        min_rad = -min_rad;
        max_rad = -max_rad;
    }
    
    // Ограничиваем позицию в допустимых пределах
    current_position_ = std::clamp(current_position_, min_rad, max_rad);
    
    // Если позиция была ограничена, логируем это для отладки
    static double last_limited_position = current_position_;
    if (std::abs(current_position_ - last_limited_position) > 0.001) {
        last_limited_position = current_position_;
    }
    
    // Вычисляем нагрузку на основе усилия и скорости
    // (ускорение больше не используется в симуляции)
    
    // Обновляем состояние
    current_state_.position = current_position_;
    current_state_.velocity = velocity;
    
    // Вычисляем нагрузку на основе усилия и скорости
    double load_factor = std::abs(velocity) / config_.type_config.max_velocity;
    load_factor = std::clamp(load_factor, 0.0, 1.0);
    current_state_.load = load_factor * 100.0;  // В % от максимальной нагрузки
    
    // Симуляция динамики напряжения и тока в зависимости от нагрузки
    // Нормализуем нагрузку относительно максимальной
    double normalized_load = current_state_.load / 100.0;
    normalized_load = std::clamp(normalized_load, 0.0, 1.0);
    
    // Вычисляем целевые значения напряжения и тока
    double target_voltage = 8.4 - normalized_load * 1.0; // Напряжение падает от 8.4В до 7.4В
    double target_current = 0.1 + normalized_load * 0.9; // Ток растет от 0.1А до 1.0А
    
    // Плавный переход к новым значениям
    double transition_duration = 0.2; // 0.2 секунды на переход при изменении нагрузки
    double elapsed = simulation_time - transition_start_time_;
    double progress = std::min(elapsed / transition_duration, 1.0);
    
    // Интерполяция к целевым значениям
    current_state_.voltage = target_voltage_ + (target_voltage - target_voltage_) * progress;
    current_state_.current = target_current_ + (target_current - target_current_) * progress;
    current_state_.effort = current_state_.current * config_.type_config.effort_scale / config_.type_config.current_scale;
    
    // Обновляем целевые значения для следующего перехода
    target_voltage_ = target_voltage;
    target_current_ = target_current;
    
    // Состояние enabled не изменяется в симуляции (устанавливается через команды)
    // current_state_.enabled остается как есть
    current_state_.error = false;
}

// Преобразования единиц
int MotorController::radiansToMotorUnits(double radians) const {
    // Применяем reversed для инвертирования направления
    double adjusted_radians = config_.reversed ? -radians : radians;
    
    // Преобразуем радианы в units относительно zero_offset_units
    int units = static_cast<int>(adjusted_radians * config_.type_config.conversion.motor_units_per_radian);
    units += config_.zero_offset_units;  // Добавляем смещение нуля
    // Валидация units с учетом индивидуальных ограничений мотора
    units = std::clamp(units, config_.min_position_units, config_.max_position_units);
    return units;
}

double MotorController::motorUnitsToRadians(int motor_units) const {
    // Преобразуем units в радианы с учетом zero_offset_units
    int relative_units = motor_units - config_.zero_offset_units;
    double radians = relative_units / config_.type_config.conversion.motor_units_per_radian;
    
    // Применяем reversed для обратного преобразования
    return config_.reversed ? -radians : radians;
}

double MotorController::motorUnitsToRadiansPerSec(int motor_units) const {
    return motor_units / config_.type_config.conversion.motor_units_per_rad_per_sec;
}

int MotorController::radiansPerSecToMotorUnits(double rad_per_sec) const {
    int units = static_cast<int>(rad_per_sec * config_.type_config.conversion.motor_units_per_rad_per_sec);
    // Валидация units
    units = std::clamp(units, config_.type_config.min_velocity_units, config_.type_config.max_velocity_units);
    return units;
}

int MotorController::accelerationToMotorUnits(double rad_per_sec_sq) const {
    int units = static_cast<int>(rad_per_sec_sq * config_.type_config.conversion.motor_units_per_rad_per_sec_sq);
    // Валидация units
    units = std::clamp(units, config_.type_config.min_acceleration_units, config_.type_config.max_acceleration_units);
    return units;
}

void MotorController::syncWritePos(u8 IDs[], u8 IDN, u16 Position[], u16 Time[], u16 Speed[], u8 Acc[]) {
    if (is_sim_) {
        return;
    }
    
    // Блокируем доступ к последовательной линии в реальном режиме
    std::lock_guard<std::mutex> lock(serial_mutex_);
    
    // Вызываем метод базового класса
    SyncWritePos(IDs, IDN, Position, Time, Speed, Acc);
}

} // namespace ftservo 