#!/usr/bin/env python3
"""LLM-прослойка: микрофон → VAD → vosk → классификатор system-one → команда | разговор (rkllm+Paroli).

Состав:
- ``vosk_ros2 vad.launch.py`` — VAD-шлюз (Silero VAD, CPU): в vosk идут только фразы речи.
  **По умолчанию выключен** (``vad_enabled:=false`` — vosk слушает микрофон напрямую; у ES8388
  слабый SNR и гейтинг там не спасает). Включение: ``vad_enabled:=true vosk_audio_topic:=/audio/vad``.
- ``rds_2p voice_system.launch.py`` — audio (микрофон/плеер) + vosk + Paroli + lip_sync («рот»);
  выключается ``include_voice:=false`` (например, для отладки текстом).
- ``rkllm_ros2 rkllm.launch.py`` — LLM (по умолчанию Qwen3.5-2B из ~/models).
- ``rkllm_ros2 system_one.launch.py`` — HTTP-обёртка system-one-rknn (kev-0.8b).
- ``rds_2p_commands llm_layer`` — маршрутизация: команда → ``/audio/command_transcription``,
  разговор → rkllm ChatCompletion + озвучка Paroli; «посмотри …» → кадр камеры + текст
  (мультимодально); ``llm_system_prompt`` добавляется в начало запроса к LLM.

Контейнер system-one-rknn должен быть поднят заранее::

    ros2 run rkllm_ros2 system_one_docker.sh run

Командная система тут НЕ запускается (запускайте отдельно и кормите её тем же топиком)::

    ros2 launch rds_2p_commands commands_system.launch.py \
      transcription_topics:="['/audio/command_transcription']"
"""

import json

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

SYSTEM_PROMPT = (
    'Ты робот-панда, отвечай на вопросы гостей. '
    'На вопросы отвечай кратко. '
    'Не придумывай точную информацию. '
    'У тебя есть зрение с помощью камеры, фото с которой будет передаваться '
    'при надобности тебе.'
)

CLASSIFIER_JSON = json.dumps({
    'instructions': 'Выбери команду робота, которой соответствует текст.',
    'criteria': {
        'dismiss': 'отставить, встань, вставай, отбой',
        'lie_down': 'лежать, ложись, ляг',
        'stand_at_attention': 'равняйся, выровняйся, равняйсь',
        'unknown': (
            'не команда: вопрос, болтовня, похвала; отрицание или сомнение '
            '(не лежать, не беги, не давай лапу)'
        ),
    },
    'actions': {
        'dismiss': 'вставай',
        'lie_down': 'ложись',
        'stand_at_attention': 'равняйсь',
    },
    'say': {
        'dismiss': 'Встаю!',
        'lie_down': 'Ложусь!',
        'stand_at_attention': 'Равняюсь!',
    },
}, ensure_ascii=False)


