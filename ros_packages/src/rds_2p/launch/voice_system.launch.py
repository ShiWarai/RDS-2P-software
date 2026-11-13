#!/usr/bin/env python3
"""Голосовой контур робота: аудио (``rds_2p_audio``) + STT + Paroli + липсинк лица.

1. ``rds_2p_audio/launch/audio.launch.py`` — сначала плеер, затем микрофон.
2. Затем без задержек: выбранный STT (``stt:=vosk`` или ``stt:=gigaam``),
   ``paroli_ros``, ``rds_2p_face/lip_sync_face.launch.py``.

Так можно обойтись без ``TimerAction``. Это **не** то же самое, что ожидание «готовности» по ROS
(topic/service): при ``IncludeLaunchDescription`` на звук родитель не видит ``Node``
``audio_player``, поэтому :class:`~launch.event_handlers.OnProcessStart` здесь не используется.
Если на железе снова понадобятся паузы — поднимайте часть узлов отдельным launch или добавьте
обратно таймеры в этот файл.

LLM (``rkllm_ros``, ``system_one``, ``llm_layer``) в этот launch не входит: только аудио,
распознавание, синтез и липсинк. Для команд без LLM используйте ``rds_2p_commands``.

Полный набор параметров звука: ``ros2 launch rds_2p_audio audio.launch.py --show-args``.
Липсинк слушает тот же ``output_topic``, что и Paroli; ``audio_frame_id`` совпадает с ``paroli_frame_id``.
"""

