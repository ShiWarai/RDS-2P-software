#!/usr/bin/env python3
"""paroli_ros: дефолты из префикса пакета (paroli-cli и vendor/lib)."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    # Все тяжёлые дефолты задаются в tts_node.py через ament_index.
    return LaunchDescription([
        DeclareLaunchArgument(
            'output_topic',
            default_value='/audio/output',
            description='Шина AudioStamped',
        ),
        DeclareLaunchArgument(
            'frame_id',
            default_value='tts.paroli',
            description='header.frame_id',
        ),
        DeclareLaunchArgument(
            'output_sample_rate',
            default_value='44100',
            description='Совпадает с audio.launch.py',
        ),
        DeclareLaunchArgument(
            'chunk_frames',
            default_value='4096',
            description='Кадров mono на сообщение (крупнее → меньше DDS-овых заголовков)',
        ),
        DeclareLaunchArgument(
            'force_stereo',
            default_value='false',
            description='Дублировать mono L=R',
        ),
        DeclareLaunchArgument(
            'use_stdbuf',
            default_value='true',
            description='stdbuf -o0 -i0',
        ),
        DeclareLaunchArgument(
            'length_scale',
            default_value='-1.0',
            description='Piper --length-scale: <1 быстрее, >1 медленнее; -1 = не задавать (дефолт модели)',
        ),
        DeclareLaunchArgument(
            'noise_scale',
            default_value='-1.0',
            description='-1 = не задавать; иначе --noise-scale для paroli-cli',
        ),
        DeclareLaunchArgument(
            'noise_w',
            default_value='-1.0',
            description='-1 = не задавать; иначе --noise-w',
        ),
        DeclareLaunchArgument(
            'tts_volume',
            default_value='1.8',
            description='Усиление голоса: 1.0 без изменений, >1 громче (клип int16), <1 тише',
        ),
        DeclareLaunchArgument(
            'voice_pitch',
            default_value='0.0',
            description='Войсморфинг: высота в полутонах (−12…12), >0 выше, <0 ниже; длительность сохраняется',
        ),
        DeclareLaunchArgument(
            'voice_formant',
            default_value='0.0',
            description='Войсморфинг: форманты в полутонах (−12…12), меняет тембр без смены высоты',
        ),
        DeclareLaunchArgument(
            'voice_tempo',
            default_value='1.0',
            description='Войсморфинг: темп (0.5…2.0), >1 быстрее, <1 медленнее; высота не меняется',
        ),
        Node(
            package='paroli_ros',
            executable='tts_node.py',
            name='paroli_ros',
            output='screen',
            parameters=[{
                'output_topic': LaunchConfiguration('output_topic'),
                'frame_id': LaunchConfiguration('frame_id'),
                'output_sample_rate': ParameterValue(
                    LaunchConfiguration('output_sample_rate'), value_type=int),
                'chunk_frames': ParameterValue(
                    LaunchConfiguration('chunk_frames'), value_type=int),
                'force_stereo': ParameterValue(
                    LaunchConfiguration('force_stereo'), value_type=bool),
                'use_stdbuf': ParameterValue(
                    LaunchConfiguration('use_stdbuf'), value_type=bool),
                'length_scale': ParameterValue(
                    LaunchConfiguration('length_scale'), value_type=float),
                'noise_scale': ParameterValue(
                    LaunchConfiguration('noise_scale'), value_type=float),
                'noise_w': ParameterValue(
                    LaunchConfiguration('noise_w'), value_type=float),
                'tts_volume': ParameterValue(
                    LaunchConfiguration('tts_volume'), value_type=float),
                'voice_pitch': ParameterValue(
                    LaunchConfiguration('voice_pitch'), value_type=float),
                'voice_formant': ParameterValue(
                    LaunchConfiguration('voice_formant'), value_type=float),
                'voice_tempo': ParameterValue(
                    LaunchConfiguration('voice_tempo'), value_type=float),
            }],
        ),
    ])
