#!/usr/bin/env python3
"""
Launch system_one_client — ROS 2 клиент HTTP API system-one-rknn.

Сервер инференса поднимается отдельно:
    ros2 run system_one_ros system_one_server.sh run
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'server_url',
            default_value='http://127.0.0.1:18477',
            description='Базовый URL HTTP API system-one-rknn (контейнер)',
        ),
        DeclareLaunchArgument(
            'timeout_sec',
            default_value='30.0',
            description='Таймаут HTTP-запроса инференса, с',
        ),
        DeclareLaunchArgument(
            'health_timeout_sec',
            default_value='3.0',
            description='Таймаут GET /health, с',
        ),
        DeclareLaunchArgument(
            'health_period_sec',
            default_value='10.0',
            description='Период health-check и публикации ~/server_ok, с (0 — выключить)',
        ),
        Node(
            package='system_one_ros',
            executable='system_one_client',
            name='system_one_client',
            output='screen',
            parameters=[{
                'server_url': LaunchConfiguration('server_url'),
                'timeout_sec': ParameterValue(
                    LaunchConfiguration('timeout_sec'), value_type=float),
                'health_timeout_sec': ParameterValue(
                    LaunchConfiguration('health_timeout_sec'), value_type=float),
                'health_period_sec': ParameterValue(
                    LaunchConfiguration('health_period_sec'), value_type=float),
            }],
        ),
    ])
