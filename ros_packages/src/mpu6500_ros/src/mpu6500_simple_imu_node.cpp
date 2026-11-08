#include <rclcpp/rclcpp.hpp>
#include <rclcpp/executors/multi_threaded_executor.hpp>
#include <rclcpp/qos.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <sensor_msgs/msg/temperature.hpp>
#include <geometry_msgs/msg/quaternion.hpp>
#include <geometry_msgs/msg/vector3.hpp>
#include <std_msgs/msg/header.hpp>
#include <chrono>
#include <cmath>
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstring>
#include <thread>
#include <memory>

class MPU6500SimpleIMUNode : public rclcpp::Node
{
public:
    MPU6500SimpleIMUNode() : Node("mpu6500_simple_imu_node")
    {
        // Получение параметров
        int address = this->declare_parameter("address", 0);
        double publish_rate = this->declare_parameter("publish_rate", 100.0);
        frame_id_ = this->declare_parameter("frame_id", "imu_link");
        bool enable_calibration = this->declare_parameter("enable_calibration", true);
        bool enable_temperature = this->declare_parameter("enable_temperature", false);
        
        // Инициализация I2C (выбор шины: параметр i2c_device или по умолчанию по адресу)
        std::string i2c_bus = this->declare_parameter("i2c_device", (address == 0) ? "/dev/i2c-1" : "/dev/i2c-0");
        i2c_fd_ = open(i2c_bus.c_str(), O_RDWR);
        if (i2c_fd_ < 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to open I2C bus %s", i2c_bus.c_str());
            return;
        }
        
        RCLCPP_INFO(this->get_logger(), "Using I2C bus: %s", i2c_bus.c_str());

        // Установка адреса MPU6500
        if (ioctl(i2c_fd_, I2C_SLAVE, MPU6500_ADDRESS) < 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to set I2C address");
            return;
        }

        // Инициализация MPU6500
        init_MPU6500();

        // Калибровка (если включена)
        if (enable_calibration) {
            calibrate();
        } else {
            RCLCPP_INFO(this->get_logger(), "Калибровка отключена");
        }

        // Инициализация углов
        auto accel_data = get_raw_accel();
        double accel_x = (accel_data.x - accel_offsets_.x) / 16384.0;
        double accel_y = (accel_data.y - accel_offsets_.y) / 16384.0;
        double accel_z = (accel_data.z - accel_offsets_.z) / 16384.0;

        roll_ = atan2(accel_y, accel_z) * 180.0 / M_PI;
        pitch_ = atan2(-accel_x, sqrt(accel_y * accel_y + accel_z * accel_z)) * 180.0 / M_PI;
        yaw_ = 0.0;

        last_time_ = this->now();
        alpha_ = 0.98;  // Коэффициент комплементарного фильтра

        // Создание QoS профиля "Sensor data" для низкой задержки и высокой надежности
        auto sensor_qos = rclcpp::SensorDataQoS();
        sensor_qos.keep_last(5); // Размер очереди сообщений
        
        // Создание издателя с QoS профилем "Sensor data"
        pub_ = this->create_publisher<sensor_msgs::msg::Imu>("/imu", sensor_qos);

        // Создание издателя температуры (только если включен)
        if (enable_temperature) {
            temp_pub_ = this->create_publisher<sensor_msgs::msg::Temperature>("/imu/temperature", sensor_qos);
            RCLCPP_INFO(this->get_logger(), "Temperature publishing enabled with Sensor Data QoS");
        } else {
            temp_pub_ = nullptr;
            RCLCPP_INFO(this->get_logger(), "Temperature publishing disabled");
        }

        // Настройка таймера на основе частоты публикации
        int timer_period_ms = static_cast<int>(1000.0 / publish_rate);
        timer_ = this->create_wall_timer(
            std::chrono::milliseconds(timer_period_ms),
            std::bind(&MPU6500SimpleIMUNode::timer_callback, this)
        );
        
        // Настройка таймера для температуры (каждые 5 секунд, только если включен)
        if (enable_temperature) {
            temp_timer_ = this->create_wall_timer(
                std::chrono::seconds(5),
                std::bind(&MPU6500SimpleIMUNode::temp_timer_callback, this)
            );
            RCLCPP_INFO(this->get_logger(), "Temperature timer period: 5 seconds");
        } else {
            temp_timer_ = nullptr;
        }
        
        RCLCPP_INFO(this->get_logger(), "Timer period: %d ms (%.1f Hz)", timer_period_ms, publish_rate);

        RCLCPP_INFO(this->get_logger(), "MPU6500 Simple IMU node started");
    }

    ~MPU6500SimpleIMUNode()
    {
        if (i2c_fd_ >= 0) {
            close(i2c_fd_);
        }
    }

private:
    static constexpr uint8_t MPU6500_ADDRESS = 0x68;
    static constexpr uint8_t PWR_MGMT_1 = 0x6B;
    static constexpr uint8_t GYRO_CONFIG = 0x1B;
    static constexpr uint8_t ACCEL_CONFIG = 0x1C;
    static constexpr uint8_t ACCEL_XOUT_H = 0x3B;
    static constexpr uint8_t GYRO_XOUT_H = 0x43;
    static constexpr uint8_t TEMP_OUT_H = 0x41;
    static constexpr uint8_t TEMP_OUT_L = 0x42;

