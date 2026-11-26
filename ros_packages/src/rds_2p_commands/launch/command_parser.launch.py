#!/usr/bin/env python3
"""Command Parser Node: разбор транскрипций по keywords из commands.yaml.

LLM/диалог здесь не запускается — им занимается mirea_rag.
"""

from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'log_level', default_value='info',
            description='Уровень логирования: debug, info, warn, error, fatal'),
        DeclareLaunchArgument(
            'config_file', default_value='commands.yaml',
            description='Имя файла конфигурации команд в share/rds_2p_commands/config/'),
        DeclareLaunchArgument(
            'allow_parallel_same_class', default_value='false',
            description='Разрешить параллельное выполнение команд одного класса'),
        DeclareLaunchArgument(
            'transcription_topics',
            default_value="['/audio/input/transcription', '/telegram/audio/transcription']",
            description='Список топиков транскрипции для подписки (YAML массив)'),
        DeclareLaunchArgument(
            'command_debounce_sec', default_value='3.0',
            description='Минимальный интервал (сек) между одинаковыми командами'),
        Node(
            package='rds_2p_commands',
            executable='command_parser',
            name='command_parser',
            output='screen',
            parameters=[{
                'config_file': LaunchConfiguration('config_file'),
                'allow_parallel_same_class': ParameterValue(
                    LaunchConfiguration('allow_parallel_same_class'), value_type=bool),
                'transcription_topics': LaunchConfiguration('transcription_topics'),
                'command_debounce_sec': ParameterValue(
                    LaunchConfiguration('command_debounce_sec'), value_type=float),
            }],
            arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
            emulate_tty=True,
        ),
    ])