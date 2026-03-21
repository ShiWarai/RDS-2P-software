#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    # Получаем путь к пакету
    pkg_share = get_package_share_directory('rds_2p')
    
    # Аргументы для joint_to_motor_bridge
    motor_command_rate_arg = DeclareLaunchArgument(
        'motor_command_rate',
        default_value='50.0',
        description='Motor command rate in Hz'
    )
    
    offsets_config_file_arg = DeclareLaunchArgument(
        'offsets_config_file',
        default_value=os.path.join(pkg_share, 'config', 'joint_offsets_example.yaml'),
        description='Path to joint offsets configuration file'
    )
    
    verbose_logging_arg = DeclareLaunchArgument(
        'verbose_logging',
        default_value='false',
        description='Enable verbose logging for joint-to-motor transformations'
    )
    
    # Joint-to-motor bridge
    joint_to_motor_bridge_node = Node(
        package='rds_2p',
        executable='joint_to_motor_bridge',
        name='joint_to_motor_bridge',
        parameters=[{
            'motor_command_rate': LaunchConfiguration('motor_command_rate'),
            'offsets_config_file': LaunchConfiguration('offsets_config_file'),
            'verbose_logging': LaunchConfiguration('verbose_logging'),
        }],
        output='screen'
    )
    
    return LaunchDescription([
        # Аргументы
        motor_command_rate_arg,
        offsets_config_file_arg,
        verbose_logging_arg,
        
        # Ноды
        joint_to_motor_bridge_node,
    ])
