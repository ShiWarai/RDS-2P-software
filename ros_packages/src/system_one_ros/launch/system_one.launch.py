#!/usr/bin/env python3
"""ROS 2 system-one: нативный Kev/RKLLM или HTTP-клиент к контейнеру.

По умолчанию — native: узел сам грузит Kev-0.8B на NPU и отдаёт /system_one/ask.
HTTP-режим оставлен для совместимости (mode:=http, контейнер на server_url).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    mode = LaunchConfiguration('mode')
    native_condition = IfCondition(PythonExpression(["'", mode, "' == 'native'"]))
    http_condition = IfCondition(PythonExpression(["'", mode, "' == 'http'"]))

    return LaunchDescription([
        DeclareLaunchArgument(
            'mode', default_value='native',
            description='native — Kev внутри ROS 2 ноды; http — клиент контейнера'),
        DeclareLaunchArgument(
            'model_root', default_value='/home/orangepi/models/kev-0.8b-rknn',
            description='Каталог Kev: *.rkllm, tokenizer.json, pointer.json, *.npy'),
        DeclareLaunchArgument(
            'rkllm_lib', default_value='/opt/npu/librkllmrt-1.3.1.so'),
        DeclareLaunchArgument(
            'rknpu_lib', default_value='/opt/npu/librknnrt-2.3.2.so'),
        DeclareLaunchArgument('model', default_value='kev-0.8b'),

        # HTTP fallback (старый контейнер).
        DeclareLaunchArgument(
            'server_url', default_value='http://127.0.0.1:18477'),
        DeclareLaunchArgument(
            'timeout_sec', default_value='30.0'),
        DeclareLaunchArgument(
            'health_timeout_sec', default_value='3.0'),
        DeclareLaunchArgument(
            'health_period_sec', default_value='10.0'),

        Node(
            package='system_one_ros',
            executable='system_one_native',
            name='system_one',
            output='screen',
            condition=native_condition,
            parameters=[{
                'model_root': LaunchConfiguration('model_root'),
                'rkllm_lib': LaunchConfiguration('rkllm_lib'),
                'rknpu_lib': LaunchConfiguration('rknpu_lib'),
                'model': LaunchConfiguration('model'),
            }],
        ),
        Node(
            package='system_one_ros',
            executable='system_one_client',
            name='system_one',
            output='screen',
            condition=http_condition,
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