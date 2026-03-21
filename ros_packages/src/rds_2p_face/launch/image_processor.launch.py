#!/usr/bin/env python3
"""
Launch файл для запуска ноды обработки изображений image_processor.

Эта нода:
- Подписывается на входной топик (любое разрешение, цветное или ч/б)
- Масштабирует изображение до заданного разрешения
- Публикует результат в выходной топик (rgb8, настраивается параметрами)
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
    
    input_topic_arg = DeclareLaunchArgument(
        'input_topic',
        default_value='',
        description='Входной топик для изображений (обязательный)'
    )
    
    output_topic_arg = DeclareLaunchArgument(
        'output_topic',
        default_value='',
        description='Выходной топик для обработанных изображений (обязательный)'
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
    
    # Image processor node
    image_processor_node = Node(
        package='rds_2p_face',
        executable='image_processor',
        name='image_processor',
        output='screen',
        parameters=[{
            'input_topic': LaunchConfiguration('input_topic'),
            'output_topic': LaunchConfiguration('output_topic'),
            'output_width': LaunchConfiguration('output_width'),
            'output_height': LaunchConfiguration('output_height'),
        }],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
    )
    
    return LaunchDescription([
        log_level_arg,
        input_topic_arg,
        output_topic_arg,
        output_width_arg,
        output_height_arg,
        image_processor_node,
    ])

