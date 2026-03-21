#ifndef RDS_2P_FACE__IMAGE_PROCESSOR_HPP_
#define RDS_2P_FACE__IMAGE_PROCESSOR_HPP_

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <rclcpp/qos.hpp>
#include <memory>
#include <string>

class ImageProcessorNode : public rclcpp::Node {
public:
    ImageProcessorNode();

private:
    void image_callback(const sensor_msgs::msg::Image::SharedPtr msg);
    
    // Подписчики и публикаторы
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr image_sub_;
    rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr image_pub_;
    
    // Параметры топиков (обязательные)
    std::string input_topic_;
    std::string output_topic_;
    
    // Параметры выходного изображения
    int output_width_;
    int output_height_;
    static constexpr const char* OUTPUT_ENCODING = "rgb8";
};

#endif  // RDS_2P_FACE__IMAGE_PROCESSOR_HPP_

