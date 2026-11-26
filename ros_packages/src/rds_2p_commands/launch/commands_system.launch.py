#!/usr/bin/env python3
"""Система команд: unified_action_server + command_parser (regex/keywords).

LLM/диалог вынесен в mirea_rag; здесь только команды из commands.yaml.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'log_level', default_value='info',
            description='Уровень логирования: debug, info, warn, error, fatal'),
        DeclareLaunchArgument(
            'config_file', default_value='commands.yaml',
            description='Имя файла конфигурации команд'),
        DeclareLaunchArgument(
            'transcription_topics',
            default_value="['/audio/input/transcription', '/telegram/audio/transcription']",
            description='Список топиков транскрипции'),
        DeclareLaunchArgument(
            'command_debounce_sec', default_value='3.0',
            description='Дребезг command_parser (сек)'),
        DeclareLaunchArgument(
            'publish_motor_positions', default_value='true',
            description='Публиковать позы routine в /motors/commands'),
        DeclareLaunchArgument(
            'motor_config_file', default_value='',
            description='YAML ftservo_ros для units→rad; пусто — config_example.yaml'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                get_package_share_directory('rds_2p_commands'),
                '/launch/unified_action_server.launch.py']),
            launch_arguments={
                'log_level': LaunchConfiguration('log_level'),
                'publish_motor_positions': LaunchConfiguration('publish_motor_positions'),
                'motor_config_file': LaunchConfiguration('motor_config_file'),
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                get_package_share_directory('rds_2p_commands'),
                '/launch/command_parser.launch.py']),
            launch_arguments={
                'log_level': LaunchConfiguration('log_level'),
                'config_file': LaunchConfiguration('config_file'),
                'transcription_topics': LaunchConfiguration('transcription_topics'),
                'command_debounce_sec': LaunchConfiguration('command_debounce_sec'),
            }.items(),
        ),
    ])