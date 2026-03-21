#!/usr/bin/env python3
"""
Launch файл для запуска ноды отображения изображений на дисплее ST7789.

Эта нода:
- Запускает image_processor для преобразования /joy/drawing → /face/image
- Подписывается на /face/image (sensor_msgs/msg/Image, формат rgb8, 280x240)
- Отображает изображения на физическом дисплее ST7789 через SPI
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
    
    # Image processor node для преобразования /joy/drawing → /face/image
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
    
    # Display face node
    display_face_node = Node(
        package='rds_2p_face',
        executable='display_face',
        name='display_face',
        output='screen',
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
    )
    
    return LaunchDescription([
        log_level_arg,
        output_width_arg,
        output_height_arg,
        image_processor_node,
        display_face_node,
    ])

