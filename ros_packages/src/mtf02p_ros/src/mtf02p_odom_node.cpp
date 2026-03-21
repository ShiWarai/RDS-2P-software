#include <rclcpp/rclcpp.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2/LinearMath/Quaternion.h>

#include "mtf02p_ros/kalman_filter.hpp"
#include "mtf02p_ros/uart_reader.hpp"
#include "mtf02p_ros/sensor_data.hpp"

#include <cmath>
#include <chrono>
#include <memory>

class MTF02POdomNode : public rclcpp::Node {
public:
  MTF02POdomNode()
    : Node("mtf02p_odom_node")
    , position_x_(0.0)
    , position_y_(0.0)
    , position_z_(0.0)
    , last_system_time_(0)
  {
    declare_parameter("uart_port", "/dev/ttyS3");
    declare_parameter("uart_baudrate", 115200);
    declare_parameter("odom_frame_id", "odom");
    declare_parameter("child_frame_id", "odom_raw_link");
    declare_parameter("publish_tf", true);
    declare_parameter("publish_rate", 50.0);
    declare_parameter("kalman_process_variance", 0.01);
    declare_parameter("kalman_measurement_variance", 0.1);
    declare_parameter("max_velocity_change", 50.0);
    declare_parameter("dead_zone_threshold", 1.0);
    declare_parameter("min_dt", 0.001);
    declare_parameter("max_dt", 2.0);  // Увеличено с 1.0 до 2.0
    
    std::string uart_port = get_parameter("uart_port").as_string();
    int uart_baudrate = get_parameter("uart_baudrate").as_int();
    
    odom_frame_id_ = get_parameter("odom_frame_id").as_string();
    child_frame_id_ = get_parameter("child_frame_id").as_string();
    publish_tf_ = get_parameter("publish_tf").as_bool();
    double publish_rate = get_parameter("publish_rate").as_double();
    
    double kalman_process_var = get_parameter("kalman_process_variance").as_double();
    double kalman_meas_var = get_parameter("kalman_measurement_variance").as_double();
    
    kalman_filter_x_ = std::make_unique<KalmanFilter>(kalman_process_var, kalman_meas_var);
    kalman_filter_y_ = std::make_unique<KalmanFilter>(kalman_process_var, kalman_meas_var);
    
    max_velocity_change_ = get_parameter("max_velocity_change").as_double();
    dead_zone_threshold_ = get_parameter("dead_zone_threshold").as_double();
    min_dt_ = get_parameter("min_dt").as_double();
    max_dt_ = get_parameter("max_dt").as_double();
    
    uart_reader_ = std::make_unique<UARTReader>();
    
    if (!uart_reader_->connect(uart_port, uart_baudrate)) {
      RCLCPP_ERROR(get_logger(), "Failed to connect to %s", uart_port.c_str());
    }
    
    odom_pub_ = create_publisher<nav_msgs::msg::Odometry>("/odom/raw", 10);
    
    if (publish_tf_) {
      tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);
    }
    
    double timer_period = 1.0 / publish_rate;
    timer_ = create_wall_timer(
      std::chrono::milliseconds(static_cast<int>(timer_period * 1000)),
      std::bind(&MTF02POdomNode::process_and_publish, this));
  }
  
  ~MTF02POdomNode()
  {
    if (uart_reader_) {
      uart_reader_->disconnect();
    }
  }

