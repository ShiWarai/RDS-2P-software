#!/usr/bin/env python3
"""
Launch файл для запуска универсального Action сервера.

Этот launch файл запускает универсальный Action сервер, который:
- Поддерживает несколько типов Action в одной ноде
- Регистрирует обработчики для различных действий
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
    
    interpolate_arg = DeclareLaunchArgument(
        'interpolate',
        default_value='true',
        description='Включить линейную интерполяцию между позами (true/false)'
    )
    
    base_rate_arg = DeclareLaunchArgument(
        'base_rate',
        default_value='50.0',
        description='Базовая частота публикации команд суставов в Hz'
    )
    
    speed_multiplier_arg = DeclareLaunchArgument(
        'speed_multiplier',
        default_value='0.7',
        description='Множитель скорости воспроизведения (1.0 = нормальная скорость, 2.0 = в 2 раза быстрее)'
    )
    
    allow_parallel_arg = DeclareLaunchArgument(
        'allow_parallel_same_class',
        default_value='false',
        description='Разрешить параллельное выполнение действий одного класса (true/false)'
    )

    # Частота в AudioStamped / ресемп WAV в RobotRoutineHandler.
    # Договор с плеером: на RK «default»/ES8323 PortAudio обычно 44100; WAV ресемпится в RobotRoutine под sr_out.
    audio_output_rate_arg = DeclareLaunchArgument(
        'audio_output_rate',
        default_value='44100',
        description=(
            'Hz в AudioStamped и цель ресемпла WAV здесь же; должно совпадать с '
            '`output_sample_rate` у ноды `audio_player` (rds_2p_audio).'
        ),
    )
    
    audio_force_stereo_arg = DeclareLaunchArgument(
        'audio_output_force_stereo',
        default_value='true',
        description=(
            'Как scripts/test_speaker.py --force-stereo: WAV в ROS как стерео (L=R), '
            'часто нужно чтобы audio_player с player_channels:=1 воспроизводил звук.'
        ),
    )
    audio_chunk_arg = DeclareLaunchArgument(
        'audio_playback_chunk_size',
        default_value='2048',
        description='Аудиокадров на AudioStamped. 2048 снижает DDS/CPU jitter против старого 512.',
    )
    audio_qos_depth_arg = DeclareLaunchArgument(
        'audio_output_qos_depth',
        default_value='50',
        description=(
            'QoS history depth publisher /audio/output (как test_speaker qos_depth; '
            'старое 10 иногда рвёт стрим при DDS).'
        ),
    )
    playback_volume_arg = DeclareLaunchArgument(
        'playback_volume_percent',
        default_value='100.0',
        description='Громкость WAV после нормализации: 100 = номинал, допускается до 200 (клип).',
    )
    wav_peak_norm_arg = DeclareLaunchArgument(
        'wav_peak_normalize',
        default_value='true',
        description='Перед volume: масштабировать mono до пика ±1 (тише master TTS/других источников).',
    )

    # Unified action server node
    unified_action_server_node = Node(
        package='rds_2p_commands',
        executable='unified_action_server',
        name='unified_action_server',
        output='screen',
        parameters=[{
            'interpolate': LaunchConfiguration('interpolate'),
            'base_rate': LaunchConfiguration('base_rate'),
            'speed_multiplier': LaunchConfiguration('speed_multiplier'),
            'allow_parallel_same_class': LaunchConfiguration('allow_parallel_same_class'),
            'audio_output_rate': ParameterValue(LaunchConfiguration('audio_output_rate'), value_type=int),
            'audio_output_force_stereo': ParameterValue(
                LaunchConfiguration('audio_output_force_stereo'), value_type=bool
            ),
            'audio_playback_chunk_size': ParameterValue(
                LaunchConfiguration('audio_playback_chunk_size'), value_type=int
            ),
            'audio_output_qos_depth': ParameterValue(
                LaunchConfiguration('audio_output_qos_depth'), value_type=int
            ),
            'playback_volume_percent': ParameterValue(
                LaunchConfiguration('playback_volume_percent'), value_type=float
            ),
            'wav_peak_normalize': ParameterValue(
                LaunchConfiguration('wav_peak_normalize'), value_type=bool
            ),
        }],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
        emulate_tty=True
    )
    
    return LaunchDescription([
        log_level_arg,
        interpolate_arg,
        base_rate_arg,
        speed_multiplier_arg,
        allow_parallel_arg,
        audio_output_rate_arg,
        audio_force_stereo_arg,
        audio_chunk_arg,
        audio_qos_depth_arg,
        playback_volume_arg,
        wav_peak_norm_arg,
        unified_action_server_node,
    ])

