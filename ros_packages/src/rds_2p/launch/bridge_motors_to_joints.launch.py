#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    return LaunchDescription([
        # Аргументы запуска
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',  # По умолчанию false для реальных моторов
            description='Use simulation time'
        ),
        
        DeclareLaunchArgument(
            'joint_state_rate',
            default_value='50.0',
            description='Joint state publication rate in Hz'
        ),
        
        DeclareLaunchArgument(
            'offsets_config_file',
            default_value=PathJoinSubstitution([
                FindPackageShare('rds_2p'),
                'config',
                'joint_offsets.yaml'
            ]),
            description='Path to joint offsets configuration file'
        ),
        
        # Запуск только моста мотор-сустав (БЕЗ контроллера моторов)
        Node(
            package='rds_2p',
            executable='motor_to_joint_bridge',
            name='motor_to_joint_bridge',
            output='screen',
            parameters=[{
                'use_sim_time': LaunchConfiguration('use_sim_time'),
                'joint_state_rate': LaunchConfiguration('joint_state_rate'),
                'offsets_config_file': LaunchConfiguration('offsets_config_file'),
            }],
            arguments=[
                '--ros-args',
                '--log-level', 'info'
            ]
        ),
    ])


