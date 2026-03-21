#!/usr/bin/env python3
"""
Launch файл для ноды мониторинга батареи
Подписывается на телеметрию моторов и публикует состояние батареи

Использование:
  # Запуск с уровнем логов INFO (по умолчанию)
  ros2 launch rds_2p battery_monitor.launch.py
  
  # Запуск с детальными логами (DEBUG)
  ros2 launch rds_2p battery_monitor.launch.py log_level:=debug
  
  # Запуск только с важными логами (WARN)
  ros2 launch rds_2p battery_monitor.launch.py log_level:=warn
  
Уровни логирования:
  - debug: Детальная информация (все события, изменения состояний)
  - info:  Основная информация (периодические обновления каждые 5 сек)
  - warn:  Предупреждения (низкий заряд < 20%)
  - error: Ошибки (критический заряд < 10%)
"""

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    return LaunchDescription([
        # Аргументы запуска
        DeclareLaunchArgument(
            'log_level',
            default_value='info',
            description='Logging level: debug (detailed), info (default), warn (warnings only), error (errors only)'
        ),
        
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use simulation time'
        ),
        
        # Нода мониторинга батареи
        Node(
            package='rds_2p',
            executable='battery_monitor',
            name='battery_monitor',
            output='screen',
            parameters=[{
                'use_sim_time': LaunchConfiguration('use_sim_time'),
            }],
            arguments=[
                '--ros-args',
                '--log-level', LaunchConfiguration('log_level')
            ]
        )
    ])

