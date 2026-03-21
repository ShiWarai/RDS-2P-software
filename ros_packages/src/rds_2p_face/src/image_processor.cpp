#include "rds_2p_face/image_processor.hpp"
#include <cv_bridge/cv_bridge.h>
#include <opencv2/opencv.hpp>
#include <opencv2/imgproc/imgproc.hpp>

ImageProcessorNode::ImageProcessorNode() : Node("image_processor") {
    // Объявление обязательных параметров для топиков (без дефолтов)
    this->declare_parameter<std::string>("input_topic");
    this->declare_parameter<std::string>("output_topic");
    
    // Объявление параметров для разрешения выходного изображения
    this->declare_parameter<int>("output_width", 280);
    this->declare_parameter<int>("output_height", 240);
    
    // Получение обязательных параметров топиков
    input_topic_ = this->get_parameter("input_topic").as_string();
    output_topic_ = this->get_parameter("output_topic").as_string();
    
    // Проверка обязательных параметров
    if (input_topic_.empty() || output_topic_.empty()) {
        RCLCPP_FATAL(this->get_logger(), "Обязательные параметры input_topic и output_topic должны быть заданы!");
        rclcpp::shutdown();
        return;
    }
    
    // Получение параметров разрешения
    output_width_ = this->get_parameter("output_width").as_int();
    output_height_ = this->get_parameter("output_height").as_int();
    
    // Проверка валидности параметров разрешения
    if (output_width_ <= 0 || output_height_ <= 0) {
        RCLCPP_ERROR(this->get_logger(), "Неверные параметры разрешения: %dx%d. Используются значения по умолчанию 280x240", 
                     output_width_, output_height_);
        output_width_ = 280;
        output_height_ = 240;
    }
    
    // QoS профиль для подписки (BestEffort для совместимости с touchpad_drawer)
    rclcpp::QoS input_qos(10);
    input_qos.reliability(rclcpp::ReliabilityPolicy::BestEffort);
    input_qos.history(rclcpp::HistoryPolicy::KeepLast);
    
    // Подписчик на изображения (используем параметр input_topic)
    image_sub_ = this->create_subscription<sensor_msgs::msg::Image>(
        input_topic_,
        input_qos,
        std::bind(&ImageProcessorNode::image_callback, this, std::placeholders::_1)
    );
    
    // QoS профиль для публикации (Reliable для совместимости с display_face)
    rclcpp::QoS output_qos(10);
    output_qos.reliability(rclcpp::ReliabilityPolicy::Reliable);
    output_qos.history(rclcpp::HistoryPolicy::KeepLast);
    
    // Публикатор обработанных изображений (используем параметр output_topic)
    image_pub_ = this->create_publisher<sensor_msgs::msg::Image>(
        output_topic_,
        output_qos
    );
    
    RCLCPP_INFO(this->get_logger(), "Image processor node started");
    RCLCPP_INFO(this->get_logger(), "Подписка на %s (любое разрешение, цветное или ч/б)", input_topic_.c_str());
    RCLCPP_INFO(this->get_logger(), "Публикация в %s (%s, %dx%d)", 
                output_topic_.c_str(), OUTPUT_ENCODING, output_width_, output_height_);
}

void ImageProcessorNode::image_callback(const sensor_msgs::msg::Image::SharedPtr msg) {
    try {
        // Конвертация ROS Image в OpenCV Mat (passthrough для сохранения формата)
        cv_bridge::CvImagePtr cv_ptr;
        // Используем пустую строку для passthrough или исходный encoding
        std::string encoding = msg->encoding;
        cv_ptr = cv_bridge::toCvCopy(msg, encoding);
        
        if (cv_ptr->image.empty()) {
            RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 5000,
                                "Не удалось конвертировать изображение из формата: %s", 
                                msg->encoding.c_str());
            return;
        }
        
        cv::Mat input_img = cv_ptr->image;
        
        // Определение формата изображения
        bool is_grayscale = (input_img.channels() == 1);
        
        // Масштабирование изображения до нужного размера (без обрезки)
        cv::Mat resized_img;
        cv::resize(input_img, resized_img, cv::Size(output_width_, output_height_), 
                   0, 0, cv::INTER_LINEAR);
        
        // Конвертация в rgb8 (если ч/б → COLOR_GRAY2RGB)
        cv::Mat rgb_img;
        if (is_grayscale) {
            cv::cvtColor(resized_img, rgb_img, cv::COLOR_GRAY2RGB);
        } else {
            // Если уже цветное, проверяем формат исходного сообщения
            std::string input_encoding = msg->encoding;
            if (resized_img.channels() == 3) {
                // Проверяем формат исходного изображения
                if (input_encoding == "rgb8" || input_encoding == "8UC3") {
                    // Уже RGB формат, используем как есть
                    rgb_img = resized_img;
                } else {
                    // Предполагаем BGR (cv_bridge с PASSTHROUGH может вернуть BGR)
                    cv::cvtColor(resized_img, rgb_img, cv::COLOR_BGR2RGB);
                }
            } else if (resized_img.channels() == 4) {
                // RGBA -> RGB
                cv::cvtColor(resized_img, rgb_img, cv::COLOR_BGRA2RGB);
            } else {
                rgb_img = resized_img;
            }
        }
        
        // Конвертация обратно в ROS Image
        cv_bridge::CvImage out_img;
        out_img.header = msg->header;
        out_img.encoding = OUTPUT_ENCODING;
        out_img.image = rgb_img;
        
        sensor_msgs::msg::Image::SharedPtr out_msg = out_img.toImageMsg();
        
        // Публикация
        image_pub_->publish(*out_msg);
        
    } catch (cv_bridge::Exception& e) {
        RCLCPP_ERROR(this->get_logger(), "Ошибка cv_bridge: %s", e.what());
        return;
    } catch (const std::exception& e) {
        RCLCPP_ERROR(this->get_logger(), "Ошибка при обработке изображения: %s", e.what());
        return;
    }
}

int main(int argc, char * argv[]) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<ImageProcessorNode>());
    rclcpp::shutdown();
    return 0;
}

