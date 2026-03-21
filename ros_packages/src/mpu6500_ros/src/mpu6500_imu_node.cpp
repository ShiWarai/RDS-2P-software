#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <geometry_msgs/msg/quaternion.hpp>
#include <std_msgs/msg/header.hpp>

#include "driver_mpu6500_basic.h"
#include "driver_mpu6500_dmp.h"
#include "driver_mpu6500_interface.h"
#include "driver_mpu6500_register_test.h"
#include "driver_mpu6500_read_test.h"
#include "driver_mpu6500_fifo_test.h"
#include "driver_mpu6500_dmp_read_test.h"

#include <chrono>
#include <memory>
#include <string>
#include <vector>

using namespace std::chrono_literals;

class MPU6500IMUNode : public rclcpp::Node
{
public:
    MPU6500IMUNode() : Node("mpu6500_imu_node")
    {
        // Declare parameters
        this->declare_parameter("interface", "iic");
        this->declare_parameter("address", 0);
        this->declare_parameter("publish_rate", 100.0);
        this->declare_parameter("frame_id", "imu_link");
        this->declare_parameter("enable_calibration", true);
        this->declare_parameter("debug_mode", false);
        
        // Get parameters
        interface_type_ = this->get_parameter("interface").as_string();
        address_ = this->get_parameter("address").as_int();
        publish_rate_ = this->get_parameter("publish_rate").as_double();
        frame_id_ = this->get_parameter("frame_id").as_string();
        enable_calibration_ = this->get_parameter("enable_calibration").as_bool();
        debug_mode_ = this->get_parameter("debug_mode").as_bool();
        
        RCLCPP_INFO(this->get_logger(), "MPU6500 IMU Node initialized with:");
        RCLCPP_INFO(this->get_logger(), "  Interface: %s", interface_type_.c_str());
        RCLCPP_INFO(this->get_logger(), "  Address: %d", address_);
        RCLCPP_INFO(this->get_logger(), "  Publish rate: %.1f Hz", publish_rate_);
        RCLCPP_INFO(this->get_logger(), "  Frame ID: %s", frame_id_.c_str());
        RCLCPP_INFO(this->get_logger(), "  Calibration: %s", enable_calibration_ ? "enabled" : "disabled");
        RCLCPP_INFO(this->get_logger(), "  Debug mode: %s", debug_mode_ ? "enabled" : "disabled");
        
        // Create publisher
        imu_publisher_ = this->create_publisher<sensor_msgs::msg::Imu>("/imu", 10);
        
        // Initialize MPU6500
        if (!initializeMPU6500()) {
            RCLCPP_ERROR(this->get_logger(), "Failed to initialize MPU6500");
            return;
        }
        
        // Create timer for publishing
        timer_ = this->create_wall_timer(
            std::chrono::milliseconds(static_cast<int>(1000.0 / publish_rate_)),
            std::bind(&MPU6500IMUNode::publishIMUData, this)
        );
        
        RCLCPP_INFO(this->get_logger(), "MPU6500 IMU Node started successfully");
    }
    
