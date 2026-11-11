#!/usr/bin/env python3
"""Запуск VAD-шлюза gigaam_ros/vad_node: микрофон → только речь → распознавание.

Примеры:

  ros2 launch gigaam_ros vad.launch.py
  ros2 launch gigaam_ros vad.launch.py backend:=npu vad_rknn_path:=/path/silero_vad.rknn
  ros2 launch gigaam_ros gigaam.launch.py audio_topic:=/audio/vad

backend=cpu (по умолчанию) — Silero VAD v4 через sherpa-onnx, модель по умолчанию
share/gigaam_ros/models/silero_vad.onnx. backend=npu — Silero VAD .rknn по NPU
(экспериментально, требует vad_rknn_path).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('audio_topic', default_value='/audio/input',
                              description='Вход: AudioStamped с микрофона'),
        DeclareLaunchArgument('output_topic', default_value='/audio/vad',
                              description='Выход: AudioStamped только с речью'),
        DeclareLaunchArgument('backend', default_value='cpu',
                              description='VAD backend: cpu (sherpa-onnx) или npu (rknn)'),
        DeclareLaunchArgument('vad_model_path', default_value='',
                              description='cpu: путь к silero_vad.onnx (пусто — share/models)'),
        DeclareLaunchArgument('vad_rknn_path', default_value='',
                              description='npu: путь к silero_vad.rknn'),
        DeclareLaunchArgument('rknn_lib', default_value='',
                              description='npu: путь к librknnrt.so'),
        DeclareLaunchArgument('threshold', default_value='0.5',
                              description='Порог вероятности речи VAD'),
        DeclareLaunchArgument('min_speech_duration', default_value='0.15',
                              description='Минимальная длительность речи, с'),
        DeclareLaunchArgument('min_silence_duration', default_value='0.25',
                              description='Минимальная пауза для «конца» речи, с'),
        DeclareLaunchArgument('preroll_sec', default_value='0.3',
                              description='Пред-ролл перед началом речи, с'),
        DeclareLaunchArgument('hangover_sec', default_value='2.0',
                              description='Хвост тишины после фразы, с'),
        DeclareLaunchArgument('max_segment_sec', default_value='15.0',
                              description='Максимальная длина фразы до принудительной отдачи, с'),
        DeclareLaunchArgument('output_reliable', default_value='true',
                              description='RELIABLE на /audio/vad (длинные фразы одним сообщением)'),
        Node(
            package='gigaam_ros',
            executable='vad_node',
            name='vad_node',
            output='screen',
            parameters=[{
                'audio_topic': LaunchConfiguration('audio_topic'),
                'output_topic': LaunchConfiguration('output_topic'),
                'backend': LaunchConfiguration('backend'),
                'vad_model_path': LaunchConfiguration('vad_model_path'),
                'vad_rknn_path': LaunchConfiguration('vad_rknn_path'),
                'rknn_lib': LaunchConfiguration('rknn_lib'),
                'threshold': ParameterValue(
                    LaunchConfiguration('threshold'), value_type=float),
                'min_speech_duration': ParameterValue(
                    LaunchConfiguration('min_speech_duration'), value_type=float),
                'min_silence_duration': ParameterValue(
                    LaunchConfiguration('min_silence_duration'), value_type=float),
                'preroll_sec': ParameterValue(
                    LaunchConfiguration('preroll_sec'), value_type=float),
                'hangover_sec': ParameterValue(
                    LaunchConfiguration('hangover_sec'), value_type=float),
                'max_segment_sec': ParameterValue(
                    LaunchConfiguration('max_segment_sec'), value_type=float),
                'output_reliable': ParameterValue(
                    LaunchConfiguration('output_reliable'), value_type=bool),
            }],
        ),
    ])
