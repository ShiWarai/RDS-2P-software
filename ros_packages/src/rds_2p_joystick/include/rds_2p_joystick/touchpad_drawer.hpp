#ifndef RDS_2P_JOYSTICK__TOUCHPAD_DRAWER_HPP_
#define RDS_2P_JOYSTICK__TOUCHPAD_DRAWER_HPP_

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/point_stamped.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <sensor_msgs/msg/joy.hpp>
#include <rclcpp/qos.hpp>
#include <vector>
#include <deque>
#include <mutex>
#include <atomic>
#include <opencv2/opencv.hpp>

struct TouchPoint {
    double x;
    double y;
    double timestamp;
    double received_time;
    int brush_size;  // Размер кисти на момент получения точки
};

class TouchpadDrawerNode : public rclcpp::Node {
public:
    TouchpadDrawerNode();

private:
    void touchpad_callback(const geometry_msgs::msg::PointStamped::SharedPtr msg);
    void joy_callback(const sensor_msgs::msg::Joy::SharedPtr msg);
    void clear_image();
    void draw_on_image();
    void draw_line(int x1, int y1, int x2, int y2, int width);
    void draw_circle(int cx, int cy, int radius);
    void publish_image();
    
    // Подписчики и публикаторы
    rclcpp::Subscription<geometry_msgs::msg::PointStamped>::SharedPtr touchpad_sub_;
    rclcpp::Subscription<sensor_msgs::msg::Joy>::SharedPtr joy_sub_;
    rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr image_pub_;
    rclcpp::TimerBase::SharedPtr publish_timer_;
    
    // Данные
    std::deque<TouchPoint> touch_history_;
    cv::Mat image_;  // OpenCV Mat вместо std::vector для быстрой отрисовки
    std::mutex data_mutex_;
    
    // Параметры
    int touchpad_width_;
    int touchpad_height_;
    size_t max_history_;
    int min_brush_size_;
    int max_brush_size_;
    double fast_touch_threshold_;
    size_t max_points_per_frame_;  // Лимит точек для обработки за кадр
    
    // Состояние
    std::atomic<int> brush_size_;  // Atomic для быстрого доступа без блокировок
    double last_clear_time_;
    size_t last_drawn_index_;  // Индекс последней отрисованной точки в touch_history_
    std::atomic<bool> dirty_;  // Флаг изменений для пропуска пустых публикаций
};

#endif  // RDS_2P_JOYSTICK__TOUCHPAD_DRAWER_HPP_