    ~MPU6500IMUNode()
    {
        if (mpu6500_handle_) {
            mpu6500_deinit(mpu6500_handle_);
        }
    }

private:
    bool initializeMPU6500()
    {
        // Allocate handle
        mpu6500_handle_ = new mpu6500_handle_t;
        if (!mpu6500_handle_) {
            RCLCPP_ERROR(this->get_logger(), "Failed to allocate MPU6500 handle");
            return false;
        }
        
        // Link interface functions
        DRIVER_MPU6500_LINK_INIT(mpu6500_handle_, mpu6500_handle_t);
        DRIVER_MPU6500_LINK_IIC_INIT(mpu6500_handle_, mpu6500_interface_iic_init);
        DRIVER_MPU6500_LINK_IIC_DEINIT(mpu6500_handle_, mpu6500_interface_iic_deinit);
        DRIVER_MPU6500_LINK_IIC_READ(mpu6500_handle_, mpu6500_interface_iic_read);
        DRIVER_MPU6500_LINK_IIC_WRITE(mpu6500_handle_, mpu6500_interface_iic_write);
        DRIVER_MPU6500_LINK_SPI_INIT(mpu6500_handle_, mpu6500_interface_spi_init);
        DRIVER_MPU6500_LINK_SPI_DEINIT(mpu6500_handle_, mpu6500_interface_spi_deinit);
        DRIVER_MPU6500_LINK_SPI_READ(mpu6500_handle_, mpu6500_interface_spi_read);
        DRIVER_MPU6500_LINK_SPI_WRITE(mpu6500_handle_, mpu6500_interface_spi_write);
        DRIVER_MPU6500_LINK_DELAY_MS(mpu6500_handle_, mpu6500_interface_delay_ms);
        DRIVER_MPU6500_LINK_DEBUG_PRINT(mpu6500_handle_, mpu6500_interface_debug_print);
        DRIVER_MPU6500_LINK_RECEIVE_CALLBACK(mpu6500_handle_, mpu6500_interface_receive_callback);
        
        // Set interface
        mpu6500_interface_t interface;
        if (interface_type_ == "spi") {
            interface = MPU6500_INTERFACE_SPI;
        } else {
            interface = MPU6500_INTERFACE_IIC;
        }
        
        uint8_t res = mpu6500_set_interface(mpu6500_handle_, interface);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to set interface");
            return false;
        }
        
