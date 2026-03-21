#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare
from launch.launch_description_sources import PythonLaunchDescriptionSource
import os


def generate_launch_description():
    # Получаем пути к пакетам
    ftservo_ros_pkg = FindPackageShare('ftservo_ros')
    rds_2p_pkg = FindPackageShare('rds_2p')
    
    # Получаем абсолютные пути для конфигурационных файлов
    # Пользователь указал относительные пути от src, нужно получить их через пакеты
    ftservo_config_file = PathJoinSubstitution([
        FindPackageShare('ftservo_ros'),
        'config',
        'config_example.yaml'
    ])
    
    rds_2p_offsets_config_file = PathJoinSubstitution([
        FindPackageShare('rds_2p'),
        'config',
        'joint_offsets_example.yaml'
    ])
    
    # Аргументы запуска
    interface_arg = DeclareLaunchArgument(
        'interface',
        default_value='/dev/ttyS7',
        description='Путь к последовательному интерфейсу'
    )
    
    config_file_arg = DeclareLaunchArgument(
        'config_file',
        default_value=ftservo_config_file,
        description='Путь к файлу конфигурации моторов'
    )
    
    is_sim_arg = DeclareLaunchArgument(
        'is_sim',
        default_value='false',
        description='Включить режим симуляции моторов'
    )
    
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='ERROR',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )
    
    offsets_config_file_arg = DeclareLaunchArgument(
        'offsets_config_file',
        default_value=rds_2p_offsets_config_file,
        description='Путь к файлу конфигурации смещений суставов'
    )
    
    # Включение launch файла контроллера моторов
    motor_controller_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                ftservo_ros_pkg,
                'launch',
                'motor_controller.launch.py'
            ])
        ]),
        launch_arguments={
            'interface': LaunchConfiguration('interface'),
            'config_file': LaunchConfiguration('config_file'),
            'is_sim': LaunchConfiguration('is_sim'),
            'log_level': LaunchConfiguration('log_level'),
        }.items()
    )
    
    # Включение launch файла bridge_motors_to_joints
    bridge_motors_to_joints_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                rds_2p_pkg,
                'launch',
                'bridge_motors_to_joints.launch.py'
            ])
        ]),
        launch_arguments={
            'offsets_config_file': LaunchConfiguration('offsets_config_file'),
        }.items()
    )
    
    # Включение launch файла bridge_joints_to_motors
    bridge_joints_to_motors_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                rds_2p_pkg,
                'launch',
                'bridge_joints_to_motors.launch.py'
            ])
        ]),
        launch_arguments={
            'offsets_config_file': LaunchConfiguration('offsets_config_file'),
        }.items()
    )
    
    return LaunchDescription([
        # Аргументы
        interface_arg,
        config_file_arg,
        is_sim_arg,
        log_level_arg,
        offsets_config_file_arg,
        
        # Launch файлы
        motor_controller_launch,
        bridge_motors_to_joints_launch,
        bridge_joints_to_motors_launch,
    ])


