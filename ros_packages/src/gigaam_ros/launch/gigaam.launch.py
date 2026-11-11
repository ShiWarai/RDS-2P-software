#!/usr/bin/env python3
"""Запуск узла распознавания gigaam_ros (GigaAM CTC, RKNN / RK3588 NPU).

Примеры:

  ros2 launch gigaam_ros gigaam.launch.py
  ros2 launch gigaam_ros vad.launch.py
  ros2 launch gigaam_ros gigaam.launch.py audio_topic:=/audio/vad

Модель по умолчанию берётся из share/gigaam_ros/models (параметр ``model_path``
переопределяет — каталог с ``.rknn`` + ``multilingual_vocab.txt`` или путь к ``.rknn``).
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    pkg_share_dir = get_package_share_directory('gigaam_ros')
    default_model_path = os.path.join(pkg_share_dir, 'models')

    return LaunchDescription([
        DeclareLaunchArgument(
            'model_path', default_value=default_model_path,
            description='Каталог модели (.rknn + multilingual_vocab.txt) или путь к .rknn'),
        DeclareLaunchArgument(
            'model_file', default_value='',
            description='Имя .rknn внутри model_path (пусто — первая найденная)'),
        DeclareLaunchArgument(
            'vocab_path', default_value='',
            description='Путь к multilingual_vocab.txt (пусто — рядом с .rknn)'),
        DeclareLaunchArgument(
            'rknn_lib', default_value='',
            description='Путь к librknnrt.so (пусто — RKNN_LIB или системная)'),
        DeclareLaunchArgument(
            'audio_topic', default_value='/audio/input',
            description='Топик для подписки на аудио (AudioStamped)'),
        DeclareLaunchArgument(
            'transcription_topic', default_value='/audio/transcription',
            description='Топик результатов распознавания'),
        DeclareLaunchArgument(
            'max_audio_time', default_value='30.0',
            description='Максимальная длительность фразы, с (защита от переполнения)'),
        DeclareLaunchArgument(
            'reliable_audio', default_value='true',
            description='RELIABLE на входе аудио (нужно для /audio/vad: длинные фразы одним сообщением)'),
        Node(
            package='gigaam_ros',
            executable='gigaam_node',
            name='gigaam_node',
            namespace='gigaam',
            parameters=[{
                'model_path': LaunchConfiguration('model_path'),
                'model_file': LaunchConfiguration('model_file'),
                'vocab_path': LaunchConfiguration('vocab_path'),
                'rknn_lib': LaunchConfiguration('rknn_lib'),
                'audio_topic': LaunchConfiguration('audio_topic'),
                'transcription_topic': LaunchConfiguration('transcription_topic'),
                'max_audio_time': LaunchConfiguration('max_audio_time'),
                'reliable_audio': ParameterValue(
                    LaunchConfiguration('reliable_audio'), value_type=bool),
            }],
            output='screen',
        ),
    ])
