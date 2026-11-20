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
from launch_ros.parameter_descriptions import ParameterValue
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
    
    # SPI конфигурация
    spi_device_arg = DeclareLaunchArgument(
        'spi_device',
        default_value='/dev/spidev4.0',
        description='Устройство SPI (например /dev/spidev0.0)'
    )
    spi_mode_arg = DeclareLaunchArgument(
        'spi_mode',
        default_value='0',
        description='Режим SPI (CPOL/CPHA): 0-3'
    )
    spi_speed_arg = DeclareLaunchArgument(
        'spi_speed',
        default_value='20000000',
        description='Скорость SPI в Гц'
    )
    
    # GPIO конфигурация (gpiod chip + line для каждого пина)
    gpio_reset_chip_arg = DeclareLaunchArgument('gpio_reset_chip', default_value='gpiochip4')
    gpio_reset_line_arg = DeclareLaunchArgument('gpio_reset_line', default_value='10')
    gpio_dc_chip_arg = DeclareLaunchArgument('gpio_dc_chip', default_value='gpiochip4')
    gpio_dc_line_arg = DeclareLaunchArgument('gpio_dc_line', default_value='11')
    gpio_cs_chip_arg = DeclareLaunchArgument('gpio_cs_chip', default_value='gpiochip1')
    gpio_cs_line_arg = DeclareLaunchArgument('gpio_cs_line', default_value='3')
    
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
        parameters=[{
            'spi_device': LaunchConfiguration('spi_device'),
            'spi_mode': ParameterValue(LaunchConfiguration('spi_mode'), value_type=int),
            'spi_speed': ParameterValue(LaunchConfiguration('spi_speed'), value_type=int),
            'gpio_reset_chip': LaunchConfiguration('gpio_reset_chip'),
            'gpio_reset_line': ParameterValue(LaunchConfiguration('gpio_reset_line'), value_type=int),
            'gpio_dc_chip': LaunchConfiguration('gpio_dc_chip'),
            'gpio_dc_line': ParameterValue(LaunchConfiguration('gpio_dc_line'), value_type=int),
            'gpio_cs_chip': LaunchConfiguration('gpio_cs_chip'),
            'gpio_cs_line': ParameterValue(LaunchConfiguration('gpio_cs_line'), value_type=int),
        }],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
    )
    
    return LaunchDescription([
        log_level_arg,
        output_width_arg,
        output_height_arg,
        spi_device_arg,
        spi_mode_arg,
        spi_speed_arg,
        gpio_reset_chip_arg,
        gpio_reset_line_arg,
        gpio_dc_chip_arg,
        gpio_dc_line_arg,
        gpio_cs_chip_arg,
        gpio_cs_line_arg,
        image_processor_node,
        display_face_node,
    ])

