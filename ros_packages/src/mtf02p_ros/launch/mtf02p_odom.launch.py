from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    return LaunchDescription([
        # Аргументы запуска
        DeclareLaunchArgument(
            'uart_port',
            default_value='/dev/ttyS3',
            description='Путь к UART устройству (UART3_M2 на Orange Pi 5 Pro)'
        ),
        
        DeclareLaunchArgument(
            'uart_baudrate',
            default_value='115200',
            description='Скорость передачи данных UART'
        ),
        
        DeclareLaunchArgument(
            'odom_frame_id',
            default_value='odom',
            description='Родительский frame для одометрии'
        ),
        
        DeclareLaunchArgument(
            'child_frame_id',
            default_value='odom_raw_link',
            description='Дочерний frame для одометрии'
        ),
        
        DeclareLaunchArgument(
            'publish_tf',
            default_value='true',
            description='Публиковать ли трансформацию odom -> odom_raw_link'
        ),
        
        DeclareLaunchArgument(
            'publish_rate',
            default_value='50.0',
            description='Частота публикации одометрии (Hz)'
        ),
        
        DeclareLaunchArgument(
            'kalman_process_variance',
            default_value='0.01',
            description='Ковариация процесса для фильтра Калмана'
        ),
        
        DeclareLaunchArgument(
            'kalman_measurement_variance',
            default_value='0.1',
            description='Ковариация измерения для фильтра Калмана'
        ),
        
        DeclareLaunchArgument(
            'max_velocity_change',
            default_value='50.0',
            description='Максимальное изменение скорости за шаг (см/с)'
        ),
        
        DeclareLaunchArgument(
            'dead_zone_threshold',
            default_value='1.0',
            description='Порог dead zone для фильтрации малых скоростей (см/с)'
        ),
        
        DeclareLaunchArgument(
            'min_dt',
            default_value='0.001',
            description='Минимальный временной интервал между измерениями (секунды)'
        ),
        
        DeclareLaunchArgument(
            'max_dt',
            default_value='2.0',
            description='Максимальный временной интервал между измерениями (секунды)'
        ),
        
        DeclareLaunchArgument(
            'log_level',
            default_value='info',
            description='Уровень логирования: debug, info, warn, error, fatal'
        ),
        
        # Узел одометрии MTF-02P
        Node(
            package='mtf02p_ros',
            executable='mtf02p_odom_node',
            name='mtf02p_odom',
            output='screen',
            parameters=[{
                'uart_port': LaunchConfiguration('uart_port'),
                'uart_baudrate': LaunchConfiguration('uart_baudrate'),
                'odom_frame_id': LaunchConfiguration('odom_frame_id'),
                'child_frame_id': LaunchConfiguration('child_frame_id'),
                'publish_tf': LaunchConfiguration('publish_tf'),
                'publish_rate': LaunchConfiguration('publish_rate'),
                'kalman_process_variance': LaunchConfiguration('kalman_process_variance'),
                'kalman_measurement_variance': LaunchConfiguration('kalman_measurement_variance'),
                'max_velocity_change': LaunchConfiguration('max_velocity_change'),
                'dead_zone_threshold': LaunchConfiguration('dead_zone_threshold'),
                'min_dt': LaunchConfiguration('min_dt'),
                'max_dt': LaunchConfiguration('max_dt'),
            }],
            arguments=[
                '--ros-args',
                '--log-level', LaunchConfiguration('log_level')
            ]
        )
    ])