private:
  void process_and_publish()
  {
    SensorData data;
    bool data_processed = false;
    
    // Обрабатываем все доступные данные
    while (uart_reader_->get_data(data)) {
      process_sensor_data(data);
      data_processed = true;
    }
    
    // Публикуем одометрию
    if (data_processed || last_system_time_ != 0) {
      publish_odometry();
    }
  }
  
  void process_sensor_data(const SensorData& data)
  {
    // 1. Фильтрация по качеству потока
    if (data.flow_quality == 0) {
      return;
    }
    
    // 2. Проверка статуса потока и расстояния
    if (!(data.flow_status == 1 && data.distance > 0)) {
      return;
    }
    
    // 3. Использование системного времени датчика
    if (last_system_time_ == 0) {
      last_system_time_ = data.system_time;
      position_z_ = data.distance / 1000.0;
      return;
    }
    
    // Вычисляем dt
    uint32_t dt_ms = data.system_time - last_system_time_;
    if (dt_ms > 0x7FFFFFFF) {  // Обработка переполнения
      dt_ms = (0xFFFFFFFF - last_system_time_) + data.system_time + 1;
    }
    
    double dt = dt_ms / 1000.0;
    
    // 4. Валидация временных интервалов
    if (dt < min_dt_ || dt > max_dt_) {
      last_system_time_ = data.system_time;
      return;
    }
    
    // Расчет реальной скорости потока
    double distance_m = data.distance > 0 ? data.distance / 1000.0 : 1.0;
    double flowx_speed_raw_cm_s = data.flow_vel_x * distance_m;
    double flowy_speed_raw_cm_s = data.flow_vel_y * distance_m;
    
    // Конвертируем в м/с
    double flowx_speed_raw = flowx_speed_raw_cm_s / 100.0;
    double flowy_speed_raw = flowy_speed_raw_cm_s / 100.0;
    
    // 5. Сохраняем предыдущие значения
    double prev_speed_x = kalman_filter_x_->get_value();
    double prev_speed_y = kalman_filter_y_->get_value();
    
    // 6. Применение фильтра Калмана
    double flowx_speed_filtered = kalman_filter_x_->update(flowx_speed_raw);
    double flowy_speed_filtered = kalman_filter_y_->update(flowy_speed_raw);
    
    // 7. Пороговая фильтрация выбросов
    double speed_change_x = std::abs(flowx_speed_filtered - prev_speed_x);
    double speed_change_y = std::abs(flowy_speed_filtered - prev_speed_y);
    double max_velocity_change_ms = max_velocity_change_ / 100.0;
    
    if (speed_change_x > max_velocity_change_ms || speed_change_y > max_velocity_change_ms) {
      last_system_time_ = data.system_time;
      return;
    }
    
    // 8. Dead zone фильтрация
    double speed_magnitude = std::sqrt(flowx_speed_filtered * flowx_speed_filtered + 
                                      flowy_speed_filtered * flowy_speed_filtered);
    double dead_zone_threshold_ms = dead_zone_threshold_ / 100.0;
    
    if (speed_magnitude < dead_zone_threshold_ms) {
      position_z_ = data.distance / 1000.0;
      last_system_time_ = data.system_time;
      return;
    }
    
    // Все проверки пройдены - обновляем позицию
    // Преобразование осей датчика в ROS2 координаты:
    // ROS2 X (вперед) = -flow_vel_y датчика
    // ROS2 Y (влево) = -flow_vel_x датчика
    double dx = -flowy_speed_filtered * dt; // Вперед = -flow_vel_y
    double dy = -flowx_speed_filtered * dt; // Влево = -flow_vel_x
    
    position_x_ += dx;
    position_y_ += dy;
    position_z_ = data.distance / 1000.0;
    
    last_system_time_ = data.system_time;
  }
  
  void publish_odometry()
  {
    auto odom_msg = nav_msgs::msg::Odometry();
    odom_msg.header.stamp = now();
    odom_msg.header.frame_id = odom_frame_id_;
    odom_msg.child_frame_id = child_frame_id_;
    
    odom_msg.pose.pose.position.x = position_x_;
    odom_msg.pose.pose.position.y = position_y_;
    odom_msg.pose.pose.position.z = position_z_;
    
    odom_msg.pose.pose.orientation.x = 0.0;
    odom_msg.pose.pose.orientation.y = 0.0;
    odom_msg.pose.pose.orientation.z = 0.0;
    odom_msg.pose.pose.orientation.w = 1.0;
    
    // Преобразование осей для скорости (аналогично позиции)
    odom_msg.twist.twist.linear.x = -kalman_filter_y_->get_value(); // Вперед = -flow_vel_y
    odom_msg.twist.twist.linear.y = -kalman_filter_x_->get_value(); // Влево = -flow_vel_x
    odom_msg.twist.twist.linear.z = 0.0;
    
    odom_msg.pose.covariance[0] = 0.01;
    odom_msg.pose.covariance[7] = 0.01;
    odom_msg.pose.covariance[14] = 0.01;
    odom_msg.pose.covariance[35] = 0.01;
    
    odom_msg.twist.covariance[0] = 0.01;
    odom_msg.twist.covariance[7] = 0.01;
    odom_msg.twist.covariance[14] = 0.01;
    
    odom_pub_->publish(odom_msg);
    
    if (publish_tf_) {
      geometry_msgs::msg::TransformStamped t;
      t.header.stamp = now();
      t.header.frame_id = odom_frame_id_;
      t.child_frame_id = child_frame_id_;
      
      t.transform.translation.x = position_x_;
      t.transform.translation.y = position_y_;
      t.transform.translation.z = position_z_;
      
      t.transform.rotation.x = 0.0;
      t.transform.rotation.y = 0.0;
      t.transform.rotation.z = 0.0;
      t.transform.rotation.w = 1.0;
      
      tf_broadcaster_->sendTransform(t);
    }
  }
  
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odom_pub_;
  std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
  rclcpp::TimerBase::SharedPtr timer_;
  
  std::unique_ptr<UARTReader> uart_reader_;
  std::unique_ptr<KalmanFilter> kalman_filter_x_;
  std::unique_ptr<KalmanFilter> kalman_filter_y_;
  
  double position_x_;
  double position_y_;
  double position_z_;
  uint32_t last_system_time_;
  
  std::string odom_frame_id_;
  std::string child_frame_id_;
  bool publish_tf_;
  
  double max_velocity_change_;
  double dead_zone_threshold_;
  double min_dt_;
  double max_dt_;
};

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<MTF02POdomNode>());
  rclcpp::shutdown();
  return 0;
}

