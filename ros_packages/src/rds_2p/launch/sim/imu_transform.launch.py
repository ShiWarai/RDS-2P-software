from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    return LaunchDescription([
        # Аргументы запуска
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Flag to enable usage of simulation time'
        ),
        
        # Узел для публикации трансформации IMU
        Node(
            package='rds_2p',
            executable='imu_transform_publisher',
            name='imu_transform_publisher',
            output='screen',
            parameters=[{
                'use_sim_time': LaunchConfiguration('use_sim_time'),
            }],
            arguments=[
                '--ros-args',
                '--log-level', 'info'
            ]
        )
    ])
