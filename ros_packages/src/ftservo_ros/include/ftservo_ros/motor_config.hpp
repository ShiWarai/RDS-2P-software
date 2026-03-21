#ifndef FTSERVO_ROS_MOTOR_CONFIG_HPP
#define FTSERVO_ROS_MOTOR_CONFIG_HPP

#include <string>
#include <map>
#include <vector>
#include <memory>
#include <yaml-cpp/yaml.h>

namespace ftservo {

struct MotorConversion {
    double motor_units_per_radian;
    double motor_units_per_rad_per_sec;
    double motor_units_per_rad_per_sec_sq;
};

struct MotorTypeConfig {
    // Максимальные значения для units
    int min_position_units;
    int max_position_units;
    int min_velocity_units;
    int max_velocity_units;
    int min_acceleration_units;
    int max_acceleration_units;
    
    // Коэффициенты конвертации
    MotorConversion conversion;
    
    // Коэффициент напряжения
    double voltage_scale;
    
    // Коэффициент тока
    double current_scale;
    
    // Коэффициент усилия
    double effort_scale;
    
    // Максимальные физические значения
    double max_velocity;
    double max_acceleration;
    
    // PID коэффициенты для симуляции
    double pid_kp;  // Пропорциональный коэффициент
    double pid_ki;  // Интегральный коэффициент
    double pid_kd;  // Дифференциальный коэффициент
};

struct MotorConfig {
    uint8_t id;
    std::string joint_name;
    std::string motor_type;  // Ссылка на тип двигателя
    int zero_offset_units;   // Смещение нуля в units (центр отсчета)
    int min_position_units;  // Минимальная позиция в units
    int max_position_units;  // Максимальная позиция в units
    bool reversed;           // Инвертировать направление вращения
    
    // Наследуемые параметры от типа (заполняются при загрузке)
    MotorTypeConfig type_config;
};

class MotorConfigManager {
public:
    MotorConfigManager() = default;
    ~MotorConfigManager() = default;

    /**
     * @brief Загрузить конфигурацию из YAML файла
     * @param config_path Путь к файлу конфигурации
     * @return true если загрузка успешна, false иначе
     */
    bool loadFromFile(const std::string& config_path);

    /**
     * @brief Получить конфигурацию мотора по имени joint
     * @param joint_name Имя joint
     * @return Конфигурация мотора
     */
    const MotorConfig& getMotorConfig(const std::string& joint_name) const;

    /**
     * @brief Получить конфигурацию мотора по ID
     * @param motor_id ID мотора
     * @return Конфигурация мотора
     */
    const MotorConfig& getMotorConfig(uint8_t motor_id) const;

    /**
     * @brief Получить список имен всех joints
     * @return Вектор имен joints
     */
    std::vector<std::string> getJointNames() const;

    /**
     * @brief Получить список ID всех моторов
     * @return Вектор ID моторов
     */
    std::vector<uint8_t> getMotorIds() const;

    /**
     * @brief Проверить, существует ли мотор с данным joint_name
     * @param joint_name Имя joint
     * @return true если мотор существует
     */
    bool hasMotor(const std::string& joint_name) const;

    /**
     * @brief Проверить, существует ли мотор с данным ID
     * @param motor_id ID мотора
     * @return true если мотор существует
     */
    bool hasMotor(uint8_t motor_id) const;

    /**
     * @brief Получить количество моторов
     * @return Количество моторов
     */
    size_t getMotorCount() const;

    /**
     * @brief Валидировать units для позиции
     * @param motor_id ID мотора
     * @param units Значение в units
     * @return true если значение в допустимых пределах
     */
    bool validatePositionUnits(uint8_t motor_id, int units) const;

    /**
     * @brief Валидировать units для скорости
     * @param motor_id ID мотора
     * @param units Значение в units
     * @return true если значение в допустимых пределах
     */
    bool validateVelocityUnits(uint8_t motor_id, int units) const;

    /**
     * @brief Валидировать units для ускорения
     * @param motor_id ID мотора
     * @param units Значение в units
     * @return true если значение в допустимых пределах
     */
    bool validateAccelerationUnits(uint8_t motor_id, int units) const;

private:
    std::map<std::string, MotorConfig> joint_to_config_;
    std::map<uint8_t, MotorConfig> id_to_config_;
    std::map<std::string, MotorTypeConfig> motor_types_;
    
    /**
     * @brief Парсить конфигурацию типа двигателя из YAML узла
     * @param node YAML узел
     * @param type_name Имя типа
     * @return Конфигурация типа двигателя
     */
    MotorTypeConfig parseMotorTypeConfig(const YAML::Node& node, const std::string& type_name) const;
    
    /**
     * @brief Парсить конфигурацию мотора из YAML узла
     * @param node YAML узел
     * @param motor_name Имя мотора
     * @return Конфигурация мотора
     */
    MotorConfig parseMotorConfig(const YAML::Node& node, const std::string& motor_name) const;
};

} // namespace ftservo

#endif // FTSERVO_ROS_MOTOR_CONFIG_HPP 