#!/usr/bin/env python3

from launch import LaunchDescription
from launch_ros.actions import Node
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
    
    temperature_arg = DeclareLaunchArgument(
        'enable_temperature',
        default_value='false',
        description='Enable temperature publishing (every 5 seconds)'
    )
    
    # MPU6500 Simple IMU Node
    mpu6500_simple_node = Node(
        package='mpu6500_ros',
        executable='mpu6500_simple_imu_node',
        name='mpu6500_simple_imu_node',
        output='screen',
        parameters=[{
            'address': LaunchConfiguration('address'),
            'publish_rate': LaunchConfiguration('publish_rate'),
            'frame_id': LaunchConfiguration('frame_id'),
            'enable_calibration': LaunchConfiguration('enable_calibration'),
            'enable_temperature': LaunchConfiguration('enable_temperature'),
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
        temperature_arg,
        mpu6500_simple_node,
    ])
