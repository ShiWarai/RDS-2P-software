#ifndef FTSERVO_ROS_MOTOR_CONTROLLER_HPP
#define FTSERVO_ROS_MOTOR_CONTROLLER_HPP

#include "motor_config.hpp"
#include "SCSCL.hpp"
#include <memory>
#include <string>
#include <mutex>

namespace ftservo {

struct MotorState {
    double position;        // Текущая позиция (радианы)
    double velocity;        // Текущая скорость (рад/с)
    double load;            // Текущая нагрузка в % от максимальной (0.1% единиц)
    double effort;          // Текущее усилие (Н⋅м)
    double current;         // Текущий ток (А)
    double temperature;     // Температура (°C)
    double voltage;         // Напряжение (В)
    bool enabled;           // Включен ли мотор
    bool error;             // Есть ли ошибка
    uint8_t error_code;     // Код ошибки
    std::string error_message; // Сообщение об ошибке
};

class MotorController : public SCSCL {
public:
    /**
     * @brief Конструктор контроллера мотора
     * @param config Конфигурация мотора
     * @param is_sim Режим симуляции
     */
    MotorController(const MotorConfig& config, bool is_sim = false);
    
    /**
     * @brief Деструктор
     */
    ~MotorController();

    /**
     * @brief Инициализация контроллера
     * @param interface Интерфейс связи
     * @param baud_rate Скорость связи
     * @return true если инициализация успешна
     */
    bool initialize(const std::string& interface, int baud_rate = 115200);

    /**
     * @brief Чтение состояния мотора
     * @param state Структура для записи состояния
     * @return true если чтение успешно
     */
    bool readState(MotorState& state);

    /**
     * @brief Установка целевой позиции
     * @param position Позиция в радианах
     * @return true если команда отправлена успешно
     */
    bool setTargetPosition(double position);

    /**
     * @brief Установка целевой скорости
     * @param velocity Скорость в рад/с
     * @return true если команда отправлена успешно
     */
    bool setTargetVelocity(double velocity);

    /**
     * @brief Установка целевого ускорения
     * @param acceleration Ускорение в рад/с²
     * @return true если команда отправлена успешно
     */
    bool setTargetAcceleration(double acceleration);

    /**
     * @brief Включение мотора
     * @return true если команда отправлена успешно
     */
    bool enable();

    /**
     * @brief Выключение мотора
     * @return true если команда отправлена успешно
     */
    bool disable();

    /**
     * @brief Установка состояния включения/выключения
     * @param enabled true для включения, false для выключения
     * @return true если команда отправлена успешно
     */
    bool setEnabled(bool enabled);

    /**
     * @brief Обновление симуляции
     * @param dt Время с последнего обновления (секунды)
     */
    void updateSimulation(double dt);

    /**
     * @brief Получить конфигурацию мотора
     * @return Конфигурация мотора
     */
    const MotorConfig& getConfig() const { return config_; }

    /**
     * @brief Проверить, включен ли режим симуляции
     * @return true если включен режим симуляции
     */
    bool isSimulationMode() const { return is_sim_; }

    /**
     * @brief Получить текущее состояние мотора
     * @return Текущее состояние
     */
    const MotorState& getCurrentState() const { return current_state_; }

    /**
     * @brief Получить ID мотора
     * @return ID мотора
     */
    uint8_t getMotorId() const { return config_.id; }

    /**
     * @brief Преобразование позиции из радиан в единицы мотора
     * @param radians Позиция в радианах
     * @return Единицы мотора
     */
    int radiansToMotorUnits(double radians) const;
    
    /**
     * @brief Преобразование позиции из единиц мотора в радианы
     * @param motor_units Единицы мотора
     * @return Позиция в радианах
     */
    double motorUnitsToRadians(int motor_units) const;
    
    /**
     * @brief Преобразование скорости из рад/с в единицы мотора
     * @param rad_per_sec Скорость в рад/с
     * @return Единицы мотора
     */
    int radiansPerSecToMotorUnits(double rad_per_sec) const;
    
    /**
     * @brief Преобразование ускорения из рад/с² в единицы мотора
     * @param rad_per_sec_sq Ускорение в рад/с²
     * @return Единицы мотора
     */
    int accelerationToMotorUnits(double rad_per_sec_sq) const;
    
    /**
     * @brief Преобразование скорости из единиц мотора в рад/с
     * @param motor_units Единицы мотора
     * @return Скорость в рад/с
     */
    double motorUnitsToRadiansPerSec(int motor_units) const;
    
    /**
     * @brief Синхронная запись позиций с блокировкой линии связи
     * @param IDs Массив ID моторов
     * @param IDN Количество моторов
     * @param Position Массив позиций
     * @param Time Массив времен
     * @param Speed Массив скоростей
     * @param Acc Массив ускорений
     */
    void syncWritePos(u8 IDs[], u8 IDN, u16 Position[], u16 Time[], u16 Speed[], u8 Acc[]);
    


private:
    MotorConfig config_;
    bool is_sim_;
    MotorState current_state_;
    
    // Для симуляции
    double target_position_;
    double target_velocity_;
    double target_acceleration_;
    double current_position_;
    double current_velocity_;

    // Для плавных переходов напряжения и тока
    bool previous_enabled_;
    double transition_start_time_;
    double target_voltage_;
    double target_current_;
    
    // Статический семафор для синхронизации доступа к линии связи
    static std::mutex serial_mutex_;
};

} // namespace ftservo

#endif // FTSERVO_ROS_MOTOR_CONTROLLER_HPP 