#!/usr/bin/env python3

from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    # Launch arguments
    address_arg = DeclareLaunchArgument(
        'address',
        default_value='0',
        description='MPU6500 address: 0 or 1'
    )
    
    publish_rate_arg = DeclareLaunchArgument(
        'publish_rate',
        default_value='100.0',
        description='IMU data publish rate in Hz'
    )
    
    frame_id_arg = DeclareLaunchArgument(
        'frame_id',
        default_value='imu_link',
        description='Frame ID for IMU messages'
    )
    
    calibration_arg = DeclareLaunchArgument(
        'enable_calibration',
        default_value='true',
        description='Enable automatic calibration on startup'
    )
    
    i2c_device_arg = DeclareLaunchArgument(
        'i2c_device',
        default_value='/dev/i2c-1',
        description='I2C device path (e.g. /dev/i2c-1)'
    )
    
    spi_device_arg = DeclareLaunchArgument(
        'spi_device',
        default_value='/dev/spidev0.0',
        description='SPI device path (e.g. /dev/spidev0.0)'
    )
    
    spi_mode_arg = DeclareLaunchArgument(
        'spi_mode',
        default_value='3',
        description='SPI mode 0-3 (CPOL/CPHA)'
    )
    
    spi_speed_arg = DeclareLaunchArgument(
        'spi_speed',
        default_value='1000000',
        description='SPI speed in Hz'
    )
    
    # MPU6500 IMU Node
    mpu6500_node = Node(
        package='mpu6500_ros',
        executable='mpu6500_imu_node',
        name='mpu6500_imu_node',
        output='screen',
        parameters=[{
            'address': LaunchConfiguration('address'),
            'publish_rate': LaunchConfiguration('publish_rate'),
            'frame_id': LaunchConfiguration('frame_id'),
            'enable_calibration': LaunchConfiguration('enable_calibration'),
            'i2c_device': LaunchConfiguration('i2c_device'),
            'spi_device': LaunchConfiguration('spi_device'),
            'spi_mode': ParameterValue(LaunchConfiguration('spi_mode'), value_type=int),
            'spi_speed': ParameterValue(LaunchConfiguration('spi_speed'), value_type=int),
        }],
        remappings=[
            ('/imu', '/imu'),
        ]
    )
    
    return LaunchDescription([
        address_arg,
        publish_rate_arg,
        frame_id_arg,
        calibration_arg,
        i2c_device_arg,
        spi_device_arg,
        spi_mode_arg,
        spi_speed_arg,
        mpu6500_node,
    ])