    struct AccelData {
        int16_t x, y, z;
    };

    struct GyroData {
        int16_t x, y, z;
    };

    struct TempData {
        int16_t temperature;
    };

    struct Offsets {
        double x, y, z;
    };

    int i2c_fd_;
    rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr pub_;
    rclcpp::Publisher<sensor_msgs::msg::Temperature>::SharedPtr temp_pub_;
    rclcpp::TimerBase::SharedPtr timer_;
    rclcpp::TimerBase::SharedPtr temp_timer_;
    
    std::string frame_id_;
    
    Offsets accel_offsets_;
    Offsets gyro_offsets_;
    
    double roll_, pitch_, yaw_;
    rclcpp::Time last_time_;
    double alpha_;

    void init_MPU6500()
    {
        // Пробуждение MPU6500
        write_byte_data(PWR_MGMT_1, 0);
        // Настройка гироскопа ±250 dps
        write_byte_data(GYRO_CONFIG, 0x00);
        // Настройка акселерометра ±2g
        write_byte_data(ACCEL_CONFIG, 0x00);
    }

    void write_byte_data(uint8_t reg, uint8_t data)
    {
        uint8_t buffer[2] = {reg, data};
        if (write(i2c_fd_, buffer, 2) != 2) {
            RCLCPP_ERROR(this->get_logger(), "Failed to write I2C data");
        }
    }

    std::vector<uint8_t> read_i2c_block_data(uint8_t reg, uint8_t length)
    {
        std::vector<uint8_t> data(length);
        
        if (write(i2c_fd_, &reg, 1) != 1) {
            RCLCPP_ERROR(this->get_logger(), "Failed to write register address");
            return data;
        }
        
        if (read(i2c_fd_, data.data(), length) != length) {
            RCLCPP_ERROR(this->get_logger(), "Failed to read I2C data");
        }
        
        return data;
    }

    AccelData get_raw_accel()
    {
        auto data = read_i2c_block_data(ACCEL_XOUT_H, 6);
        AccelData accel;
        
        accel.x = (data[0] << 8) | data[1];
        accel.y = (data[2] << 8) | data[3];
        accel.z = (data[4] << 8) | data[5];
        
        // Преобразование в знаковое число (int16_t уже знаковый тип)
        // Предупреждения компилятора о том, что сравнение всегда ложно, можно игнорировать
        // так как мы работаем с int16_t, который имеет диапазон [-32768, 32767]
        
        return accel;
    }

    GyroData get_raw_gyro()
    {
        auto data = read_i2c_block_data(GYRO_XOUT_H, 6);
        GyroData gyro;
        
        gyro.x = (data[0] << 8) | data[1];
        gyro.y = (data[2] << 8) | data[3];
        gyro.z = (data[4] << 8) | data[5];
        
        // Преобразование в знаковое число (int16_t уже знаковый тип)
        // Предупреждения компилятора о том, что сравнение всегда ложно, можно игнорировать
        // так как мы работаем с int16_t, который имеет диапазон [-32768, 32767]
        
        return gyro;
    }

    TempData get_raw_temperature()
    {
        auto data = read_i2c_block_data(TEMP_OUT_H, 2);
        TempData temp;
        
        temp.temperature = (data[0] << 8) | data[1];
        
        return temp;
    }

    double convert_temperature_to_celsius(int16_t raw_temp)
    {
        // Формула для MPU6500: Temperature (°C) = (TEMP_OUT / 340) + 36.53
        return (static_cast<double>(raw_temp) / 340.0) + 36.53;
    }

