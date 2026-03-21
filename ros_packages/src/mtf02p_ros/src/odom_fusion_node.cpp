#include <rclcpp/rclcpp.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2/LinearMath/Matrix3x3.h>
#include <tf2/LinearMath/Vector3.h>

#include <memory>
#include <mutex>
#include <cmath>

class OdomFusionNode : public rclcpp::Node {
public:
  OdomFusionNode()
    : Node("odom_fusion_node")
    , latest_imu_(nullptr)
    , last_odom_raw_(nullptr)
    , global_position_x_(0.0)
    , global_position_y_(0.0)
    , global_position_z_(0.0)
    , imu_timeout_(1.0)
  {
    // Параметры
    declare_parameter("odom_frame_id", "odom");
    declare_parameter("child_frame_id", "odom_link");
    declare_parameter("publish_tf", true);
    declare_parameter("imu_timeout", 1.0);
    declare_parameter("imu_topic", "/imu");
    declare_parameter("odom_topic", "/odom");
    
    odom_frame_id_ = get_parameter("odom_frame_id").as_string();
    child_frame_id_ = get_parameter("child_frame_id").as_string();
    publish_tf_ = get_parameter("publish_tf").as_bool();
    imu_timeout_ = get_parameter("imu_timeout").as_double();
    std::string imu_topic = get_parameter("imu_topic").as_string();
    std::string odom_topic = get_parameter("odom_topic").as_string();
    
    // QoS профили
    auto reliable_qos = rclcpp::QoS(10)
      .reliability(rclcpp::ReliabilityPolicy::Reliable)
      .durability(rclcpp::DurabilityPolicy::Volatile)
      .history(rclcpp::HistoryPolicy::KeepLast);
    
    // SensorDataQoS для IMU (BEST_EFFORT, совместимо с mpu6500_simple_imu_node)
    // Явно указываем BEST_EFFORT для совместимости с издателем
    auto sensor_qos = rclcpp::QoS(5)
      .reliability(rclcpp::ReliabilityPolicy::BestEffort)
      .durability(rclcpp::DurabilityPolicy::Volatile)
      .history(rclcpp::HistoryPolicy::KeepLast);
    
    // Подписка на /odom/raw (триггер публикации)
    odom_raw_sub_ = create_subscription<nav_msgs::msg::Odometry>(
      "/odom/raw",
      reliable_qos,
      std::bind(&OdomFusionNode::odom_raw_callback, this, std::placeholders::_1)
    );
    
    // Подписка на IMU (источник ориентации) - топик настраивается через параметр
    imu_sub_ = create_subscription<sensor_msgs::msg::Imu>(
      imu_topic,
      sensor_qos,
      std::bind(&OdomFusionNode::imu_callback, this, std::placeholders::_1)
    );
    
    // Публикация объединенного odom (топик настраивается через параметр)
    odom_pub_ = create_publisher<nav_msgs::msg::Odometry>(odom_topic, reliable_qos);
    
    // TF broadcaster
    if (publish_tf_) {
      tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);
    }
    
    RCLCPP_INFO(get_logger(), "OdomFusionNode started");
    RCLCPP_INFO(get_logger(), "Subscribing to: /odom/raw, %s", imu_topic.c_str());
    RCLCPP_INFO(get_logger(), "Publishing to: %s", odom_topic.c_str());
    RCLCPP_INFO(get_logger(), "Parameters: odom_frame_id=%s, child_frame_id=%s", odom_frame_id_.c_str(), child_frame_id_.c_str());
    if (publish_tf_) {
      RCLCPP_INFO(get_logger(), "Publishing TF: %s -> %s", odom_frame_id_.c_str(), child_frame_id_.c_str());
    }
  }

