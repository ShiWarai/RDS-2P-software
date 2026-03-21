#!/usr/bin/env python3
"""
Launch файл для запуска системы обработки команд.

Запускает:
- Unified Action Server (сервер действий)
- Command Parser Node (парсер команд из топиков)

Telegram бот запускается отдельно через пакет rds_2p_telegram_bot
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
from pathlib import Path


def generate_launch_description():
    # Аргументы запуска
    cvc_enabled_arg = DeclareLaunchArgument(
        'cvc_enabled',
        default_value='false',
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
    
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )
    
    transcription_topics_arg = DeclareLaunchArgument(
        'transcription_topics',
        default_value="['/audio/transcription', '/telegram/audio/transcription']",
        description='Список топиков транскрипции для подписки (YAML массив)'
    )
    
    # Unified Action Server
    unified_action_server_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            get_package_share_directory('rds_2p_commands'),
            '/launch/unified_action_server.launch.py'
        ]),
        launch_arguments={
            'log_level': LaunchConfiguration('log_level'),
        }.items()
    )
    
    # Command Parser
    command_parser_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            get_package_share_directory('rds_2p_commands'),
            '/launch/command_parser.launch.py'
        ]),
        launch_arguments={
            'cvc_enabled': LaunchConfiguration('cvc_enabled'),
            'cvc_url': LaunchConfiguration('cvc_url'),
            'cvc_confidence_threshold': LaunchConfiguration('cvc_confidence_threshold'),
            'log_level': LaunchConfiguration('log_level'),
            'transcription_topics': LaunchConfiguration('transcription_topics'),
        }.items()
    )
    
    # Собираем launch описание
    launch_description = LaunchDescription([
        cvc_enabled_arg,
        cvc_url_arg,
        cvc_confidence_threshold_arg,
        log_level_arg,
        transcription_topics_arg,
        unified_action_server_launch,
        command_parser_launch,
    ])
    
    return launch_description

