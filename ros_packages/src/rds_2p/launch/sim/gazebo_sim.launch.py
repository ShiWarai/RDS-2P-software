#!/usr/bin/env python3

import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Получаем путь к пакету
    pkg_share = get_package_share_directory('rds_2p')

    # Настройка путей для Gazebo
    world_path = os.path.join(pkg_share, 'worlds', 'empty.sdf')

    # Устанавливаем переменные окружения для Gazebo
    os.environ['GZ_SIM_RESOURCE_PATH'] = str(Path(pkg_share).parent)

    # Аргументы запуска
    use_sim_time = LaunchConfiguration('use_sim_time')
    use_rviz = LaunchConfiguration('use_rviz')

    # Объявляем аргументы
    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation time'
    )

    declare_use_rviz = DeclareLaunchArgument(
        'use_rviz',
        default_value='true',
        description='Launch RViz2'
    )

    # Запускаем Gazebo
    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('ros_gz_sim'),
                'launch',
                'gz_sim.launch.py'
            ])
        ]),
        launch_arguments={
            'gz_args': f'-r {world_path} --verbose'
        }.items()
    )

    # Robot State Publisher
    robot_state_publisher = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('rds_2p'),
                'launch',
                'description.launch.py'
            ])
        ]),
        launch_arguments={
            'use_sim_time': use_sim_time
        }.items()
    )

    # Спавним робота в Gazebo
    spawn_robot = Node(
        package='ros_gz_sim',
        executable='create',
        arguments=[
            '-name', 'rds-2p',
            '-x', '0.0',
            '-y', '0.0',
            '-z', '0.5',
            '-topic', '/robot_description'
        ],
        output='screen'
    )

    # Bridge для параметров (время симуляции)
    gz_bridge_parameter = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        arguments=['/clock@rosgraph_msgs/msg/Clock[ignition.msgs.Clock'],
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
        }]
    )

    # Контроллеры суставов
    controllers = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('rds_2p'),
                'launch',
                'controllers.launch.py'
            ])
        ]),
        launch_arguments={
            'use_sim_time': use_sim_time
        }.items()
    )

    # Joint State Publisher GUI для управления суставами
    joint_state_publisher_gui = Node(
        package='joint_state_publisher_gui',
        executable='joint_state_publisher_gui',
        name='joint_state_publisher_gui',
        output='screen',
        parameters=[{'use_sim_time': use_sim_time}]
    )

    # RViz2 (опционально)
    rviz = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('rds_2p'),
                'launch',
                'display.launch.py'
            ])
        ]),
        condition=IfCondition(use_rviz),
        launch_arguments={
            'use_sim_time': use_sim_time
        }.items()
    )

    return LaunchDescription([
        declare_use_sim_time,
        declare_use_rviz,
        gazebo,
        robot_state_publisher,
        spawn_robot,
        gz_bridge_parameter,
        controllers,
        joint_state_publisher_gui,
        rviz
    ]) 