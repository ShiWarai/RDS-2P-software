# MIT License
#
# Copyright (c) 2024
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_nodes(context):
    """Генерирует узлы с правильными типами параметров."""
    # Получаем значения параметров и преобразуем в числа
    capturer_device = int(context.launch_configurations['capturer_device'])
    capturer_rate = int(context.launch_configurations['capturer_rate'])
    capturer_channels = int(context.launch_configurations['capturer_channels'])
    capturer_format = int(context.launch_configurations['capturer_format'])
    capturer_chunk = int(context.launch_configurations['capturer_chunk'])
    capturer_topic = context.launch_configurations['capturer_topic']
    
    player_device = int(context.launch_configurations['player_device'])
    player_topic = context.launch_configurations['player_topic']
    
    # Узел захвата аудио
    audio_capturer_node = Node(
        package='audio_common',
        executable='audio_capturer_node',
        name='audio_capturer',
        parameters=[{
            'device': capturer_device,
            'rate': capturer_rate,
            'channels': capturer_channels,
            'format': capturer_format,
            'chunk': capturer_chunk,
        }],
        remappings=[
            ('audio', capturer_topic),
        ],
        output='screen'
    )

    # Узел воспроизведения аудио
    audio_player_node = Node(
        package='audio_common',
        executable='audio_player_node',
        name='audio_player',
        parameters=[{
            'device': player_device,
        }],
        remappings=[
            ('audio', player_topic),
        ],
        output='screen'
    )
    
    return [audio_capturer_node, audio_player_node]


def generate_launch_description():
    """Генерирует описание запуска для узлов audio_common."""

    # Аргументы запуска для audio_capturer_node
    capturer_device_arg = DeclareLaunchArgument(
        'capturer_device',
        default_value='7',
        description='Индекс устройства для захвата аудио (микрофон)'
    )

    capturer_rate_arg = DeclareLaunchArgument(
        'capturer_rate',
        default_value='48000',
        description='Частота дискретизации для захвата аудио в Гц'
    )

    capturer_channels_arg = DeclareLaunchArgument(
        'capturer_channels',
        default_value='1',
        description='Количество каналов для захвата (1 для моно, 2 для стерео)'
    )

    capturer_format_arg = DeclareLaunchArgument(
        'capturer_format',
        default_value='8',
        description='Формат аудио для захвата (8 = paInt16)'
    )

    capturer_chunk_arg = DeclareLaunchArgument(
        'capturer_chunk',
        default_value='512',
        description='Размер чанка аудио данных (буфер). Для WSL2 рекомендуется 4096'
    )

    capturer_topic_arg = DeclareLaunchArgument(
        'capturer_topic',
        default_value='/audio/input',
        description='Имя топика для публикации захваченного аудио'
    )

    # Аргументы запуска для audio_player_node
    player_device_arg = DeclareLaunchArgument(
        'player_device',
        default_value='2',
        description='Индекс устройства для воспроизведения аудио (динамик)'
    )

    player_topic_arg = DeclareLaunchArgument(
        'player_topic',
        default_value='/audio/output',
        description='Имя топика для подписки на аудио для воспроизведения'
    )

    return LaunchDescription([
        capturer_device_arg,
        capturer_rate_arg,
        capturer_channels_arg,
        capturer_format_arg,
        capturer_chunk_arg,
        capturer_topic_arg,
        player_device_arg,
        player_topic_arg,
        OpaqueFunction(function=generate_nodes),
    ])

