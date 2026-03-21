#include <rclcpp/rclcpp.hpp>
#include <rclcpp/executors/multi_threaded_executor.hpp>
#include <rclcpp/qos.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <sensor_msgs/msg/temperature.hpp>
#include <geometry_msgs/msg/quaternion.hpp>
#include <chrono>
#include <cmath>

class FakeIMUPublisher : public rclcpp::Node
{
public:
    FakeIMUPublisher() : Node("fake_imu_publisher")
    {
        // Получение параметров
        double publish_rate = this->declare_parameter("publish_rate", 100.0);
        frame_id_ = this->declare_parameter("frame_id", "imu_link");
        
        // Создание QoS профиля "Sensor data" для низкой задержки и высокой надежности
        auto sensor_qos = rclcpp::SensorDataQoS();
        sensor_qos.keep_last(5); // Размер очереди сообщений
        
        // Создание издателя IMU
        imu_pub_ = this->create_publisher<sensor_msgs::msg::Imu>("/imu", sensor_qos);

        // Создание издателя температуры
        temp_pub_ = this->create_publisher<sensor_msgs::msg::Temperature>("/imu/temperature", sensor_qos);

        // Настройка таймера на основе частоты публикации
        int timer_period_ms = static_cast<int>(1000.0 / publish_rate);
        imu_timer_ = this->create_wall_timer(
            std::chrono::milliseconds(timer_period_ms),
            std::bind(&FakeIMUPublisher::imu_timer_callback, this)
        );
        
        // Настройка таймера для температуры (каждые 5 секунд)
        temp_timer_ = this->create_wall_timer(
            std::chrono::seconds(5),
            std::bind(&FakeIMUPublisher::temp_timer_callback, this)
        );
        
        start_time_ = this->now();
        
        RCLCPP_INFO(this->get_logger(), "Timer period: %d ms (%.1f Hz)", timer_period_ms, publish_rate);
        RCLCPP_INFO(this->get_logger(), "Fake IMU publisher started");
        RCLCPP_INFO(this->get_logger(), "Publishing fake data: robot standing still on ground");
    }

private:
    rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr imu_pub_;
    rclcpp::Publisher<sensor_msgs::msg::Temperature>::SharedPtr temp_pub_;
    rclcpp::TimerBase::SharedPtr imu_timer_;
    rclcpp::TimerBase::SharedPtr temp_timer_;
    
    std::string frame_id_;
    rclcpp::Time start_time_;

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

    void imu_timer_callback()
    {
        auto current_time = this->now();
        
        // Фейковые данные: робот стоит ровно на земле
        double roll = 0.0;   // Робот не наклонен
        double pitch = 0.0;  // Робот не наклонен
        double yaw = 0.0;    // Робот не повернут
        
        auto q = euler_to_quaternion(roll, pitch, yaw);
        
        // Создание сообщения Imu
        auto imu_msg = sensor_msgs::msg::Imu();
        imu_msg.header.stamp = current_time;
        imu_msg.header.frame_id = frame_id_;
        
        // Ориентация (робот стоит ровно)
        imu_msg.orientation = q;
        imu_msg.orientation_covariance = {0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01};
        
        // Угловая скорость (робот не вращается)
        imu_msg.angular_velocity.x = 0.0;
        imu_msg.angular_velocity.y = 0.0;
        imu_msg.angular_velocity.z = 0.0;
        imu_msg.angular_velocity_covariance = {0.001, 0.0, 0.0, 0.0, 0.001, 0.0, 0.0, 0.0, 0.001};
        
        // Линейное ускорение (только сила тяжести вверх)
        imu_msg.linear_acceleration.x = 0.0;
        imu_msg.linear_acceleration.y = 0.0;
        imu_msg.linear_acceleration.z = 9.81; // 1g вверх
        imu_msg.linear_acceleration_covariance = {0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01};
        
        imu_pub_->publish(imu_msg);
    }

    void temp_timer_callback()
    {
        // Комнатная температура с небольшими колебаниями
        auto elapsed = (this->now() - start_time_).seconds();
        double temperature_celsius = 22.5 + 0.5 * sin(elapsed * 0.1) + 0.3 * cos(elapsed * 0.07);
        
        // Создание сообщения Temperature
        auto temp_msg = sensor_msgs::msg::Temperature();
        temp_msg.header.stamp = this->now();
        temp_msg.header.frame_id = frame_id_;
        temp_msg.temperature = temperature_celsius;
        temp_msg.variance = 0.1;
        
        temp_pub_->publish(temp_msg);
    }
};

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    
    try {
        auto node = std::make_shared<FakeIMUPublisher>();
        
        // Использование многопоточного исполнителя для параллельной обработки колбэков
        rclcpp::executors::MultiThreadedExecutor executor;
        executor.add_node(node);
        
        RCLCPP_INFO(node->get_logger(), "Using MultiThreadedExecutor for parallel callback processing");
        
        executor.spin();
    } catch (const std::exception& e) {
        RCLCPP_ERROR(rclcpp::get_logger("fake_imu_publisher"), "Error: %s", e.what());
    }
    
    rclcpp::shutdown();
    return 0;
}
