#!/usr/bin/env python3
"""paroli_ros2: дефолты из префикса пакета (paroli-cli и vendor/lib)."""

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
        Node(
            package='paroli_ros2',
            executable='tts_node.py',
            name='paroli_ros2',
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
            }],
        ),
    ])
