#!/usr/bin/env python3

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    # Аргументы запуска
    update_rate_arg = DeclareLaunchArgument(
        'update_rate',
        default_value='50.0',
        description='Update rate in Hz'
    )
    
    keyframes_file_arg = DeclareLaunchArgument(
        'keyframes_file',
        default_value='/home/orangepi/RDS-2P-simulator/mjcf_src/configs/keyframes.yml',
        description='Path to keyframes YAML file'
    )
    
    current_keyframe_arg = DeclareLaunchArgument(
        'current_keyframe',
        default_value='home',
        description='Initial keyframe to use'
    )
    
    # Нода keyframe publisher
    keyframe_publisher_node = Node(
        package='rds_2p',
        executable='keyframe_publisher.py',
        name='keyframe_publisher',
        output='screen',
        parameters=[{
            'update_rate': LaunchConfiguration('update_rate'),
            'keyframes_file': LaunchConfiguration('keyframes_file'),
            'current_keyframe': LaunchConfiguration('current_keyframe'),
        }]
    )
    
    return LaunchDescription([
        update_rate_arg,
        keyframes_file_arg,
        current_keyframe_arg,
        keyframe_publisher_node,
    ])
