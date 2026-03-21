#!/usr/bin/env python3
"""
Launch файл для запуска узла управления танцами через джойстик.

Этот launch файл запускает узел dance_joy_controller, который:
- Подписывается на топик /joy для получения данных джойстика
- Отслеживает комбинации кнопок Options + D-pad для запуска танцев
- Отправляет запросы на проигрывание танцев через Action интерфейс /dance/play

Комбинации:
- Options + Вверх (D-pad) -> Танец 1
- Options + Вправо (D-pad) -> Танец 2
- Options + Вниз (D-pad) -> Танец 3
- Options + Влево (D-pad) -> Танец 4
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
    
    # Dance joy controller node
    dance_joy_controller_node = Node(
        package='rds_2p_dance',
        executable='dance_joy_controller',
        name='dance_joy_controller',
        output='screen',
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
        emulate_tty=True
    )
    
    return LaunchDescription([
        log_level_arg,
        dance_joy_controller_node,
    ])


