from pathlib import Path

import launch
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution

import launch_ros
from launch_ros.substitutions import FindPackageShare
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    pkg_share = Path(launch_ros.substitutions.FindPackageShare(package='rds_2p').find('rds_2p'))
    default_model_path = pkg_share / 'urdf/rds-2p_description_wrapper.urdf.xacro'
    default_rviz_config_path = pkg_share / 'rviz/robot_description.rviz'

    use_sim_time = LaunchConfiguration('use_sim_time')

    # Включаем описание робота
    robot_state_publisher_node = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('rds_2p'),
                'launch',
                'description.launch.py',
            ]),
        ]),
        launch_arguments=dict(use_sim_time=use_sim_time).items(),
    )

    # Включаем IMU трансформацию
    imu_transform_node = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('rds_2p'),
                'launch',
                'imu_transform.launch.py',
            ]),
        ]),
        launch_arguments=dict(use_sim_time=use_sim_time).items(),
    )

    # Узел для статических трансформаций (map_link -> odom_link)
    static_transform_node = launch_ros.actions.Node(
        package='rds_2p',
        executable='static_transform_publisher',
        name='static_transform_publisher',
        output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
        }],
    )

    rviz_node = launch_ros.actions.Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', LaunchConfiguration('rvizconfig')],
        parameters=[{
            'use_sim_time': use_sim_time,
        }],
    )

    return launch.LaunchDescription([
        launch.actions.DeclareLaunchArgument(
            name='use_sim_time',
            default_value='false',  # Используем реальное время для реального IMU
            description='Flag to enable usage of simulation time',
        ),
        launch.actions.DeclareLaunchArgument(
            name='model',
            default_value=str(default_model_path),
            description='Absolute path to robot urdf file',
        ),
        launch.actions.DeclareLaunchArgument(
            name='rvizconfig',
            default_value=str(default_rviz_config_path),
            description='Absolute path to rviz config file',
        ),
        robot_state_publisher_node,
        imu_transform_node,
        static_transform_node,
        rviz_node,
    ])
