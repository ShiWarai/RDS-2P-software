#!/usr/bin/env python3
"""Orbbec Astra Mini — пресет ``stream_profile:=rgb_only`` (только RGB).

Тонкая настройка параметров: ``ros2 launch rds_2p astra_mini.launch.py stream_profile:=rgb_only ...``.
"""

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare('rds_2p'),
                    'launch',
                    'astra_mini.launch.py',
                ]),
            ]),
            launch_arguments=[('stream_profile', 'rgb_only')],
        ),
    ])
