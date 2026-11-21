#!/usr/bin/env python3
"""Launch RNNoise AudioStamped filter: `/audio/input` -> `/audio/input/clean`."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    args = [
        DeclareLaunchArgument(
            "input_topic",
            default_value="/audio/input",
            description="Source AudioStamped (raw microphone)",
        ),
        DeclareLaunchArgument(
            "output_topic",
            default_value="/audio/input/clean",
            description="Filtered AudioStamped for STT/consumers",
        ),
        DeclareLaunchArgument(
            "qos_depth",
            default_value="50",
            description="Subscriber HISTORY depth",
        ),
        DeclareLaunchArgument(
            "output_chunk_frames",
            default_value="1024",
            description="Publish chunk length (mono samples) unless input audio.info.chunk is set",
        ),
        DeclareLaunchArgument(
            "preserve_input_format_for_output",
            default_value="true",
            description="Match int16/float32 AudioStamped output to input codec when supported",
        ),
        DeclareLaunchArgument(
            "node_name",
            default_value="audio_rnnoise",
            description="ROS node name",
        ),
    ]

    node = Node(
        package="audio_filters",
        executable="audio_rnnoise_node",
        name=LaunchConfiguration("node_name"),
        output="screen",
        parameters=[
            {
                "input_topic": LaunchConfiguration("input_topic"),
                "output_topic": LaunchConfiguration("output_topic"),
                "qos_depth": ParameterValue(
                    LaunchConfiguration("qos_depth"),
                    value_type=int,
                ),
                "output_chunk_frames": ParameterValue(
                    LaunchConfiguration("output_chunk_frames"),
                    value_type=int,
                ),
                "preserve_input_format_for_output": ParameterValue(
                    LaunchConfiguration(
                        "preserve_input_format_for_output"
                    ),
                    value_type=bool,
                ),
            }
        ],
    )

    return LaunchDescription(args + [node])
