#include <rclcpp/rclcpp.hpp>
#include <tf2_ros/static_transform_broadcaster.h>
#include <geometry_msgs/msg/transform_stamped.hpp>

class StaticTransformPublisher : public rclcpp::Node
{
public:
    StaticTransformPublisher() : Node("static_transform_publisher")
    {
        // Создаем статический трансформацию broadcaster
        static_broadcaster_ = std::make_unique<tf2_ros::StaticTransformBroadcaster>(this);

        // Публикуем статическую трансформацию map_link -> odom
        publishStaticTransforms();

        RCLCPP_INFO(this->get_logger(), "Static Transform Publisher started");
        RCLCPP_INFO(this->get_logger(), "Publishing static transform: map_link -> odom");
    }

private:
    void publishStaticTransforms()
    {
        // Трансформация map_link -> odom
        geometry_msgs::msg::TransformStamped map_to_odom;
        map_to_odom.header.stamp = this->now();
        map_to_odom.header.frame_id = "map_link";
        map_to_odom.child_frame_id = "odom";

        // map_link и odom совпадают в начальный момент
        map_to_odom.transform.translation.x = 0.0;
        map_to_odom.transform.translation.y = 0.0;
        map_to_odom.transform.translation.z = 0.0;

        // Без поворота
        map_to_odom.transform.rotation.x = 0.0;
        map_to_odom.transform.rotation.y = 0.0;
        map_to_odom.transform.rotation.z = 0.0;
        map_to_odom.transform.rotation.w = 1.0;

        // Публикуем статическую трансформацию
        static_broadcaster_->sendTransform(map_to_odom);
    }

    std::unique_ptr<tf2_ros::StaticTransformBroadcaster> static_broadcaster_;
};

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<StaticTransformPublisher>();
    rclcpp::spin(node);
    rclcpp::shutdown();
    return 0;
}
