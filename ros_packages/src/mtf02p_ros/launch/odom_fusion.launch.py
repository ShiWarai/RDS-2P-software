from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    return LaunchDescription([
        # Аргументы запуска
        DeclareLaunchArgument(
            'odom_frame_id',
            default_value='odom',
            description='Родительский frame для одометрии'
        ),
        
        DeclareLaunchArgument(
            'child_frame_id',
            default_value='odom_link',
            description='Дочерний frame для одометрии'
        ),
        
        DeclareLaunchArgument(
            'publish_tf',
            default_value='true',
            description='Публиковать ли трансформацию odom -> odom_link'
        ),
        
        DeclareLaunchArgument(
            'imu_timeout',
            default_value='1.0',
            description='Максимальное время ожидания IMU данных (секунды)'
        ),
        
        DeclareLaunchArgument(
            'imu_topic',
            default_value='/imu',
            description='Топик для подписки на данные IMU'
        ),
        
        DeclareLaunchArgument(
            'odom_topic',
            default_value='/odom',
            description='Топик для публикации объединенной одометрии'
        ),
        
        DeclareLaunchArgument(
            'log_level',
            default_value='info',
            description='Уровень логирования: debug, info, warn, error, fatal'
        ),
        
        # Узел слияния одометрии
        Node(
            package='mtf02p_ros',
            executable='odom_fusion_node',
            name='odom_fusion',
            output='screen',
            parameters=[{
                'odom_frame_id': LaunchConfiguration('odom_frame_id'),
                'child_frame_id': LaunchConfiguration('child_frame_id'),
                'publish_tf': LaunchConfiguration('publish_tf'),
                'imu_timeout': LaunchConfiguration('imu_timeout'),
                'imu_topic': LaunchConfiguration('imu_topic'),
                'odom_topic': LaunchConfiguration('odom_topic'),
            }],
            arguments=[
                '--ros-args',
                '--log-level', LaunchConfiguration('log_level')
            ]
        )
    ])