def generate_launch_description():
    args = [
        DeclareLaunchArgument(
            'include_voice', default_value='true',
            description='Поднимать voice_system (audio+vosk+Paroli+lip_sync)',
        ),
        DeclareLaunchArgument(
            'encoder_model_path',
            default_value='/home/orangepi/models/qwen3.5-2b-rkllm-rk3588/qwen3.5-2b_vision_rk3588.rknn',
            description='Vision encoder (.rknn) для rkllm_ros2',
        ),
        DeclareLaunchArgument(
            'llm_model_path',
            default_value='/home/orangepi/models/qwen3.5-2b-rkllm-rk3588/qwen3.5-2b_w8a8_rk3588.rkllm',
            description='LLM (.rkllm) для rkllm_ros2',
        ),
        DeclareLaunchArgument(
            'rkllm_max_new_tokens', default_value='512',
            description='Лимит генерации ответа в диалоге',
        ),
        DeclareLaunchArgument(
            'system_one_url', default_value='http://127.0.0.1:8080',
            description='HTTP API контейнера system-one-rknn',
        ),
        DeclareLaunchArgument(
            'input_topic', default_value='/audio/transcription',
            description='Топик vosk_ros2/Transcription (вход прослойки)',
        ),
        DeclareLaunchArgument(
            'command_topic', default_value='/audio/command_transcription',
            description='Топик vosk_ros2/Transcription с канонической фразой команды',
        ),
        DeclareLaunchArgument(
            'classifier_json', default_value=CLASSIFIER_JSON,
            description='Критерии choice-классификатора (instructions/criteria/actions)',
        ),
        DeclareLaunchArgument('min_confidence', default_value='0.0',
                              description='Порог уверенности для ветки команды (0 = выкл)'),
        DeclareLaunchArgument(
            'announce_commands', default_value='true',
            description='Голосом объявлять команду перед отправкой (classifier_json.say)',
        ),
        DeclareLaunchArgument(
            'post_speech_cooldown_sec', default_value='2.5',
            description='Окно после озвучки, в котором транскрипции игнорируются '
                        '(гасит самоэхо: мик+vosk отдают его через ~1.5–2 с)',
        ),
        DeclareLaunchArgument(
            'vad_enabled', default_value='false',
            description='VAD-шлюз vosk_ros2 (mic → только речь → /audio/vad → vosk); по умолчанию выключен',
        ),
        DeclareLaunchArgument(
            'vosk_audio_topic', default_value='/audio/input',
            description='Топик аудио для vosk; при vad_enabled:=true поставьте /audio/vad',
        ),
        DeclareLaunchArgument(
            'capturer_device', default_value='-1',
            description='Индекс PortAudio микрофона (−1 = default input; список: python3 -m sounddevice)',
        ),
        DeclareLaunchArgument(
            'llm_system_prompt', default_value=SYSTEM_PROMPT,
            description='System-строка в начало user_message диалогов и «посмотри»',
        ),
        DeclareLaunchArgument(
            'camera_topic', default_value='/camera/color/image_raw',
            description='Кадр камеры для команды «посмотри» (multimodal)',
        ),
    ]

    vad = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('vosk_ros2'), 'launch', 'vad.launch.py',
            ]),
        ),
        condition=IfCondition(PythonExpression(
            ['"', LaunchConfiguration('include_voice'), '" == "true" and "',
             LaunchConfiguration('vad_enabled'), '" == "true"'])),
    )

    voice = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('rds_2p'), 'launch', 'voice_system.launch.py',
            ]),
        ),
        launch_arguments={
            'vosk_audio_topic': LaunchConfiguration('vosk_audio_topic'),
            'capturer_device': LaunchConfiguration('capturer_device'),
        }.items(),
        condition=IfCondition(LaunchConfiguration('include_voice')),
    )

    rkllm = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('rkllm_ros2'), 'launch', 'rkllm.launch.py',
            ]),
        ),
        launch_arguments={
            'encoder_model_path': LaunchConfiguration('encoder_model_path'),
            'llm_model_path': LaunchConfiguration('llm_model_path'),
            'max_new_tokens': LaunchConfiguration('rkllm_max_new_tokens'),
        }.items(),
    )

    system_one = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('rkllm_ros2'), 'launch', 'system_one.launch.py',
            ]),
        ),
        launch_arguments={
            'server_url': LaunchConfiguration('system_one_url'),
        }.items(),
    )

    llm_layer_node = Node(
        package='rds_2p_commands',
        executable='llm_layer',
        name='llm_layer',
        output='screen',
        parameters=[{
            'input_topic': LaunchConfiguration('input_topic'),
            'command_topic': LaunchConfiguration('command_topic'),
            'classifier_json': ParameterValue(
                LaunchConfiguration('classifier_json'), value_type=str),
            'min_confidence': ParameterValue(
                LaunchConfiguration('min_confidence'), value_type=float),
            'announce_commands': ParameterValue(
                LaunchConfiguration('announce_commands'), value_type=bool),
            'post_speech_cooldown_sec': ParameterValue(
                LaunchConfiguration('post_speech_cooldown_sec'), value_type=float),
            'llm_system_prompt': ParameterValue(
                LaunchConfiguration('llm_system_prompt'), value_type=str),
            'camera_topic': LaunchConfiguration('camera_topic'),
        }],
    )

    return LaunchDescription(args + [vad, voice, rkllm, system_one, llm_layer_node])