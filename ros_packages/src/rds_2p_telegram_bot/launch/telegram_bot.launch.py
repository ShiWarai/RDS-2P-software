#!/usr/bin/env python3
"""
Launch файл для запуска Telegram бота.

Токен Telegram передается через обязательный параметр launch файла.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_telegram_bot_node(context):
    """Создает Telegram Bot node с правильной обработкой параметров."""
    # Получаем значения параметров
    telegram_token = context.launch_configurations['telegram_token']
    commands_topic = context.launch_configurations.get('commands_topic', '/commands')
    telegram_whitelist = context.launch_configurations.get('telegram_whitelist', '')
    
    # Конвертируем строки в числа
    code_timeout = float(context.launch_configurations.get('code_timeout', '60.0'))
    menu_refresh_interval = float(context.launch_configurations.get('menu_refresh_interval', '5.0'))
    audio_sample_rate = int(context.launch_configurations.get('audio_sample_rate', '16000'))
    auth_enabled = context.launch_configurations.get('auth_enabled', 'true').lower() == 'true'
    
    audio_topic = context.launch_configurations.get('audio_topic', '/telegram/audio')
    log_level = context.launch_configurations.get('log_level', 'info')
    
    return [
        Node(
            package='rds_2p_telegram_bot',
            executable='telegram_bot',
            name='telegram_bot',
            output='screen',
            parameters=[{
                'telegram_token': telegram_token,
                'commands_topic': commands_topic,
                'telegram_whitelist': telegram_whitelist,
                'code_timeout': code_timeout,
                'menu_refresh_interval': menu_refresh_interval,
                'audio_topic': audio_topic,
                'audio_sample_rate': audio_sample_rate,
                'auth_enabled': auth_enabled,
            }],
            arguments=['--ros-args', '--log-level', log_level],
            emulate_tty=True
        )
    ]


def generate_launch_description():
    # Обязательный параметр: токен Telegram бота
    telegram_token_arg = DeclareLaunchArgument(
        'telegram_token',
        description='Токен Telegram бота от BotFather (обязательный параметр)'
    )
    
    # Параметры команд
    commands_topic_arg = DeclareLaunchArgument(
        'commands_topic',
        default_value='/commands',
        description='Топик для подписки на команды (все action серверы публикуют в этот топик)'
    )
    
    # Параметры авторизации
    telegram_whitelist_arg = DeclareLaunchArgument(
        'telegram_whitelist',
        default_value='',
        description='Список разрешенных chat_id через запятую (например: 123456789,987654321). Пусто = требуется авторизация'
    )
    
    code_timeout_arg = DeclareLaunchArgument(
        'code_timeout',
        default_value='60.0',
        description='Таймаут кода авторизации в секундах (по умолчанию 60 секунд = 1 минута)'
    )
    
    auth_enabled_arg = DeclareLaunchArgument(
        'auth_enabled',
        default_value='true',
        description='Включена ли авторизация (true/false). Если false, все пользователи имеют доступ без авторизации'
    )
    
    # Параметры меню
    menu_refresh_interval_arg = DeclareLaunchArgument(
        'menu_refresh_interval',
        default_value='5.0',
        description='Интервал обновления меню в секундах'
    )
    
    # Параметры аудио
    audio_topic_arg = DeclareLaunchArgument(
        'audio_topic',
        default_value='/telegram/audio',
        description='Топик для публикации голосовых сообщений'
    )
    
    audio_sample_rate_arg = DeclareLaunchArgument(
        'audio_sample_rate',
        default_value='16000',
        description='Частота дискретизации для голосовых сообщений'
    )
    
    # Параметры логирования
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )
    
    # Telegram Bot node (используем OpaqueFunction для обработки массива)
    telegram_bot_node = OpaqueFunction(function=generate_telegram_bot_node)
    
    return LaunchDescription([
        telegram_token_arg,
        commands_topic_arg,
        telegram_whitelist_arg,
        code_timeout_arg,
        auth_enabled_arg,
        menu_refresh_interval_arg,
        audio_topic_arg,
        audio_sample_rate_arg,
        log_level_arg,
        telegram_bot_node,
    ])

