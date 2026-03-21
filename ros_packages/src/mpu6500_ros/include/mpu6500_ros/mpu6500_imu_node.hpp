#ifndef MPU6500_IMU_NODE_HPP
#define MPU6500_IMU_NODE_HPP

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <std_msgs/msg/header.hpp>
#include <geometry_msgs/msg/quaternion.hpp>
#include <geometry_msgs/msg/vector3.hpp>

#include <chrono>
#include <thread>
#include <iostream>
#include <cmath>

// MPU6500 library includes
extern "C" {
#include "driver_mpu6500_dmp.h"
#include "driver_mpu6500_interface.h"
}

/**
 * @brief ROS node for MPU6500 IMU sensor with DMP support
 * 
 * This node reads data from the MPU6500 sensor using the Digital Motion Processor (DMP)
 * and publishes it as IMU messages to the /imu topic. It provides:
 * - Accelerometer data (in m/s²)
 * - Gyroscope data (in rad/s)
 * - Orientation data as quaternions (from DMP)
 * - Euler angles (pitch, roll, yaw) for reference
 * 
 * Note: DMP is only supported on I2C interface, not SPI.
 */
class MPU6500IMUNode : public rclcpp::Node {
private:
    // MPU6500 handle
    mpu6500_handle_t mpu6500_handle_;
    
    // Configuration parameters
    int publish_rate_hz_;
    mpu6500_interface_t interface_;
    mpu6500_address_t address_;
    
    // Data buffers for DMP
    int16_t accel_raw[128][3];
    float accel_g[128][3];
    int16_t gyro_raw[128][3];
    float gyro_dps[128][3];
    int32_t quat[128][4];
    float pitch[128];
    float roll[128];
    float yaw[128];
    uint16_t fifo_length;
    
    // ROS components
    rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr imu_publisher_;
    rclcpp::TimerBase::SharedPtr timer_;
    
    // Timing
    std::chrono::steady_clock::time_point last_publish_time_;
    
public:
    /**
     * @brief Constructor
     * 
     * Initializes the node with default parameters:
     * - Publish rate: 50 Hz
     * - Interface: I2C (DMP requires I2C)
     * - Address: AD0_LOW (0xD0)
     * - DMP enabled with quaternion support
     */
    MPU6500IMUNode();
    
    /**
     * @brief Destructor
     * 
     * Cleans up MPU6500 DMP resources
     */
    ~MPU6500IMUNode();
    
    /**
     * @brief Set publish rate
     * 
     * @param rate_hz Publish rate in Hz
     */
    void setPublishRate(int rate_hz);
    
    /**
     * @brief Set interface type
     * 
     * @param interface MPU6500 interface (I2C or SPI, but DMP only works with I2C)
     */
    void setInterface(mpu6500_interface_t interface);
    
    /**
     * @brief Set device address
     * 
     * @param address MPU6500 device address
     */
    void setAddress(mpu6500_address_t address);
    
private:
    /**
     * @brief Initialize ROS components
     * 
     * @param frame_id Frame ID for IMU messages
     * @return true if successful, false otherwise
     */
    bool initializeROS(const std::string& frame_id);
    
    /**
     * @brief Initialize MPU6500 DMP
     * 
     * Initializes the Digital Motion Processor for quaternion output.
     * Note: DMP is only supported on I2C interface.
     * 
     * @return true if successful, false otherwise
     */
    bool initializeMPU6500DMP();
    
    /**
     * @brief Read data from MPU6500 DMP
     * 
     * Reads accelerometer, gyroscope, and quaternion data from the DMP FIFO.
     * 
     * @return true if successful, false otherwise
     */
    bool readMPU6500DMPData();
    
    /**
     * @brief Publish IMU data to ROS topic
     * 
     * Creates and publishes an IMU message with:
     * - Linear acceleration (m/s²)
     * - Angular velocity (rad/s)
     * - Orientation as quaternions
     * - Proper covariance matrices
     */
    void publishIMUData();
    
    /**
     * @brief Timer callback for publishing data
     */
    void timer_callback();
};

#endif // MPU6500_IMU_NODE_HPP
