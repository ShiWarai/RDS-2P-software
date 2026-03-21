#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2/LinearMath/Matrix3x3.h>
#include <geometry_msgs/msg/transform_stamped.hpp>

class ImuTransformPublisher : public rclcpp::Node
{
public:
    ImuTransformPublisher() : Node("imu_transform_publisher")
    {
        // Создаем подписчика на топик IMU с QoS SENSOR_DATA
        imu_subscription_ = this->create_subscription<sensor_msgs::msg::Imu>(
            "/imu", rclcpp::SensorDataQoS(), std::bind(&ImuTransformPublisher::imu_callback, this, std::placeholders::_1));

        // Создаем трансформацию broadcaster
        tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(this);

        RCLCPP_INFO(this->get_logger(), "IMU Transform Publisher started");
        RCLCPP_INFO(this->get_logger(), "Publishing transforms: odom_link -> base_link -> imu_link");
    }

private:
    void imu_callback(const sensor_msgs::msg::Imu::SharedPtr msg)
    {
        // Трансформация 1: odom_link -> base_link (обновляется по данным IMU)
        geometry_msgs::msg::TransformStamped odom_to_base;
        odom_to_base.header.stamp = this->now();
        odom_to_base.header.frame_id = "odom_link";
        odom_to_base.child_frame_id = "base_link";

        // Позиция base_link относительно odom_link (можно настроить)
        odom_to_base.transform.translation.x = 0.0;
        odom_to_base.transform.translation.y = 0.0;
        odom_to_base.transform.translation.z = 0.0;

        // Ориентация base_link из IMU данных
        odom_to_base.transform.rotation.x = msg->orientation.x;
        odom_to_base.transform.rotation.y = msg->orientation.y;
        odom_to_base.transform.rotation.z = msg->orientation.z;
        odom_to_base.transform.rotation.w = msg->orientation.w;

        // Трансформация 2: base_link -> imu_link (статическая)
        geometry_msgs::msg::TransformStamped base_to_imu;
        base_to_imu.header.stamp = this->now();
        base_to_imu.header.frame_id = "base_link";
        base_to_imu.child_frame_id = "imu_link";

        // IMU находится в центре base_link (можно настроить смещение)
        base_to_imu.transform.translation.x = 0.0;
        base_to_imu.transform.translation.y = 0.0;
        base_to_imu.transform.translation.z = 0.0;

        // IMU имеет ту же ориентацию, что и base_link
        base_to_imu.transform.rotation.x = 0.0;
        base_to_imu.transform.rotation.y = 0.0;
        base_to_imu.transform.rotation.z = 0.0;
        base_to_imu.transform.rotation.w = 1.0;

        // Публикуем обе трансформации
        tf_broadcaster_->sendTransform(odom_to_base);
        tf_broadcaster_->sendTransform(base_to_imu);
    }

    rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr imu_subscription_;
    std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
};

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<ImuTransformPublisher>();
    rclcpp::spin(node);
    rclcpp::shutdown();
    return 0;
}
