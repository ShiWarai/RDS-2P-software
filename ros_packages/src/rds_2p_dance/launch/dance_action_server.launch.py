#!/usr/bin/env python3
"""
Launch файл для запуска Action сервера проигрывания танцев rds_2p_dance.

Этот launch файл запускает Action сервер, который:
- Принимает запросы на проигрывание танцев через Action интерфейс /dance/play
- Загружает анимации из CSV файлов в папке animations
- Публикует команды суставов в /joint_commands
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
    
    # Dance action server node
    dance_action_server_node = Node(
        package='rds_2p_dance',
        executable='dance_action_server',
        name='dance_action_server',
        output='screen',
        parameters=[{
            'interpolate': LaunchConfiguration('interpolate'),
            'base_rate': LaunchConfiguration('base_rate'),
            'speed_multiplier': LaunchConfiguration('speed_multiplier'),
        }],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
        emulate_tty=True
    )
    
    return LaunchDescription([
        log_level_arg,
        interpolate_arg,
        base_rate_arg,
        speed_multiplier_arg,
        dance_action_server_node,
    ])

