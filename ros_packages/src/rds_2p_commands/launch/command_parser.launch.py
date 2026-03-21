#!/usr/bin/env python3
"""
Launch файл для запуска Command Parser Node.

Этот launch файл запускает ноду для парсинга команд из Telegram и голосовых расшифровок.
Поддерживает CVC классификатор и fallback парсинг по ключевым словам.
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
    
    cvc_enabled_arg = DeclareLaunchArgument(
        'cvc_enabled',
        default_value='true',
        description='Включить CVC классификатор команд (true/false)'
    )
    
    cvc_url_arg = DeclareLaunchArgument(
        'cvc_url',
        default_value='http://localhost:8000',
        description='URL CVC API сервера'
    )
    
    cvc_confidence_threshold_arg = DeclareLaunchArgument(
        'cvc_confidence_threshold',
        default_value='0.7',
        description='Минимальный порог уверенности CVC классификатора (0.0-1.0)'
    )
    
    cvc_timeout_arg = DeclareLaunchArgument(
        'cvc_timeout',
        default_value='2.0',
        description='Таймаут для HTTP запросов к CVC серверу в секундах'
    )
    
    config_file_arg = DeclareLaunchArgument(
        'config_file',
        default_value='command_mappings.yaml',
        description='Имя конфигурационного файла команд'
    )
    
    allow_parallel_arg = DeclareLaunchArgument(
        'allow_parallel_same_class',
        default_value='false',
        description='Разрешить параллельное выполнение команд одного класса (true/false)'
    )
    
    transcription_topics_arg = DeclareLaunchArgument(
        'transcription_topics',
        default_value="['/audio/transcription', '/telegram/audio/transcription']",
        description='Список топиков транскрипции для подписки (YAML массив)'
    )
    
    # Command parser node
    command_parser_node = Node(
        package='rds_2p_commands',
        executable='command_parser',
        name='command_parser',
        output='screen',
        parameters=[{
            'cvc_enabled': LaunchConfiguration('cvc_enabled'),
            'cvc_url': LaunchConfiguration('cvc_url'),
            'cvc_confidence_threshold': LaunchConfiguration('cvc_confidence_threshold'),
            'cvc_timeout': LaunchConfiguration('cvc_timeout'),
            'config_file': LaunchConfiguration('config_file'),
            'allow_parallel_same_class': LaunchConfiguration('allow_parallel_same_class'),
            'transcription_topics': LaunchConfiguration('transcription_topics'),
        }],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
        emulate_tty=True
    )
    
    return LaunchDescription([
        log_level_arg,
        cvc_enabled_arg,
        cvc_url_arg,
        cvc_confidence_threshold_arg,
        cvc_timeout_arg,
        config_file_arg,
        allow_parallel_arg,
        transcription_topics_arg,
        command_parser_node,
    ])

