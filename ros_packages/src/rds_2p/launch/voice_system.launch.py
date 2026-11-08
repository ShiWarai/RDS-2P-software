#!/usr/bin/env python3
"""Голосовой контур робота: аудио (``rds_2p_audio``) + Vosk + Paroli + липсинк лица.

1. ``rds_2p_audio/launch/audio.launch.py`` — сначала плеер, затем микрофон.
2. Затем без задержек: ``vosk_ros2``, ``paroli_ros2``, ``rds_2p_face/lip_sync_face.launch.py``.

Так можно обойтись без ``TimerAction``. Это **не** то же самое, что ожидание «готовности» по ROS
(topic/service): при ``IncludeLaunchDescription`` на звук родитель не видит ``Node``
``audio_player``, поэтому :class:`~launch.event_handlers.OnProcessStart` здесь не используется.
Если на железе снова понадобятся паузы — поднимайте часть узлов отдельным launch или добавьте
обратно таймеры в этот файл.

Полный набор параметров звука: ``ros2 launch rds_2p_audio audio.launch.py --show-args``.
Липсинк слушает тот же ``output_topic``, что и Paroli; ``audio_frame_id`` совпадает с ``paroli_frame_id``.
"""

from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def _setup(context, *_args, **_kwargs):
    passthrough_audio = {
        "output_topic": LaunchConfiguration("output_topic"),
        "capturer_topic": LaunchConfiguration("capturer_topic"),
        "pulse_sink": LaunchConfiguration("pulse_sink"),
        "enable_capturer": LaunchConfiguration("enable_capturer"),
        "output_sample_rate": LaunchConfiguration("output_sample_rate"),
        "capturer_rate": LaunchConfiguration("capturer_rate"),
        "capturer_channels": LaunchConfiguration("capturer_channels"),
        "capturer_device": LaunchConfiguration("capturer_device"),
    }

    audio_inc = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare("rds_2p_audio"),
                "launch",
                "audio.launch.py",
            ]),
        ]),
        launch_arguments=passthrough_audio.items(),
    )

    vosk_ld_args = {
        "audio_topic": LaunchConfiguration("vosk_audio_topic"),
        "transcription_topic": LaunchConfiguration("vosk_transcription_topic"),
        "default_sample_rate": LaunchConfiguration("output_sample_rate"),
        "default_channels": LaunchConfiguration("capturer_channels"),
    }
    vosk_model = context.launch_configurations.get("vosk_model_path", "").strip()
    if vosk_model:
        vosk_ld_args["model_path"] = LaunchConfiguration("vosk_model_path")

    vosk_ld = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare("vosk_ros2"),
                "launch",
                "vosk.launch.py",
            ]),
        ]),
        launch_arguments=vosk_ld_args.items(),
    )

    paroli_ld = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare("paroli_ros2"),
                "launch",
                "tts.launch.py",
            ]),
        ]),
        launch_arguments={
            "output_topic": LaunchConfiguration("output_topic"),
            "output_sample_rate": LaunchConfiguration("output_sample_rate"),
            "frame_id": LaunchConfiguration("paroli_frame_id"),
        }.items(),
    )

    lip_sync_ld = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare("rds_2p_face"),
                "launch",
                "lip_sync_face.launch.py",
            ]),
        ]),
        launch_arguments={
            "audio_topic": LaunchConfiguration("output_topic"),
            "audio_frame_id": LaunchConfiguration("paroli_frame_id"),
            "face_topic": LaunchConfiguration("lip_sync_face_topic"),
            "manifest_path": LaunchConfiguration("lip_sync_manifest_path"),
            "max_face_hz": LaunchConfiguration("lip_sync_max_face_hz"),
        }.items(),
    )

    return [audio_inc, vosk_ld, paroli_ld, lip_sync_ld]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "output_topic",
                default_value="/audio/output",
                description="Проброс в audio.launch + Paroli",
            ),
            DeclareLaunchArgument(
                "capturer_topic",
                default_value="/audio/input",
                description="Проброс в audio.launch; согласуйте с vosk_audio_topic",
            ),
            DeclareLaunchArgument(
                "pulse_sink",
                default_value="alsa_output.platform-es8388-sound.stereo-fallback",
                description="Проброс в audio.launch",
            ),
            DeclareLaunchArgument(
                "enable_capturer",
                default_value="true",
                description="Проброс в audio.launch",
            ),
            DeclareLaunchArgument(
                "output_sample_rate",
                default_value="44100",
                description="Проброс в audio / vosk / paroli",
            ),
            DeclareLaunchArgument(
                "capturer_rate",
                default_value="44100",
                description="Проброс в audio.launch",
            ),
            DeclareLaunchArgument(
                "capturer_channels",
                default_value="1",
                description="Проброс в audio.launch и vosk default_channels",
            ),
            DeclareLaunchArgument(
                "capturer_device",
                default_value="-1",
                description="Индекс PortAudio микрофона (−1 = default input; список: python3 -m sounddevice)",
            ),
            DeclareLaunchArgument(
                "vosk_audio_topic",
                default_value="/audio/input",
                description="Топик для vosk (= capturer_topic по умолчанию)",
            ),
            DeclareLaunchArgument(
                "vosk_transcription_topic",
                default_value="/audio/transcription",
                description="Выход vosk",
            ),
            DeclareLaunchArgument(
                "vosk_model_path",
                default_value="",
                description="Пусто — дефолт из share vosk_ros2",
            ),
            DeclareLaunchArgument(
                "paroli_frame_id",
                default_value="tts.paroli",
                description="Paroli header.frame_id",
            ),
            DeclareLaunchArgument(
                "lip_sync_face_topic",
                default_value="/face/image",
                description="Выход lip_sync_face (sensor_msgs/Image для display_face)",
            ),
            DeclareLaunchArgument(
                "lip_sync_manifest_path",
                default_value="",
                description="Пусто — дефолтный manifest из share rds_2p_face",
            ),
            DeclareLaunchArgument(
                "lip_sync_max_face_hz",
                default_value="24.0",
                description="Макс. частота кадров лица у lip_sync_face",
            ),
        ]
        + [OpaqueFunction(function=_setup)]
    )
