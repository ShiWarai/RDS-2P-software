#!/usr/bin/env python3
"""Launch system_one_node — тонкая HTTP-обёртка system-one-rknn (POST /v1/systemone).

Сервис инференса поднимается отдельно контейнером (scripts/system_one_docker.sh run).
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
            default_value='http://127.0.0.1:8080',
            description='Базовый URL HTTP API system-one-rknn (контейнер)',
        ),
        DeclareLaunchArgument(
            'default_model',
            default_value='kev-0.8b',
            description='Модель, если в запросе model пусто (kev-0.8b | laya-multilingual)',
        ),
        DeclareLaunchArgument(
            'timeout_sec',
            default_value='30.0',
            description='Таймаут HTTP-запроса к system-one-rknn, с',
        ),
        Node(
            package='rkllm_ros2',
            executable='system_one_node.py',
            name='system_one',
            output='screen',
            parameters=[{
                'server_url': LaunchConfiguration('server_url'),
                'default_model': LaunchConfiguration('default_model'),
                'timeout_sec': ParameterValue(
                    LaunchConfiguration('timeout_sec'), value_type=float),
            }],
        ),
    ])