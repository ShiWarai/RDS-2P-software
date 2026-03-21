#!/usr/bin/env python3
"""
Launch файл для запуска системы отображения лица с тачпадом PS4.

Этот launch файл запускает:
1. ps4_joystick.launch.py - управление через PS4 джойстик (включая touchpad)
2. touchpad_drawer.launch.py - визуализация тачпада в изображение
3. image_processor - обработка изображения (любое разрешение, цветное/ч/б) → (rgb8, настраивается параметрами)
4. display_face.launch.py - отображение на физическом дисплее ST7789

Поток данных:
/joy/touchpad → touchpad_drawer (rds_2p_joystick) → /joy/drawing → image_processor → /face/image → display_face → дисплей
"""

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution


def generate_launch_description():
    # Аргументы запуска
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )
    
    output_width_arg = DeclareLaunchArgument(
        'output_width',
        default_value='280',
        description='Ширина выходного изображения в пикселях'
    )
    
    output_height_arg = DeclareLaunchArgument(
        'output_height',
        default_value='240',
        description='Высота выходного изображения в пикселях'
    )
    
    # Получаем пути к пакетам
    rds_2p_joystick_pkg = FindPackageShare('rds_2p_joystick')
    rds_2p_face_pkg = FindPackageShare('rds_2p_face')
    
    # Включение ps4_joystick.launch.py
    ps4_joystick_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                rds_2p_joystick_pkg,
                'launch',
                'ps4_joystick.launch.py'
            ])
        ),
        launch_arguments={
            'log_level': LaunchConfiguration('log_level'),
        }.items()
    )
    
    # Включение touchpad_drawer.launch.py (теперь в пакете rds_2p_joystick)
    touchpad_drawer_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                rds_2p_joystick_pkg,
                'launch',
                'touchpad_drawer.launch.py'
            ])
        ),
        launch_arguments={
            'log_level': LaunchConfiguration('log_level'),
        }.items()
    )
    
    # Нода-обработчик изображений
    image_processor_node = Node(
        package='rds_2p_face',
        executable='image_processor',
        name='image_processor',
        output='screen',
        parameters=[{
            'input_topic': '/joy/drawing',
            'output_topic': '/face/image',
            'output_width': LaunchConfiguration('output_width'),
            'output_height': LaunchConfiguration('output_height'),
        }],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
    )
    
    # Включение display_face.launch.py
    display_face_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                rds_2p_face_pkg,
                'launch',
                'display_face.launch.py'
            ])
        ),
        launch_arguments={
            'log_level': LaunchConfiguration('log_level'),
        }.items()
    )
    
    return LaunchDescription([
        log_level_arg,
        output_width_arg,
        output_height_arg,
        ps4_joystick_launch,
        touchpad_drawer_launch,
        image_processor_node,
        display_face_launch,
    ])

