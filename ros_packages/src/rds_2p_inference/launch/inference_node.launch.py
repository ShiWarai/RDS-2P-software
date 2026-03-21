#!/usr/bin/env python3
"""
Launch файл для узла inference RDS-2P.

Этот launch файл запускает узел inference, который:
- Подписывается на /joint_states, /imu и /cmd_vel
- Выполняет ONNX inference
- Публикует команды суставов в /joint_commands с частотой 50Hz
"""

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
import os
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Declare arguments
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation time if true'
    )

    # Create inference node
    inference_node = Node(
        package='rds_2p_inference',
        executable='inference_node',
        name='rds2p_inference',
        output='screen',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time')
        }],
        emulate_tty=True
    )

    return LaunchDescription([
        use_sim_time_arg,
        inference_node
    ])

