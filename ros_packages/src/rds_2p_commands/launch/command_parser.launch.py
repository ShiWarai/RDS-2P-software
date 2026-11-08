#!/usr/bin/env python3
"""
Launch файл для запуска Command Parser Node.

Подписка на транскрипции и Telegram; разбор по keywords из commands.yaml; LLM+Paroli — **llm_commands.py**.
"""

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    # Аргументы запуска
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )

    config_file_arg = DeclareLaunchArgument(
        'config_file',
        default_value='commands.yaml',
        description='Имя файла конфигурации команд в share/rds_2p_commands/config/'
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

    debounce_arg = DeclareLaunchArgument(
        'command_debounce_sec',
        default_value='3.0',
        description='Минимальный интервал (сек) между одинаковыми командами одного источника (0 = выкл)'
    )

    panda_llm_tts_arg = DeclareLaunchArgument(
        'panda_llm_tts_enabled',
        default_value='true',
        description=(
            'Если true и в тексте есть подстрока panda_llm_trigger_substring — после распознавания '
            'команды дополнительно запрос rkllm (ChatCompletion) и озвучка ответа через Paroli'
        ),
    )
    panda_llm_trigger_arg = DeclareLaunchArgument(
        'panda_llm_trigger_substring',
        default_value='панда',
        description='Подстрока в тексте команды (без учёта регистра) для цепочки rkllm → Paroli',
    )
    rkllm_complete_action_arg = DeclareLaunchArgument(
        'rkllm_complete_action',
        default_value='/rkllm_ros2/complete',
        description='Имя action rkllm (ChatCompletion)',
    )
    rkllm_clear_kv_arg = DeclareLaunchArgument(
        'rkllm_clear_kv_service',
        default_value='/rkllm_ros2/clear_kv_cache',
        description='Сервис сброса KV rkllm (пустая строка — не создавать клиент)',
    )
    paroli_speak_arg = DeclareLaunchArgument(
        'paroli_speak_service',
        default_value='/paroli_ros2/speak',
        description='Сервис Paroli Speak (пустая строка — отключить озвучку)',
    )
    paroli_stop_speech_arg = DeclareLaunchArgument(
        'paroli_stop_speech_service',
        default_value='/paroli_ros2/stop_speech',
        description='std_srvs/Trigger — прервать синтез Paroli (команда «хватит» и т.п.)',
    )
    rkllm_wait_arg = DeclareLaunchArgument(
        'rkllm_wait_server_sec',
        default_value='5.0',
        description='Таймаут ожидания action-сервера rkllm (сек)',
    )
    paroli_wait_arg = DeclareLaunchArgument(
        'paroli_wait_service_sec',
        default_value='3.0',
        description='Таймаут ожидания сервиса Paroli speak (сек)',
    )
    rkllm_keep_hist_arg = DeclareLaunchArgument(
        'rkllm_keep_history',
        default_value='true',
        description='Поле keep_history в goal ChatCompletion (см. README rkllm_ros2 / persist_session_kv)',
    )
    rkllm_clear_before_arg = DeclareLaunchArgument(
        'rkllm_clear_kv_before_query',
        default_value='false',
        description='Перед каждым запросом к rkllm вызывать clear_kv_cache (изолированный ответ)',
    )
    rkllm_max_tok_arg = DeclareLaunchArgument(
        'rkllm_max_new_tokens',
        default_value='0',
        description='max_new_tokens в goal (0 — лимит из ноды rkllm)',
    )
    llm_reply_log_arg = DeclareLaunchArgument(
        'llm_reply_log_max_chars',
        default_value='280',
        description=(
            'Сколько первых символов ответа LLM печатать в одной INFO-строке-сводке (0 — весь текст)'
        ),
    )
    paroli_speak_log_arg = DeclareLaunchArgument(
        'paroli_speak_log_max_chars',
        default_value='0',
        description=(
            'Сколько символов печатать в каждой строке «Paroli /speak фр.» (0 — весь фрагмент, как в req.text)'
        ),
    )

    # Command parser node
    command_parser_node = Node(
        package='rds_2p_commands',
        executable='command_parser',
        name='command_parser',
        output='screen',
        parameters=[{
            'config_file': LaunchConfiguration('config_file'),
            'allow_parallel_same_class': LaunchConfiguration('allow_parallel_same_class'),
            'transcription_topics': LaunchConfiguration('transcription_topics'),
            'command_debounce_sec': LaunchConfiguration('command_debounce_sec'),
            'panda_llm_tts_enabled': ParameterValue(
                LaunchConfiguration('panda_llm_tts_enabled'), value_type=bool
            ),
            'panda_llm_trigger_substring': LaunchConfiguration('panda_llm_trigger_substring'),
            'rkllm_complete_action': LaunchConfiguration('rkllm_complete_action'),
            'rkllm_clear_kv_service': LaunchConfiguration('rkllm_clear_kv_service'),
            'paroli_speak_service': LaunchConfiguration('paroli_speak_service'),
            'paroli_stop_speech_service': LaunchConfiguration('paroli_stop_speech_service'),
            'rkllm_wait_server_sec': ParameterValue(
                LaunchConfiguration('rkllm_wait_server_sec'), value_type=float
            ),
            'paroli_wait_service_sec': ParameterValue(
                LaunchConfiguration('paroli_wait_service_sec'), value_type=float
            ),
            'rkllm_keep_history': ParameterValue(
                LaunchConfiguration('rkllm_keep_history'), value_type=bool
            ),
            'rkllm_clear_kv_before_query': ParameterValue(
                LaunchConfiguration('rkllm_clear_kv_before_query'), value_type=bool
            ),
            'rkllm_max_new_tokens': ParameterValue(
                LaunchConfiguration('rkllm_max_new_tokens'), value_type=int
            ),
            'llm_reply_log_max_chars': ParameterValue(
                LaunchConfiguration('llm_reply_log_max_chars'), value_type=int
            ),
            'paroli_speak_log_max_chars': ParameterValue(
                LaunchConfiguration('paroli_speak_log_max_chars'), value_type=int
            ),
        }],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
        emulate_tty=True
    )
    
    return LaunchDescription([
        log_level_arg,
        config_file_arg,
        allow_parallel_arg,
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
        llm_reply_log_arg,
        paroli_speak_log_arg,
        command_parser_node,
    ])

