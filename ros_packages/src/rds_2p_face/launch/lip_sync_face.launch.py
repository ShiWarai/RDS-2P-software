#!/usr/bin/env python3
"""Запуск lip_sync_face_node: аудио шина → выбор PNG по RMS → /face/image.

Внимание: одновременная публикация с тачпад-пайплайном в тот же /face/image без композитора
даёт конфликт — см. README пакета rds_2p_face, секция lip_sync_face.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    log_level_arg = DeclareLaunchArgument(
        "log_level",
        default_value="info",
        description="Уровень логирования ноды",
    )
    audio_topic_arg = DeclareLaunchArgument(
        "audio_topic",
        default_value="/audio/output",
        description="Топик AudioStamped (шина воспроизведения)",
    )
    audio_frame_id_arg = DeclareLaunchArgument(
        "audio_frame_id",
        default_value="tts.paroli",
        description="Фильтр header.frame_id (пустая строка — все источники)",
    )
    face_topic_arg = DeclareLaunchArgument(
        "face_topic",
        default_value="/face/image",
        description="Выход sensor_msgs/Image rgb8 для display_face",
    )
    manifest_path_arg = DeclareLaunchArgument(
        "manifest_path",
        default_value="",
        description="Путь к lip_sync_manifest.json; пусто — share/rds_2p_face/config/lip_sync_manifest.json",
    )
    max_face_hz_arg = DeclareLaunchArgument(
        "max_face_hz",
        default_value="24.0",
        description="Максимальная частота публикации кадра лица",
    )

    node = Node(
        package="rds_2p_face",
        executable="lip_sync_face_node.py",
        name="lip_sync_face",
        output="screen",
        parameters=[
            {"audio_topic": LaunchConfiguration("audio_topic")},
            {"audio_frame_id": LaunchConfiguration("audio_frame_id")},
            {"face_topic": LaunchConfiguration("face_topic")},
            {"manifest_path": LaunchConfiguration("manifest_path")},
            {"max_face_hz": LaunchConfiguration("max_face_hz")},
        ],
        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
    )

    return LaunchDescription(
        [
            log_level_arg,
            audio_topic_arg,
            audio_frame_id_arg,
            face_topic_arg,
            manifest_path_arg,
            max_face_hz_arg,
            node,
        ]
    )
