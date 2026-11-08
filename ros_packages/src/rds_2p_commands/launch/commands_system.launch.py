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


def generate_launch_description():
    # Аргументы запуска
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

    debounce_arg = DeclareLaunchArgument(
        'command_debounce_sec',
        default_value='3.0',
        description='Дребезг command_parser: интервал между командами (сек)'
    )

    panda_llm_tts_arg = DeclareLaunchArgument(
        'panda_llm_tts_enabled',
        default_value='true',
        description='При подстроке в тексте — rkllm + озвучка Paroli параллельно PandaCommand',
    )
    panda_llm_trigger_arg = DeclareLaunchArgument(
        'panda_llm_trigger_substring',
        default_value='панда',
        description='Подстрока (без учёта регистра) для вызова rkllm и Paroli',
    )
    rkllm_complete_action_arg = DeclareLaunchArgument(
        'rkllm_complete_action',
        default_value='/rkllm_ros2/complete',
    )
    rkllm_clear_kv_arg = DeclareLaunchArgument(
        'rkllm_clear_kv_service',
        default_value='/rkllm_ros2/clear_kv_cache',
    )
    paroli_speak_arg = DeclareLaunchArgument(
        'paroli_speak_service',
        default_value='/paroli_ros2/speak',
    )
    paroli_stop_speech_arg = DeclareLaunchArgument(
        'paroli_stop_speech_service',
        default_value='/paroli_ros2/stop_speech',
    )
    rkllm_wait_arg = DeclareLaunchArgument('rkllm_wait_server_sec', default_value='5.0')
    paroli_wait_arg = DeclareLaunchArgument('paroli_wait_service_sec', default_value='3.0')
    rkllm_keep_hist_arg = DeclareLaunchArgument('rkllm_keep_history', default_value='true')
    rkllm_clear_before_arg = DeclareLaunchArgument(
        'rkllm_clear_kv_before_query',
        default_value='false',
    )
    rkllm_max_tok_arg = DeclareLaunchArgument('rkllm_max_new_tokens', default_value='0')

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
            'log_level': LaunchConfiguration('log_level'),
            'transcription_topics': LaunchConfiguration('transcription_topics'),
            'command_debounce_sec': LaunchConfiguration('command_debounce_sec'),
            'panda_llm_tts_enabled': LaunchConfiguration('panda_llm_tts_enabled'),
            'panda_llm_trigger_substring': LaunchConfiguration('panda_llm_trigger_substring'),
            'rkllm_complete_action': LaunchConfiguration('rkllm_complete_action'),
            'rkllm_clear_kv_service': LaunchConfiguration('rkllm_clear_kv_service'),
            'paroli_speak_service': LaunchConfiguration('paroli_speak_service'),
            'paroli_stop_speech_service': LaunchConfiguration('paroli_stop_speech_service'),
            'rkllm_wait_server_sec': LaunchConfiguration('rkllm_wait_server_sec'),
            'paroli_wait_service_sec': LaunchConfiguration('paroli_wait_service_sec'),
            'rkllm_keep_history': LaunchConfiguration('rkllm_keep_history'),
            'rkllm_clear_kv_before_query': LaunchConfiguration('rkllm_clear_kv_before_query'),
            'rkllm_max_new_tokens': LaunchConfiguration('rkllm_max_new_tokens'),
        }.items()
    )
    
    # Собираем launch описание
    launch_description = LaunchDescription([
        log_level_arg,
        transcription_topics_arg,
        debounce_arg,
        panda_llm_tts_arg,
        panda_llm_trigger_arg,
        rkllm_complete_action_arg,
        rkllm_clear_kv_arg,
        paroli_speak_arg,
        paroli_stop_speech_arg,
        rkllm_wait_arg,
        paroli_wait_arg,
        rkllm_keep_hist_arg,
        rkllm_clear_before_arg,
        rkllm_max_tok_arg,
        unified_action_server_launch,
        command_parser_launch,
    ])
    
    return launch_description