    void calibrate(int num_samples = 100)
    {
        RCLCPP_INFO(this->get_logger(), "Калибровка... Убедитесь, что устройство неподвижно и горизонтально.");
        
        Offsets accel_sum = {0, 0, 0};
        Offsets gyro_sum = {0, 0, 0};
        
        for (int i = 0; i < num_samples; ++i) {
            auto accel = get_raw_accel();
            auto gyro = get_raw_gyro();
            
            accel_sum.x += accel.x;
            accel_sum.y += accel.y;
            accel_sum.z += accel.z;
            gyro_sum.x += gyro.x;
            gyro_sum.y += gyro.y;
            gyro_sum.z += gyro.z;
            
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        
        accel_offsets_.x = accel_sum.x / num_samples;
        accel_offsets_.y = accel_sum.y / num_samples;
        accel_offsets_.z = (accel_sum.z / num_samples) - 16384;  // 1g = 16384 LSB/g
        
        gyro_offsets_.x = gyro_sum.x / num_samples;
        gyro_offsets_.y = gyro_sum.y / num_samples;
        gyro_offsets_.z = gyro_sum.z / num_samples;
        
        RCLCPP_INFO(this->get_logger(), "Калибровка завершена.");
    }

    geometry_msgs::msg::Quaternion euler_to_quaternion(double roll, double pitch, double yaw)
    {
        roll = roll * M_PI / 180.0 / 2.0;
        pitch = pitch * M_PI / 180.0 / 2.0;
        yaw = yaw * M_PI / 180.0 / 2.0;
        
        geometry_msgs::msg::Quaternion q;
        
        q.w = cos(roll) * cos(pitch) * cos(yaw) + sin(roll) * sin(pitch) * sin(yaw);
        q.x = sin(roll) * cos(pitch) * cos(yaw) - cos(roll) * sin(pitch) * sin(yaw);
        q.y = cos(roll) * sin(pitch) * cos(yaw) + sin(roll) * cos(pitch) * sin(yaw);
        q.z = cos(roll) * cos(pitch) * sin(yaw) - sin(roll) * sin(pitch) * cos(yaw);
        
        return q;
    }

    void timer_callback()
    {
        auto current_time = this->now();
        double dt = (current_time - last_time_).seconds();
        last_time_ = current_time;
        
        auto accel_data = get_raw_accel();
        auto gyro_data = get_raw_gyro();
        
        double accel_x = (accel_data.x - accel_offsets_.x) / 16384.0;
        double accel_y = (accel_data.y - accel_offsets_.y) / 16384.0;
        double accel_z = (accel_data.z - accel_offsets_.z) / 16384.0;
        
        double gyro_x = (gyro_data.x - gyro_offsets_.x) / 131.0;
        double gyro_y = (gyro_data.y - gyro_offsets_.y) / 131.0;
        double gyro_z = (gyro_data.z - gyro_offsets_.z) / 131.0;
        
        double accel_roll = atan2(accel_y, accel_z) * 180.0 / M_PI;
        double accel_pitch = atan2(-accel_x, sqrt(accel_y * accel_y + accel_z * accel_z)) * 180.0 / M_PI;
        
        double gyro_roll = roll_ + gyro_x * dt;
        double gyro_pitch = pitch_ + gyro_y * dt;
        double gyro_yaw = yaw_ + gyro_z * dt;
        
        roll_ = alpha_ * gyro_roll + (1.0 - alpha_) * accel_roll;
        pitch_ = alpha_ * gyro_pitch + (1.0 - alpha_) * accel_pitch;
        yaw_ = gyro_yaw;  // Без коррекции для yaw, будет дрейф
        
        auto q = euler_to_quaternion(roll_, pitch_, yaw_);
        
        // Создание сообщения Imu
        auto imu_msg = sensor_msgs::msg::Imu();
        imu_msg.header.stamp = current_time;
        imu_msg.header.frame_id = frame_id_;
        
        imu_msg.orientation = q;
        imu_msg.orientation_covariance = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
        
        imu_msg.angular_velocity.x = gyro_x * M_PI / 180.0;
        imu_msg.angular_velocity.y = gyro_y * M_PI / 180.0;
        imu_msg.angular_velocity.z = gyro_z * M_PI / 180.0;
        imu_msg.angular_velocity_covariance = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
        
        imu_msg.linear_acceleration.x = accel_x * 9.80665;
        imu_msg.linear_acceleration.y = accel_y * 9.80665;
        imu_msg.linear_acceleration.z = accel_z * 9.80665;
        imu_msg.linear_acceleration_covariance = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
        
        pub_->publish(imu_msg);
    }

    void temp_timer_callback()
    {
        try {
            auto temp_data = get_raw_temperature();
            double temperature_celsius = convert_temperature_to_celsius(temp_data.temperature);
            
            // Создание сообщения Temperature
            auto temp_msg = sensor_msgs::msg::Temperature();
            temp_msg.header.stamp = this->now();
            temp_msg.header.frame_id = frame_id_;
            temp_msg.temperature = temperature_celsius;
            temp_msg.variance = 0.1; // Примерная дисперсия для MPU6500
            
            temp_pub_->publish(temp_msg);
            
            RCLCPP_DEBUG(this->get_logger(), "Temperature: %.2f°C", temperature_celsius);
        } catch (const std::exception& e) {
            RCLCPP_ERROR(this->get_logger(), "Error reading temperature: %s", e.what());
        }
    }
};

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    
    try {
        auto node = std::make_shared<MPU6500SimpleIMUNode>();
        
        // Использование многопоточного исполнителя для параллельной обработки колбэков
        rclcpp::executors::MultiThreadedExecutor executor;
        executor.add_node(node);
        
        RCLCPP_INFO(node->get_logger(), "Using MultiThreadedExecutor for parallel callback processing");
        
        executor.spin();
    } catch (const std::exception& e) {
        RCLCPP_ERROR(rclcpp::get_logger("mpu6500_simple_imu_node"), "Error: %s", e.what());
    }
    
    rclcpp::shutdown();
    return 0;
}