private:
  void odom_raw_callback(const nav_msgs::msg::Odometry::SharedPtr msg)
  {
    // Получаем IMU данные с блокировкой
    sensor_msgs::msg::Imu::SharedPtr current_imu;
    bool imu_valid = false;
    {
      std::lock_guard<std::mutex> lock(imu_mutex_);
      
      if (latest_imu_) {
        auto now = this->now();
        auto imu_age = (now - latest_imu_->header.stamp).seconds();
        
        if (imu_age < imu_timeout_) {
          imu_valid = true;
          current_imu = latest_imu_;
        } else {
          RCLCPP_WARN_THROTTLE(
            get_logger(),
            *get_clock(),
            5000,
            "IMU data is too old (%.2f s), using zero orientation",
            imu_age
          );
        }
      } else {
        RCLCPP_WARN_THROTTLE(
          get_logger(),
          *get_clock(),
          5000,
          "No IMU data received yet, using zero orientation"
        );
      }
    }
    
    // Создаем объединенное сообщение одометрии
    auto fused_odom = nav_msgs::msg::Odometry();
    fused_odom.header.stamp = msg->header.stamp;
    fused_odom.header.frame_id = odom_frame_id_;
    fused_odom.child_frame_id = child_frame_id_;
    
    // Ориентация из /imu (или нулевая, если нет данных)
    geometry_msgs::msg::Quaternion orientation;
    if (imu_valid && current_imu) {
      orientation = current_imu->orientation;
      fused_odom.pose.pose.orientation = orientation;
    } else {
      orientation.x = 0.0;
      orientation.y = 0.0;
      orientation.z = 0.0;
      orientation.w = 1.0;
      fused_odom.pose.pose.orientation = orientation;
    }
    
    // Вычисляем приращение позиции в локальной системе координат датчика
    double dx_local = 0.0, dy_local = 0.0, dz_local = 0.0;
    if (last_odom_raw_) {
      dx_local = msg->pose.pose.position.x - last_odom_raw_->pose.pose.position.x;
      dy_local = msg->pose.pose.position.y - last_odom_raw_->pose.pose.position.y;
      dz_local = msg->pose.pose.position.z - last_odom_raw_->pose.pose.position.z;
    } else {
      // Первое сообщение - используем абсолютную позицию
      dx_local = msg->pose.pose.position.x;
      dy_local = msg->pose.pose.position.y;
      dz_local = msg->pose.pose.position.z;
    }
    
    // Преобразуем приращение позиции из локальной системы координат датчика в глобальную
    tf2::Quaternion q(orientation.x, orientation.y, orientation.z, orientation.w);
    q.normalize();
    
    tf2::Matrix3x3 rot_matrix(q);
    tf2::Vector3 delta_local(dx_local, dy_local, dz_local);
    tf2::Vector3 delta_global = rot_matrix * delta_local;
    
    // Накапливаем позицию в глобальной системе координат
    global_position_x_ += delta_global.x();
    global_position_y_ += delta_global.y();
    global_position_z_ += delta_global.z();
    
    fused_odom.pose.pose.position.x = global_position_x_;
    fused_odom.pose.pose.position.y = global_position_y_;
    fused_odom.pose.pose.position.z = global_position_z_;
    
    // Сохраняем текущее сообщение для следующего шага
    last_odom_raw_ = msg;
    
    // Преобразуем линейную скорость из локальной системы координат в глобальную
    tf2::Vector3 local_vel(msg->twist.twist.linear.x, msg->twist.twist.linear.y, msg->twist.twist.linear.z);
    tf2::Vector3 global_vel = rot_matrix * local_vel;
    fused_odom.twist.twist.linear.x = global_vel.x();
    fused_odom.twist.twist.linear.y = global_vel.y();
    fused_odom.twist.twist.linear.z = global_vel.z();
    
    // Угловая скорость из /imu (или нулевая, если нет данных)
    if (imu_valid && current_imu) {
      fused_odom.twist.twist.angular = current_imu->angular_velocity;
    } else {
      fused_odom.twist.twist.angular.x = 0.0;
      fused_odom.twist.twist.angular.y = 0.0;
      fused_odom.twist.twist.angular.z = 0.0;
    }
    
    // Ковариации: позиция из /odom/raw, ориентация из /imu
    fused_odom.pose.covariance = msg->pose.covariance;
    if (imu_valid && current_imu && current_imu->orientation_covariance[0] >= 0) {
      fused_odom.pose.covariance[18] = current_imu->orientation_covariance[0]; // roll-roll
      fused_odom.pose.covariance[24] = current_imu->orientation_covariance[4]; // pitch-pitch
      fused_odom.pose.covariance[30] = current_imu->orientation_covariance[8]; // yaw-yaw
    }
    
    // Ковариации скорости: линейная из /odom/raw, угловая из /imu
    fused_odom.twist.covariance = msg->twist.covariance;
    if (imu_valid && current_imu && current_imu->angular_velocity_covariance[0] >= 0) {
      fused_odom.twist.covariance[18] = current_imu->angular_velocity_covariance[0]; // vroll-vroll
      fused_odom.twist.covariance[24] = current_imu->angular_velocity_covariance[4]; // vpitch-vpitch
      fused_odom.twist.covariance[30] = current_imu->angular_velocity_covariance[8]; // vyaw-vyaw
    }
    
    // Публикуем объединенное сообщение
    odom_pub_->publish(fused_odom);
    
    // Публикуем TF трансформацию
    if (publish_tf_) {
      geometry_msgs::msg::TransformStamped t;
      t.header.stamp = fused_odom.header.stamp;
      t.header.frame_id = odom_frame_id_;
      t.child_frame_id = child_frame_id_;
      
      t.transform.translation.x = fused_odom.pose.pose.position.x;
      t.transform.translation.y = fused_odom.pose.pose.position.y;
      t.transform.translation.z = fused_odom.pose.pose.position.z;
      
      t.transform.rotation = fused_odom.pose.pose.orientation;
      
      tf_broadcaster_->sendTransform(t);
    }
  }
  
  void imu_callback(const sensor_msgs::msg::Imu::SharedPtr msg)
  {
    std::lock_guard<std::mutex> lock(imu_mutex_);
    latest_imu_ = msg;
  }
  
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odom_raw_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr imu_sub_;
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odom_pub_;
  std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
  
  sensor_msgs::msg::Imu::SharedPtr latest_imu_;
  nav_msgs::msg::Odometry::SharedPtr last_odom_raw_;
  std::mutex imu_mutex_;
  
  double global_position_x_;
  double global_position_y_;
  double global_position_z_;
  
  std::string odom_frame_id_;
  std::string child_frame_id_;
  bool publish_tf_;
  double imu_timeout_;
};

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<OdomFusionNode>());
  rclcpp::shutdown();
  return 0;
}

