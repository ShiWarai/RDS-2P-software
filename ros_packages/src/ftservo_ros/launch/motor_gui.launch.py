from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.substitutions import FindPackageShare
from pathlib import Path

def generate_launch_description():
    return LaunchDescription([
        # Аргументы запуска
        DeclareLaunchArgument(
            'config_file',
            default_value='',
            description='Path to motor configuration file (required)'
        ),
        
        # GUI узел для тестирования
        Node(
            package='ftservo_ros',
            executable='motor_gui.py',
            name='motor_gui',
            output='screen',
            parameters=[{
                'config_file': LaunchConfiguration('config_file'),
            }],
            arguments=[
                '--ros-args',
                '--log-level', 'info'
            ]
        )
    ]) 