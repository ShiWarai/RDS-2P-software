#!/usr/bin/env python3
"""
Launch файл для запуска Telegram Bridge с параметрами из launch файла.

Токен Telegram передается через обязательный параметр launch файла.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    # Обязательный параметр: токен Telegram бота
    telegram_token_arg = DeclareLaunchArgument(
        'telegram_token',
        description='Токен Telegram бота от BotFather (обязательный параметр)'
    )
    
    # Опциональные параметры
    whitelist_arg = DeclareLaunchArgument(
        'whitelist',
        default_value='',
        description='Список разрешенных chat_id через запятую (например: 123456789,987654321). Пусто = все разрешены'
    )
    
    blacklist_arg = DeclareLaunchArgument(
        'blacklist',
        default_value='',
        description='Список запрещенных chat_id через запятую. Пусто = никто не запрещен'
    )
    
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )
    
    # Telegram Bridge node
    # Используем Python для парсинга списков chat_id
    from launch.actions import OpaqueFunction
    
    def create_telegram_node(context):
        # Парсим whitelist и blacklist из строки в список
        whitelist_str = context.launch_configurations.get('whitelist', '')
        blacklist_str = context.launch_configurations.get('blacklist', '')
        
        whitelist = []
        if whitelist_str:
            try:
                whitelist = [int(x.strip()) for x in whitelist_str.split(',') if x.strip()]
            except ValueError:
                pass
        
        blacklist = []
        if blacklist_str:
            try:
                blacklist = [int(x.strip()) for x in blacklist_str.split(',') if x.strip()]
            except ValueError:
                pass
        
        # Формируем параметры для Node
        node_params = {
            'api_token': context.launch_configurations['telegram_token'],
        }
        
        # Добавляем whitelist и blacklist только если они не пустые
        if whitelist:
            node_params['whitelist'] = whitelist
        if blacklist:
            node_params['blacklist'] = blacklist
        
        return [
            Node(
                package='telegram_ros2',
                executable='telegram_ros2_bridge',
                name='telegram_bridge',
                output='screen',
                parameters=[node_params],
                arguments=['--ros-args', '--log-level', context.launch_configurations.get('log_level', 'info')],
                emulate_tty=True
            )
        ]
    
    telegram_bridge_node = OpaqueFunction(function=create_telegram_node)
    
    return LaunchDescription([
        telegram_token_arg,
        whitelist_arg,
        blacklist_arg,
        log_level_arg,
        telegram_bridge_node,
    ])

