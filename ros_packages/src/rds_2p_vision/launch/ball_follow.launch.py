from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    share = FindPackageShare('rds_2p_vision')
    return LaunchDescription([
        DeclareLaunchArgument('image_topic', default_value='/camera/color/image_raw'),
        DeclareLaunchArgument('model_path', default_value=PathJoinSubstitution([share, 'models', 'yolov8n_balls.onnx'])),
        Node(package='rds_2p_vision', executable='ball_follow', name='ball_follow', output='screen',
             parameters=[PathJoinSubstitution([share, 'config', 'ball_follow.yaml']),
                         {'image_topic': LaunchConfiguration('image_topic'),
                          'model_path': LaunchConfiguration('model_path')}]),
    ])
