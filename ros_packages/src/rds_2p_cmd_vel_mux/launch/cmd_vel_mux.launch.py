#!/usr/bin/env python3
"""
Launch файл мультиплексора cmd_vel.

Поднимает только cmd_vel_mux: источники (/cmd_vel/joy, /cmd_vel/keyboard,
/cmd_vel/voice) и их выбор через /cmd_vel_mux/select не зависят от джойстика.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_arg = DeclareLaunchArgument(
        'mux_config_file',
        default_value=PathJoinSubstitution([
            FindPackageShare('rds_2p_cmd_vel_mux'),
            'config',
            'cmd_vel_mux.yaml',
        ]),
        description='YAML с источниками, таймаутами и источником по умолчанию'
    )

    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )

    cmd_vel_mux_node = Node(
        package='rds_2p_cmd_vel_mux',
        executable='cmd_vel_mux.py',
        name='cmd_vel_mux',
        parameters=[LaunchConfiguration('mux_config_file')],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
        output='screen'
    )

    return LaunchDescription([
        config_arg,
        log_level_arg,
        cmd_vel_mux_node,
    ])