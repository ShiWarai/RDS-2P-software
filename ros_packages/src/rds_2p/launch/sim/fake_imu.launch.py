#!/usr/bin/env python3

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    # Launch arguments
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
    
    enable_temperature_arg = DeclareLaunchArgument(
        'enable_temperature',
        default_value='false',
        description='Enable temperature publishing (every 5 seconds)'
    )
    
    # Fake IMU Publisher Node
    fake_imu_node = Node(
        package='rds_2p',
        executable='fake_imu_publisher',
        name='fake_imu_publisher',
        output='screen',
        parameters=[{
            'publish_rate': LaunchConfiguration('publish_rate'),
            'frame_id': LaunchConfiguration('frame_id'),
            'enable_temperature': LaunchConfiguration('enable_temperature'),
        }],
        remappings=[
            ('/imu', '/imu'),
        ]
    )
    
    return LaunchDescription([
        publish_rate_arg,
        frame_id_arg,
        enable_temperature_arg,
        fake_imu_node,
    ])
