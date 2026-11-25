#!/usr/bin/env python3
"""Launch gain on AudioStamped: input_topic -> output_topic (same format, amplified)."""

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
            description="Source AudioStamped",
        ),
        DeclareLaunchArgument(
            "output_topic",
            default_value="/audio/input/boosted",
            description="AudioStamped with applied gain_linear",
        ),
        DeclareLaunchArgument(
            "gain_linear",
            default_value="2.0",
            description="Linear gain factor (multiply samples)",
        ),
        DeclareLaunchArgument(
            "qos_depth",
            default_value="50",
            description="Publisher/subscriber HISTORY depth",
        ),
        DeclareLaunchArgument(
            "node_name",
            default_value="audio_gain",
            description="ROS node name",
        ),
    ]

    node = Node(
        package="audio_filters",
        executable="audio_gain_node",
        name=LaunchConfiguration("node_name"),
        output="screen",
        parameters=[
            {
                "input_topic": LaunchConfiguration("input_topic"),
                "output_topic": LaunchConfiguration("output_topic"),
                "gain_linear": ParameterValue(
                    LaunchConfiguration("gain_linear"),
                    value_type=float,
                ),
                "qos_depth": ParameterValue(
                    LaunchConfiguration("qos_depth"),
                    value_type=int,
                ),
            }
        ],
    )

    return LaunchDescription(args + [node])