from __future__ import annotations

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
)
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

    stt = context.launch_configurations.get("stt", "vosk").strip().lower()
    if stt not in ("vosk", "gigaam"):
        raise RuntimeError(
            f"Неизвестный STT backend: {stt!r}; допустимо: vosk, gigaam")

    stt_extras = []
    if stt == "vosk":
        stt_ld_args = {
            "audio_topic": LaunchConfiguration("vosk_audio_topic"),
            "transcription_topic": LaunchConfiguration("vosk_transcription_topic"),
        }
        vosk_model = context.launch_configurations.get("vosk_model_path", "").strip()
        if vosk_model:
            stt_ld_args["model_path"] = LaunchConfiguration("vosk_model_path")
        stt_ld = IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare("vosk_ros"),
                    "launch",
                    "vosk.launch.py",
                ]),
            ]),
            launch_arguments=stt_ld_args.items(),
        )
    else:
        # GigaAM не потоковый → перед ним VAD-шлюз; опционально RNNoise-шумодав.
        denoise = context.launch_configurations.get("denoise", "rnnoise").strip().lower()
        vad_input = LaunchConfiguration("capturer_topic")
        if denoise == "rnnoise":
            rnnoise_inc = GroupAction(
                actions=[
                    IncludeLaunchDescription(
                        PythonLaunchDescriptionSource([
                            PathJoinSubstitution([
                                FindPackageShare("audio_filters"),
                                "launch",
                                "rnnoise_filter.launch.py",
                            ]),
                        ]),
                        launch_arguments={
                            "input_topic": LaunchConfiguration("capturer_topic"),
                            "output_topic": "/audio/input/clean",
                        }.items(),
                    ),
                ],
                scoped=True,
            )
            stt_extras.append(rnnoise_inc)
            vad_input = "/audio/input/clean"
        vad_inc = GroupAction(
            actions=[
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource([
                        PathJoinSubstitution([
                            FindPackageShare("gigaam_ros"),
                            "launch",
                            "vad.launch.py",
                        ]),
                    ]),
                    launch_arguments={
                        "audio_topic": vad_input,
                        "output_topic": "/audio/vad",
                        "min_silence_duration": LaunchConfiguration("vad_min_silence_duration"),
                        "hangover_sec": LaunchConfiguration("vad_hangover_sec"),
                        "max_segment_sec": LaunchConfiguration("vad_max_segment_sec"),
                        "preroll_sec": LaunchConfiguration("vad_preroll_sec"),
                        "threshold": LaunchConfiguration("vad_threshold"),
                    }.items(),
                ),
            ],
            scoped=True,
        )
        stt_extras.append(vad_inc)
        stt_ld_args = {
            "audio_topic": "/audio/vad",
            "transcription_topic": LaunchConfiguration("vosk_transcription_topic"),
            # VAD отдаёт длинные фразы одним сообщением по RELIABLE (/audio/vad).
            "reliable_audio": "true",
        }
        gigaam_model = context.launch_configurations.get("gigaam_model_path", "").strip()
        if gigaam_model:
            stt_ld_args["model_path"] = LaunchConfiguration("gigaam_model_path")
        stt_ld = IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare("gigaam_ros"),
                    "launch",
                    "gigaam.launch.py",
                ]),
            ]),
            launch_arguments=stt_ld_args.items(),
        )

    paroli_ld = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare("paroli_ros"),
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

    return [audio_inc] + stt_extras + [stt_ld, paroli_ld, lip_sync_ld]


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
                description="Проброс в audio / STT / paroli",
            ),
            DeclareLaunchArgument(
                "capturer_rate",
                default_value="44100",
                description="Проброс в audio.launch",
            ),
            DeclareLaunchArgument(
                "capturer_channels",
                default_value="1",
                description="Проброс в audio.launch и STT",
            ),
            DeclareLaunchArgument(
                "capturer_device",
                default_value="-1",
                description="Индекс PortAudio микрофона (−1 = default input; список: python3 -m sounddevice)",
            ),
            DeclareLaunchArgument(
                "stt",
                default_value="vosk",
                description="STT backend: vosk (CPU) или gigaam (RKNN NPU)",
            ),
            DeclareLaunchArgument(
                "denoise",
                default_value="none",
                description="Шумодав перед VAD (только gigaam): none / rnnoise. "
                            "rnnoise вырезает тихую речь и снижает дальность — для дальности none",
            ),
            DeclareLaunchArgument(
                "gigaam_model_path",
                default_value="",
                description="Только для stt:=gigaam; пусто — дефолт из share gigaam_ros",
            ),
            DeclareLaunchArgument(
                "gigaam_reliable_audio",
                default_value="true",
                description="Устарел: gigaam всегда слушает /audio/vad по RELIABLE (VAD добавляется автоматически)",
            ),
            DeclareLaunchArgument(
                "vad_min_silence_duration",
                default_value="0.6",
                description="Пауза (с), завершающая фразу. Больше — не режет речь по заминкам "
                            "и ждёт конца реплики; меньше — быстрее отдаёт, но рвёт фразы",
            ),
            DeclareLaunchArgument(
                "vad_hangover_sec",
                default_value="2.0",
                description="Хвост тишины (с), добавляемый к фразе перед распознаванием",
            ),
            DeclareLaunchArgument(
                "vad_max_segment_sec",
                default_value="15.0",
                description="Максимальная длина фразы (с) до принудительной отдачи",
            ),
            DeclareLaunchArgument(
                "vad_preroll_sec",
                default_value="0.5",
                description="Буфер (с) до старта речи: больше — не проглатывает начало слов",
            ),
            DeclareLaunchArgument(
                "vad_threshold",
                default_value="0.5",
                description="Порог вероятности речи VAD: ниже — раньше стартует, но больше ложных",
            ),
            DeclareLaunchArgument(
                "vosk_audio_topic",
                default_value="/audio/input",
                description="Топик для выбранного STT (= capturer_topic по умолчанию)",
            ),
            DeclareLaunchArgument(
                "vosk_transcription_topic",
                default_value="/audio/transcription",
                description="Выход выбранного STT",
            ),
            DeclareLaunchArgument(
                "vosk_model_path",
                default_value="",
                description="Только для stt:=vosk; пусто — дефолт из share vosk_ros",
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
