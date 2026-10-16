#!/usr/bin/env python3
"""Аудио для RDS-2P: ``audio_player`` (микшер → динамик) + опционально ``audio_capturer``.

Порядок нод: сначала плеер, затем захват (частично снижает конфликты ALSA/PortAudio).

Единственный launch-файл пакета для звука; мета-сборки (дисплей, vosk, paroli) — в ``rds_2p``,
см. ``voice_system.launch.py``.
"""

from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _as_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _opaque_audio_nodes(context, *_args, **_kwargs):
    enable_capturer = _as_bool(context.launch_configurations.get("enable_capturer", "true"))
    capturer_respawn = _as_bool(context.launch_configurations.get("capturer_respawn", "true"))

    audio_player_node = Node(
        package="rds_2p_audio",
        executable="audio_player_node.py",
        name="audio_player",
        output="screen",
        parameters=[{
            "topic": LaunchConfiguration("output_topic"),
            "device": ParameterValue(LaunchConfiguration("output_device"), value_type=int),
            "pulse_sink": LaunchConfiguration("pulse_sink"),
            "channels": ParameterValue(LaunchConfiguration("output_channels"), value_type=int),
            "output_sample_rate": ParameterValue(
                LaunchConfiguration("output_sample_rate"), value_type=int
            ),
            "mix_period_ms": ParameterValue(LaunchConfiguration("mix_period_ms"), value_type=float),
            "source_evict_sec": ParameterValue(
                LaunchConfiguration("source_evict_sec"), value_type=float
            ),
            "qos_depth": ParameterValue(LaunchConfiguration("qos_depth"), value_type=int),
        }],
        emulate_tty=True,
    )

    if not enable_capturer:
        return [audio_player_node]

    capturer_node = Node(
        package="audio_common",
        executable="audio_capturer_node",
        name="audio_capturer",
        parameters=[{
            "device": int(context.launch_configurations["capturer_device"]),
            "rate": int(context.launch_configurations["capturer_rate"]),
            "channels": int(context.launch_configurations["capturer_channels"]),
            "format": int(context.launch_configurations["capturer_format"]),
            "chunk": int(context.launch_configurations["capturer_chunk"]),
        }],
        remappings=[("audio", context.launch_configurations["capturer_topic"])],
        output="screen",
        respawn=capturer_respawn,
        respawn_delay=1.0,
    )

    return [audio_player_node, capturer_node]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "output_topic",
            default_value="/audio/output",
            description="Шина воспроизведения AudioStamped (контрактный frame_id + rate)",
        ),
        DeclareLaunchArgument(
            "output_device",
            default_value="-1",
            description="PortAudio индекс выхода (−1 = default ALSA)",
        ),
        DeclareLaunchArgument(
            "pulse_sink",
            default_value="alsa_output.platform-es8388-sound.stereo-fallback",
            description=(
                "Имя sink PulseAudio для переменной PULSE_SINK у audio_player (встроенный ES8388 на Orange Pi "
                "RDS); пустая строка — не трогать окружение"
            ),
        ),
        DeclareLaunchArgument(
            "output_channels",
            default_value="1",
            description="Каналы динамика",
        ),
        DeclareLaunchArgument(
            "output_sample_rate",
            default_value="44100",
            description="Должен совпадать с полем audio.info.rate у входящего потока",
        ),
        DeclareLaunchArgument(
            "mix_period_ms",
            default_value="20.0",
            description="Шаг смешения одного блока миллисекунд для микшера",
        ),
        DeclareLaunchArgument(
            "source_evict_sec",
            default_value="5.0",
            description="Удалять источник frame_id если нет новых сообщений дольше (с)",
        ),
        DeclareLaunchArgument(
            "qos_depth",
            default_value="50",
            description="Очередь ROS подписчика /audio/output",
        ),
        DeclareLaunchArgument(
            "enable_capturer",
            default_value="true",
            description="false — только воспроизведение без микрофона",
        ),
        DeclareLaunchArgument(
            "capturer_device",
            default_value="-1",
            description="Индекс PortAudio микрофона (−1 = default input; список: python3 -m sounddevice)",
        ),
        DeclareLaunchArgument(
            "capturer_rate",
            default_value="44100",
            description="Частота захвата (встроенный ES8388 через Pulse по умолчанию 44100 Hz)",
        ),
        DeclareLaunchArgument(
            "capturer_channels",
            default_value="1",
            description="Каналы микрофона (безопасный дефолт для большинства USB/board mic — mono)",
        ),
        DeclareLaunchArgument(
            "capturer_format",
            default_value="8",
            description="PortAudio кодек (8=int16 для audio_common по умолчанию)",
        ),
        DeclareLaunchArgument(
            "capturer_chunk",
            default_value="1024",
            description="Размер чанка на одно сообщение AudioStamped входа микрофона",
        ),
        DeclareLaunchArgument(
            "capturer_topic",
            default_value="/audio/input",
            description="Выход топика аудиопоточного микрофона",
        ),
        DeclareLaunchArgument(
            "capturer_respawn",
            default_value="true",
            description="перезапускать audio_capturer при падении",
        ),
        OpaqueFunction(function=_opaque_audio_nodes),
    ])