        // Set address
        mpu6500_address_t addr = (address_ == 1) ? MPU6500_ADDRESS_AD0_HIGH : MPU6500_ADDRESS_AD0_LOW;
        res = mpu6500_set_addr_pin(mpu6500_handle_, addr);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to set address");
            return false;
        }
        
        // Initialize MPU6500
        res = mpu6500_init(mpu6500_handle_);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to initialize MPU6500");
            return false;
        }
        
        // Delay for stabilization
        mpu6500_interface_delay_ms(3000);
        
        // Disable sleep
        res = mpu6500_set_sleep(mpu6500_handle_, MPU6500_BOOL_FALSE);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to disable sleep");
            return false;
        }
        
        // If SPI interface, disable IIC
        if (interface == MPU6500_INTERFACE_SPI) {
            res = mpu6500_set_disable_iic_slave(mpu6500_handle_, MPU6500_BOOL_TRUE);
            if (res != 0) {
                RCLCPP_ERROR(this->get_logger(), "Failed to disable IIC slave");
                return false;
            }
        }
        
        // Set FIFO size
        res = mpu6500_set_fifo_1024kb(mpu6500_handle_);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to set FIFO size");
            return false;
        }
        
        // Load DMP firmware
        res = mpu6500_dmp_load_firmware(mpu6500_handle_);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to load DMP firmware");
            return false;
        }
        
        // Set DMP features
        res = mpu6500_dmp_set_feature(mpu6500_handle_, MPU6500_DMP_FEATURE_6X_QUAT | MPU6500_DMP_FEATURE_TAP | 
            MPU6500_DMP_FEATURE_SEND_RAW_ACCEL | MPU6500_DMP_FEATURE_SEND_CAL_GYRO | MPU6500_DMP_FEATURE_GYRO_CAL);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to set DMP features");
            return false;
        }
        
        // Set DMP interrupt mode to continuous
        res = mpu6500_dmp_set_interrupt_mode(mpu6500_handle_, MPU6500_DMP_INTERRUPT_MODE_CONTINUOUS);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to set DMP interrupt mode");
            return false;
        }
        
        // Enable DMP first
        res = mpu6500_dmp_set_enable(mpu6500_handle_, MPU6500_BOOL_TRUE);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to enable DMP");
            return false;
        }
        
        // Force FIFO reset
        res = mpu6500_force_fifo_reset(mpu6500_handle_);
        if (res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to reset FIFO");
            return false;
        }
        
        // Delay for DMP stabilization - increased for better reliability
        mpu6500_interface_delay_ms(500);
        
        // Additional check: verify DMP is working by checking FIFO
        uint16_t fifo_count = 0;
        int dmp_check_attempts = 0;
        const int max_dmp_check_attempts = 10;
        bool dmp_working = false;
        
        RCLCPP_INFO(this->get_logger(), "Verifying DMP functionality...");
        
        while (!dmp_working && dmp_check_attempts < max_dmp_check_attempts) {
            res = mpu6500_get_fifo_count(mpu6500_handle_, &fifo_count);
            if (res == 0) {
                RCLCPP_DEBUG(this->get_logger(), "FIFO count check: %d", fifo_count);
                // Even if FIFO is empty, DMP is working if we can read the count
                dmp_working = true;
            } else {
                dmp_check_attempts++;
                RCLCPP_DEBUG(this->get_logger(), "DMP check attempt %d/%d failed, error: %d", dmp_check_attempts, max_dmp_check_attempts, res);
                mpu6500_interface_delay_ms(200);
            }
        }
        
        if (!dmp_working) {
            RCLCPP_WARN(this->get_logger(), "DMP functionality check failed, but proceeding anyway");
        } else {
            RCLCPP_INFO(this->get_logger(), "DMP functionality verified");
        }
        
        // Perform calibration if enabled (after DMP is fully initialized)
        if (enable_calibration_) {
            if (!performCalibration()) {
                RCLCPP_WARN(this->get_logger(), "Calibration failed, continuing with default values");
            }
        } else {
            RCLCPP_INFO(this->get_logger(), "Calibration skipped (disabled)");
        }
        
        RCLCPP_INFO(this->get_logger(), "MPU6500 DMP initialized successfully");
        return true;
    }
    
    bool performCalibration()
    {
        RCLCPP_INFO(this->get_logger(), "Starting hybrid MPU6500 calibration...");
        RCLCPP_INFO(this->get_logger(), "Please keep the device still and level during calibration");
        
        // Wait for DMP to be ready and FIFO to have data
        int ready_attempts = 0;
        const int max_ready_attempts = 20;
        bool dmp_ready = false;
        
        RCLCPP_INFO(this->get_logger(), "Waiting for DMP to be ready...");
        
        while (!dmp_ready && ready_attempts < max_ready_attempts) {
            uint16_t fifo_count = 0;
            uint8_t res = mpu6500_get_fifo_count(mpu6500_handle_, &fifo_count);
            
            if (res == 0 && fifo_count > 0) {
                dmp_ready = true;
                RCLCPP_INFO(this->get_logger(), "DMP ready, FIFO count: %d", fifo_count);
            } else {
                ready_attempts++;
                RCLCPP_DEBUG(this->get_logger(), "Waiting for DMP to be ready... attempt %d/%d", ready_attempts, max_ready_attempts);
                mpu6500_interface_delay_ms(100);
            }
        }
        
        if (!dmp_ready) {
            RCLCPP_WARN(this->get_logger(), "DMP not ready after %d attempts, proceeding anyway", max_ready_attempts);
        }
        
        // Delay for stabilization
        mpu6500_interface_delay_ms(500);
        
        // Read data BEFORE calibration to show initial state
        RCLCPP_INFO(this->get_logger(), "Reading initial data before calibration...");
        int16_t accel_before[128][3];
        float accel_g_before[128][3];
        int16_t gyro_before[128][3];
        float gyro_dps_before[128][3];
        int32_t quat_before[128][4];
        float pitch_before[128];
        float roll_before[128];
        float yaw_before[128];
        uint16_t length_before = 128;
        
        uint8_t res_before = mpu6500_dmp_read(mpu6500_handle_,
                                             accel_before, accel_g_before,
                                             gyro_before, gyro_dps_before,
                                             quat_before,
                                             pitch_before, roll_before, yaw_before,
                                             &length_before);
        
        if (res_before == 0 && length_before > 0) {
            RCLCPP_INFO(this->get_logger(), "BEFORE calibration - Accel: [%d,%d,%d] Gyro: [%d,%d,%d]", 
                       accel_before[0][0], accel_before[0][1], accel_before[0][2],
                       gyro_before[0][0], gyro_before[0][1], gyro_before[0][2]);
        } else {
            RCLCPP_WARN(this->get_logger(), "Failed to read initial data, error: %d", res_before);
        }
        
        // Read multiple samples for calibration using DMP
        const int calibration_samples = 100;
        int32_t accel_sum[3] = {0, 0, 0};
        int32_t gyro_sum[3] = {0, 0, 0};
        int valid_samples = 0;
        
        RCLCPP_INFO(this->get_logger(), "Reading %d samples for calibration...", calibration_samples);
        
        for (int i = 0; i < calibration_samples; i++) {
            // Buffers for DMP data
            int16_t accel_raw[128][3];
            float accel_g[128][3];
            int16_t gyro_raw[128][3];
            float gyro_dps[128][3];
            int32_t quat[128][4];
            float pitch[128];
            float roll[128];
            float yaw[128];
            uint16_t length = 128;
            
            // Read DMP data instead of raw data
            uint8_t res = mpu6500_dmp_read(mpu6500_handle_,
                                          accel_raw, accel_g,
                                          gyro_raw, gyro_dps,
                                          quat,
                                          pitch, roll, yaw,
                                          &length);
            
            if (res == 0 && length > 0) {
                // Use first sample from FIFO
                for (int axis = 0; axis < 3; axis++) {
                    accel_sum[axis] += accel_raw[0][axis];
                    gyro_sum[axis] += gyro_raw[0][axis];
                }
                valid_samples++;
                
                // Show progress every 10 samples
                if ((i + 1) % 10 == 0) {
                    RCLCPP_INFO(this->get_logger(), "Calibration progress: %d/%d samples", i + 1, calibration_samples);
                    RCLCPP_DEBUG(this->get_logger(), "Sample %d: Accel[%d,%d,%d] Gyro[%d,%d,%d]", 
                                i, accel_raw[0][0], accel_raw[0][1], accel_raw[0][2],
                                gyro_raw[0][0], gyro_raw[0][1], gyro_raw[0][2]);
                }
            } else {
                RCLCPP_DEBUG(this->get_logger(), "Failed to read DMP sample %d, error: %d, length: %d", i, res, length);
                
                // Additional debug info for first few failures
                if (i < 5) {
                    RCLCPP_DEBUG(this->get_logger(), "Detailed error info for sample %d: res=%d, length=%d", i, res, length);
                }
            }
            
            // Longer delay between readings for DMP
            mpu6500_interface_delay_ms(20);
        }
        
        RCLCPP_INFO(this->get_logger(), "Calibration complete: %d valid samples out of %d", valid_samples, calibration_samples);
        
        if (valid_samples < calibration_samples / 2) {
            RCLCPP_ERROR(this->get_logger(), "Not enough valid samples for calibration (need at least %d, got %d)", 
                        calibration_samples / 2, valid_samples);
            return false;
        }
        
        // Calculate averages
        int32_t accel_offset[3];
        int32_t gyro_offset[3];
        for (int axis = 0; axis < 3; axis++) {
            accel_offset[axis] = accel_sum[axis] / valid_samples;
            gyro_offset[axis] = gyro_sum[axis] / valid_samples;
        }
        
        // METHOD 1: Try DMP calibration first
        RCLCPP_INFO(this->get_logger(), "Trying DMP calibration...");
        
        // Convert raw offsets to calibrated offsets for DMP
        int32_t accel_offset_cal[3];
        int32_t gyro_offset_cal[3];
        uint8_t dmp_res = mpu6500_dmp_gyro_accel_raw_offset_convert(mpu6500_handle_, 
                                                                     gyro_offset, accel_offset,
                                                                     gyro_offset_cal, accel_offset_cal);
        
        if (dmp_res == 0) {
            // Set DMP biases
            uint8_t accel_bias_res = mpu6500_dmp_set_accel_bias(mpu6500_handle_, accel_offset_cal);
            uint8_t gyro_bias_res = mpu6500_dmp_set_gyro_bias(mpu6500_handle_, gyro_offset_cal);
            
            if (accel_bias_res == 0 && gyro_bias_res == 0) {
                RCLCPP_INFO(this->get_logger(), "DMP calibration successful");
            } else {
                RCLCPP_WARN(this->get_logger(), "DMP calibration failed: accel=%d, gyro=%d", accel_bias_res, gyro_bias_res);
            }
        } else {
            RCLCPP_WARN(this->get_logger(), "DMP offset conversion failed, error: %d", dmp_res);
        }
        
        // METHOD 2: Direct register calibration as backup
        RCLCPP_INFO(this->get_logger(), "Trying direct register calibration...");
        
        // Convert raw offsets to register format
        int16_t accel_offset_reg[3];
        int16_t gyro_offset_reg[3];
        
        // For accelerometer: divide by 8 (LSB = 16g/32768 = 0.000488g)
        // For gyroscope: divide by 4 (LSB = 2000°/s/32768 = 0.061°/s)
        for (int axis = 0; axis < 3; axis++) {
            accel_offset_reg[axis] = (int16_t)(accel_offset[axis] / 8);
            gyro_offset_reg[axis] = (int16_t)(gyro_offset[axis] / 4);
        }
        
        RCLCPP_INFO(this->get_logger(), "Raw offsets - Accel: [%d,%d,%d] Gyro: [%d,%d,%d]", 
                   accel_offset[0], accel_offset[1], accel_offset[2],
                   gyro_offset[0], gyro_offset[1], gyro_offset[2]);
        
        RCLCPP_INFO(this->get_logger(), "Register offsets - Accel: [%d,%d,%d] Gyro: [%d,%d,%d]", 
                   accel_offset_reg[0], accel_offset_reg[1], accel_offset_reg[2],
                   gyro_offset_reg[0], gyro_offset_reg[1], gyro_offset_reg[2]);
        
        // Set accelerometer offset registers directly for each axis
        uint8_t accel_x_res = mpu6500_set_accelerometer_x_offset(mpu6500_handle_, accel_offset_reg[0]);
        uint8_t accel_y_res = mpu6500_set_accelerometer_y_offset(mpu6500_handle_, accel_offset_reg[1]);
        uint8_t accel_z_res = mpu6500_set_accelerometer_z_offset(mpu6500_handle_, accel_offset_reg[2]);
        
        if (accel_x_res != 0 || accel_y_res != 0 || accel_z_res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to set accelerometer offsets: X=%d, Y=%d, Z=%d", 
                        accel_x_res, accel_y_res, accel_z_res);
        } else {
            RCLCPP_INFO(this->get_logger(), "Accelerometer offsets set successfully");
        }
        
        // Set gyroscope offset registers directly for each axis
        uint8_t gyro_x_res = mpu6500_set_gyro_x_offset(mpu6500_handle_, gyro_offset_reg[0]);
        uint8_t gyro_y_res = mpu6500_set_gyro_y_offset(mpu6500_handle_, gyro_offset_reg[1]);
        uint8_t gyro_z_res = mpu6500_set_gyro_z_offset(mpu6500_handle_, gyro_offset_reg[2]);
        
        if (gyro_x_res != 0 || gyro_y_res != 0 || gyro_z_res != 0) {
            RCLCPP_ERROR(this->get_logger(), "Failed to set gyroscope offsets: X=%d, Y=%d, Z=%d", 
                        gyro_x_res, gyro_y_res, gyro_z_res);
        } else {
            RCLCPP_INFO(this->get_logger(), "Gyroscope offsets set successfully");
        }
        
        // Force FIFO reset to apply new offsets
        uint8_t fifo_res = mpu6500_force_fifo_reset(mpu6500_handle_);
        if (fifo_res != 0) {
            RCLCPP_WARN(this->get_logger(), "Failed to reset FIFO after offset setting, error: %d", fifo_res);
        }
        
        // Delay for offsets to take effect
        mpu6500_interface_delay_ms(500);
        
        // Verify calibration by reading data after
        RCLCPP_INFO(this->get_logger(), "Verifying calibration...");
        
        // Read a few samples to verify calibration
        int verification_samples = 10;
        int32_t accel_sum_verify[3] = {0, 0, 0};
        int32_t gyro_sum_verify[3] = {0, 0, 0};
        
        for (int i = 0; i < verification_samples; i++) {
            int16_t accel_raw[128][3];
            float accel_g[128][3];
            int16_t gyro_raw[128][3];
            float gyro_dps[128][3];
            int32_t quat[128][4];
            float pitch[128];
            float roll[128];
            float yaw[128];
            uint16_t length = 128;
            
            uint8_t res = mpu6500_dmp_read(mpu6500_handle_,
                                          accel_raw, accel_g,
                                          gyro_raw, gyro_dps,
                                          quat,
                                          pitch, roll, yaw,
                                          &length);
            
            if (res == 0 && length > 0) {
                for (int axis = 0; axis < 3; axis++) {
                    accel_sum_verify[axis] += accel_raw[0][axis];
                    gyro_sum_verify[axis] += gyro_raw[0][axis];
                }
            }
            
            mpu6500_interface_delay_ms(50);
        }
        
        // Calculate averages and show verification results
        for (int axis = 0; axis < 3; axis++) {
            accel_sum_verify[axis] /= verification_samples;
            gyro_sum_verify[axis] /= verification_samples;
        }
        
        RCLCPP_INFO(this->get_logger(), "After calibration - Accel averages: X=%d, Y=%d, Z=%d", 
                   accel_sum_verify[0], accel_sum_verify[1], accel_sum_verify[2]);
        RCLCPP_INFO(this->get_logger(), "After calibration - Gyro averages: X=%d, Y=%d, Z=%d", 
                   gyro_sum_verify[0], gyro_sum_verify[1], gyro_sum_verify[2]);
        
        // Show improvement
        RCLCPP_INFO(this->get_logger(), "Improvement - Accel: X=%d, Y=%d, Z=%d", 
                   accel_before[0][0] - accel_sum_verify[0],
                   accel_before[0][1] - accel_sum_verify[1],
                   accel_before[0][2] - accel_sum_verify[2]);
        RCLCPP_INFO(this->get_logger(), "Improvement - Gyro: X=%d, Y=%d, Z=%d", 
                   gyro_before[0][0] - gyro_sum_verify[0],
                   gyro_before[0][1] - gyro_sum_verify[1],
                   gyro_before[0][2] - gyro_sum_verify[2]);
        
        RCLCPP_INFO(this->get_logger(), "Hybrid calibration completed");
        RCLCPP_INFO(this->get_logger(), "Accel offsets: X=%d, Y=%d, Z=%d", 
                   accel_offset_reg[0], accel_offset_reg[1], accel_offset_reg[2]);
        RCLCPP_INFO(this->get_logger(), "Gyro offsets: X=%d, Y=%d, Z=%d", 
                   gyro_offset_reg[0], gyro_offset_reg[1], gyro_offset_reg[2]);
        
        return true;
    }
    
    void publishIMUData()
    {
        if (!mpu6500_handle_) {
            return;
        }
        
        // Buffers for DMP data
        int16_t accel_raw[128][3];
        float accel_g[128][3];
        int16_t gyro_raw[128][3];
        float gyro_dps[128][3];
        int32_t quat[128][4];
        float pitch[128];
        float roll[128];
        float yaw[128];
        uint16_t length = 128;
        
        // Read DMP data
        uint8_t res = mpu6500_dmp_read(mpu6500_handle_,
                                      accel_raw, accel_g,
                                      gyro_raw, gyro_dps,
                                      quat,
                                      pitch, roll, yaw,
                                      &length);
        
        if (res != 0) {
            RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 1000, "Failed to read DMP data, error: %d", res);
            return;
        }
        
        if (length == 0) {
            RCLCPP_DEBUG_THROTTLE(this->get_logger(), *this->get_clock(), 1000, "No DMP data available (length=0)");
            return;
        }
        
        // Create IMU message
        auto imu_msg = sensor_msgs::msg::Imu();
        imu_msg.header.stamp = this->now();
        imu_msg.header.frame_id = frame_id_;
        
        // Set orientation (quaternion)
        if (length > 0) {
            // Convert quaternion from fixed point to float
            float qw = static_cast<float>(quat[0][0]) / 1073741824.0f; // 2^30
            float qx = static_cast<float>(quat[0][1]) / 1073741824.0f;
            float qy = static_cast<float>(quat[0][2]) / 1073741824.0f;
            float qz = static_cast<float>(quat[0][3]) / 1073741824.0f;
            
            // Normalize quaternion
            float norm = sqrt(qw*qw + qx*qx + qy*qy + qz*qz);
            if (norm > 0.0f) {
                imu_msg.orientation.w = qw / norm;
                imu_msg.orientation.x = qx / norm;
                imu_msg.orientation.y = qy / norm;
                imu_msg.orientation.z = qz / norm;
            }
            
            // Set angular velocity (gyroscope data in rad/s)
            imu_msg.angular_velocity.x = gyro_dps[0][0] * M_PI / 180.0; // Convert deg/s to rad/s
            imu_msg.angular_velocity.y = gyro_dps[0][1] * M_PI / 180.0;
            imu_msg.angular_velocity.z = gyro_dps[0][2] * M_PI / 180.0;
            
            // Set linear acceleration (accelerometer data in m/s^2)
            imu_msg.linear_acceleration.x = accel_g[0][0] * 9.80665; // Convert g to m/s^2
            imu_msg.linear_acceleration.y = accel_g[0][1] * 9.80665;
            imu_msg.linear_acceleration.z = accel_g[0][2] * 9.80665;
            
            // Set covariance matrices (assuming good quality data)
            imu_msg.orientation_covariance[0] = 0.01; // Small uncertainty in orientation
            imu_msg.orientation_covariance[4] = 0.01;
            imu_msg.orientation_covariance[8] = 0.01;
            
            imu_msg.angular_velocity_covariance[0] = 0.01; // Small uncertainty in angular velocity
            imu_msg.angular_velocity_covariance[4] = 0.01;
            imu_msg.angular_velocity_covariance[8] = 0.01;
            
            imu_msg.linear_acceleration_covariance[0] = 0.01; // Small uncertainty in linear acceleration
            imu_msg.linear_acceleration_covariance[4] = 0.01;
            imu_msg.linear_acceleration_covariance[8] = 0.01;
        }
        
        // Publish message
        imu_publisher_->publish(imu_msg);
    }
    
    // Member variables
    rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr imu_publisher_;
    rclcpp::TimerBase::SharedPtr timer_;
    
    mpu6500_handle_t* mpu6500_handle_ = nullptr;
    std::string interface_type_;
    int address_;
    double publish_rate_;
    std::string frame_id_;
    bool enable_calibration_;
    bool debug_mode_;
};

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    
    auto node = std::make_shared<MPU6500IMUNode>();
    
    if (rclcpp::ok()) {
        rclcpp::spin(node);
    }
    
    rclcpp::shutdown();
    return 0;
}

