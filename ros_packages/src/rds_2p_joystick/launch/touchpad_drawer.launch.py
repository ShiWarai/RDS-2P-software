#!/usr/bin/env python3
"""
Launch файл для запуска ноды визуализации тачпада.

Эта нода:
- Подписывается на /joy/touchpad (geometry_msgs/msg/PointStamped) для получения данных тачпада
- Подписывается на /joy (sensor_msgs/msg/Joy) для управления толщиной кисти и стиранием
- Публикует ЧБ изображение в /joy/drawing (sensor_msgs/msg/Image)

Управление:
- L2 ось (индекс 4): -1 = максимальная толщина, 1 = минимальная толщина
- Стирание: L2==-1 + кнопка крестика (кнопка 0)
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
    
    # Touchpad drawer node
    touchpad_drawer_node = Node(
        package='rds_2p_joystick',
        executable='touchpad_drawer',
        name='touchpad_drawer',
        output='screen',
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
    )
    
    return LaunchDescription([
        log_level_arg,
        touchpad_drawer_node,
    ])

