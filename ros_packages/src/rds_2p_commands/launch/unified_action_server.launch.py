#!/usr/bin/env python3
"""
Launch файл для запуска универсального Action сервера.

Этот launch файл запускает универсальный Action сервер, который:
- Поддерживает несколько типов Action в одной ноде
- Регистрирует обработчики для различных действий
"""

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    # Аргументы запуска
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )
    
    interpolate_arg = DeclareLaunchArgument(
        'interpolate',
        default_value='true',
        description='Включить линейную интерполяцию между позами (true/false)'
    )
    
    base_rate_arg = DeclareLaunchArgument(
        'base_rate',
        default_value='50.0',
        description='Базовая частота публикации команд суставов в Hz'
    )
    
    speed_multiplier_arg = DeclareLaunchArgument(
        'speed_multiplier',
        default_value='0.7',
        description='Множитель скорости воспроизведения (1.0 = нормальная скорость, 2.0 = в 2 раза быстрее)'
    )
    
    allow_parallel_arg = DeclareLaunchArgument(
        'allow_parallel_same_class',
        default_value='false',
        description='Разрешить параллельное выполнение действий одного класса (true/false)'
    )
    
    # Unified action server node
    unified_action_server_node = Node(
        package='rds_2p_commands',
        executable='unified_action_server',
        name='unified_action_server',
        output='screen',
        parameters=[{
            'interpolate': LaunchConfiguration('interpolate'),
            'base_rate': LaunchConfiguration('base_rate'),
            'speed_multiplier': LaunchConfiguration('speed_multiplier'),
            'allow_parallel_same_class': LaunchConfiguration('allow_parallel_same_class'),
        }],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
        emulate_tty=True
    )
    
    return LaunchDescription([
        log_level_arg,
        interpolate_arg,
        base_rate_arg,
        speed_multiplier_arg,
        allow_parallel_arg,
        unified_action_server_node,
    ])

