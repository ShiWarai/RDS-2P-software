#!/usr/bin/env python3

import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    # Путь к конфигурации контроллеров
    controllers_config = PathJoinSubstitution([
        FindPackageShare('rds_2p'),
        'config',
        'controllers.yaml'
    ])

    # Аргументы запуска
    use_sim_time = LaunchConfiguration('use_sim_time')
    use_controllers = LaunchConfiguration('use_controllers')

    # Объявляем аргументы
    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation time'
    )

    declare_use_controllers = DeclareLaunchArgument(
        'use_controllers',
        default_value='true',
        description='Launch joint controllers'
    )

    # Controller Manager
    controller_manager = Node(
        package='controller_manager',
        executable='ros2_control_node',
        parameters=[
            controllers_config,
            {'use_sim_time': use_sim_time}
        ],
        output='screen',
        condition=IfCondition(use_controllers)
    )

    return LaunchDescription([
        declare_use_sim_time,
        declare_use_controllers,
        controller_manager
    ]) 