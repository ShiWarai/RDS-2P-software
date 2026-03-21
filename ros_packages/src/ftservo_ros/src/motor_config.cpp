#include "ftservo_ros/motor_config.hpp"
#include <iostream>
#include <fstream>
#include <stdexcept>

namespace ftservo {

bool MotorConfigManager::loadFromFile(const std::string& config_path) {
    try {
        YAML::Node config = YAML::LoadFile(config_path);
        
        // Очищаем существующие конфигурации
        joint_to_config_.clear();
        id_to_config_.clear();
        motor_types_.clear();
        
        // Загружаем типы двигателей
        if (config["motor_types"]) {
            YAML::Node types = config["motor_types"];
            for (const auto& type_pair : types) {
                std::string type_name = type_pair.first.as<std::string>();
                YAML::Node type_node = type_pair.second;
                
                MotorTypeConfig type_config = parseMotorTypeConfig(type_node, type_name);
                motor_types_[type_name] = type_config;
            }
        }
        
        // Загружаем моторы
        if (!config["motors"]) {
            std::cerr << "Error: 'motors' section not found in config file" << std::endl;
            return false;
        }
        
        YAML::Node motors = config["motors"];
        
        // Парсим конфигурации моторов
        for (const auto& motor_pair : motors) {
            std::string motor_name = motor_pair.first.as<std::string>();
            YAML::Node motor_node = motor_pair.second;
            
            MotorConfig motor_config = parseMotorConfig(motor_node, motor_name);
            
            // Проверяем уникальность ID
            if (id_to_config_.find(motor_config.id) != id_to_config_.end()) {
                std::cerr << "Error: Duplicate motor ID " << static_cast<int>(motor_config.id) 
                          << " for motor " << motor_name << std::endl;
                return false;
            }
            
            // Проверяем уникальность joint_name
            if (joint_to_config_.find(motor_config.joint_name) != joint_to_config_.end()) {
                std::cerr << "Error: Duplicate joint name " << motor_config.joint_name 
                          << " for motor " << motor_name << std::endl;
                return false;
            }
            
            // Добавляем конфигурации
            joint_to_config_[motor_config.joint_name] = motor_config;
            id_to_config_[motor_config.id] = motor_config;
        }
        
        std::cout << "Loaded " << motor_types_.size() << " motor types and " 
                  << joint_to_config_.size() << " motor configurations" << std::endl;
        return true;
        
    } catch (const YAML::Exception& e) {
        std::cerr << "YAML parsing error: " << e.what() << std::endl;
        return false;
    } catch (const std::exception& e) {
        std::cerr << "Error loading config file: " << e.what() << std::endl;
        return false;
    }
}

const MotorConfig& MotorConfigManager::getMotorConfig(const std::string& joint_name) const {
    auto it = joint_to_config_.find(joint_name);
    if (it == joint_to_config_.end()) {
        throw std::runtime_error("Motor config not found for joint: " + joint_name);
    }
    return it->second;
}

const MotorConfig& MotorConfigManager::getMotorConfig(uint8_t motor_id) const {
    auto it = id_to_config_.find(motor_id);
    if (it == id_to_config_.end()) {
        throw std::runtime_error("Motor config not found for ID: " + std::to_string(motor_id));
    }
    return it->second;
}

std::vector<std::string> MotorConfigManager::getJointNames() const {
    std::vector<std::string> joint_names;
    joint_names.reserve(joint_to_config_.size());
    
    for (const auto& pair : joint_to_config_) {
        joint_names.push_back(pair.first);
    }
    
    return joint_names;
}

std::vector<uint8_t> MotorConfigManager::getMotorIds() const {
    std::vector<uint8_t> motor_ids;
    motor_ids.reserve(id_to_config_.size());
    
    for (const auto& pair : id_to_config_) {
        motor_ids.push_back(pair.first);
    }
    
    return motor_ids;
}

bool MotorConfigManager::hasMotor(const std::string& joint_name) const {
    return joint_to_config_.find(joint_name) != joint_to_config_.end();
}

bool MotorConfigManager::hasMotor(uint8_t motor_id) const {
    return id_to_config_.find(motor_id) != id_to_config_.end();
}

size_t MotorConfigManager::getMotorCount() const {
    return joint_to_config_.size();
}

MotorTypeConfig MotorConfigManager::parseMotorTypeConfig(const YAML::Node& node, const std::string& type_name) const {
    MotorTypeConfig config;
    
    // Проверяем обязательные поля для типа мотора
    if (!node["min_position_units"]) {
        throw std::runtime_error("Missing 'min_position_units' field for motor type: " + type_name);
    }
    if (!node["max_position_units"]) {
        throw std::runtime_error("Missing 'max_position_units' field for motor type: " + type_name);
    }
    if (!node["motor_units_per_radian"]) {
        throw std::runtime_error("Missing 'motor_units_per_radian' field for motor type: " + type_name);
    }
    
    // Максимальные значения для units
    config.min_position_units = node["min_position_units"].as<int>();
    config.max_position_units = node["max_position_units"].as<int>();
    config.min_velocity_units = node["min_velocity_units"].as<int>();
    config.max_velocity_units = node["max_velocity_units"].as<int>();
    config.min_acceleration_units = node["min_acceleration_units"].as<int>();
    config.max_acceleration_units = node["max_acceleration_units"].as<int>();
    
    // Коэффициенты конвертации
    config.conversion.motor_units_per_radian = node["motor_units_per_radian"].as<double>();
    config.conversion.motor_units_per_rad_per_sec = node["motor_units_per_rad_per_sec"].as<double>();
    config.conversion.motor_units_per_rad_per_sec_sq = node["motor_units_per_rad_per_sec_sq"].as<double>();
    
    // Коэффициент напряжения
    config.voltage_scale = node["voltage_scale"].as<double>();
    
    // Коэффициент тока
    config.current_scale = node["current_scale"].as<double>();
    
    // Коэффициент усилия
    config.effort_scale = node["effort_scale"].as<double>();
    
    // Максимальные физические значения
    config.max_velocity = node["max_velocity"].as<double>();
    config.max_acceleration = node["max_acceleration"].as<double>();
    
    // PID коэффициенты для симуляции (с значениями по умолчанию)
    config.pid_kp = node["pid_kp"].as<double>();
    config.pid_ki = node["pid_ki"].as<double>();
    config.pid_kd = node["pid_kd"].as<double>();
    
    return config;
}

MotorConfig MotorConfigManager::parseMotorConfig(const YAML::Node& node, const std::string& motor_name) const {
    MotorConfig config;
    
    // Обязательные поля
    if (!node["type"]) {
        throw std::runtime_error("Missing 'type' field for motor: " + motor_name);
    }
    if (!node["id"]) {
        throw std::runtime_error("Missing 'id' field for motor: " + motor_name);
    }
    if (!node["joint_name"]) {
        throw std::runtime_error("Missing 'joint_name' field for motor: " + motor_name);
    }
    config.motor_type = node["type"].as<std::string>();
    config.id = node["id"].as<uint8_t>();
    config.joint_name = node["joint_name"].as<std::string>();
    
    // Опциональные поля с значениями по умолчанию
    config.zero_offset_units = node["zero_offset_units"] ? node["zero_offset_units"].as<int>() : 0;
    config.min_position_units = node["min_position_units"] ? node["min_position_units"].as<int>() : 0;
    config.max_position_units = node["max_position_units"] ? node["max_position_units"].as<int>() : 1023;
    config.reversed = node["reversed"] ? node["reversed"].as<bool>() : false;
    
    // Наследуем параметры от типа двигателя
    auto type_it = motor_types_.find(config.motor_type);
    if (type_it == motor_types_.end()) {
        throw std::runtime_error("Unknown motor type '" + config.motor_type + "' for motor: " + motor_name);
    }
    config.type_config = type_it->second;
    
    // Валидация units
    if (config.min_position_units >= config.max_position_units) {
        throw std::runtime_error("Invalid position units limits for motor: " + motor_name);
    }
    
    // reversed - это булево значение, валидация не нужна
    
    return config;
}

bool MotorConfigManager::validatePositionUnits(uint8_t motor_id, int units) const {
    auto it = id_to_config_.find(motor_id);
    if (it == id_to_config_.end()) {
        return false;
    }
    
    const MotorConfig& config = it->second;
    return units >= config.min_position_units && units <= config.max_position_units;
}

bool MotorConfigManager::validateVelocityUnits(uint8_t motor_id, int units) const {
    auto it = id_to_config_.find(motor_id);
    if (it == id_to_config_.end()) {
        return false;
    }
    
    const MotorConfig& config = it->second;
    return units >= config.type_config.min_velocity_units && units <= config.type_config.max_velocity_units;
}

bool MotorConfigManager::validateAccelerationUnits(uint8_t motor_id, int units) const {
    auto it = id_to_config_.find(motor_id);
    if (it == id_to_config_.end()) {
        return false;
    }
    
    const MotorConfig& config = it->second;
    return units >= config.type_config.min_acceleration_units && units <= config.type_config.max_acceleration_units;
}

} // namespace ftservo 