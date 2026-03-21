from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare

def generate_launch_description():
    return LaunchDescription([
        # Аргументы запуска
        DeclareLaunchArgument(
            'config_file',
            default_value='',
            description='Путь к файлу конфигурации моторов (обязательный)'
        ),
        
        DeclareLaunchArgument(
            'update_rate',
            default_value='55',
            description='Частота обновления состояний моторов (position, velocity, load) в Гц'
        ),
        
        DeclareLaunchArgument(
            'data_rate',
            default_value='10',
            description='Частота обновления телеметрии моторов (temperature, voltage, current) в Гц'
        ),
        

        
        DeclareLaunchArgument(
            'interface',
            default_value='/dev/ttyS0',
            description='Путь к последовательному интерфейсу'
        ),
        
        DeclareLaunchArgument(
            'interface_baudrate',
            default_value='1000000',
            description='Скорость передачи данных последовательного интерфейса'
        ),
        
        DeclareLaunchArgument(
            'is_sim',
            default_value='false',
            description='Включить режим симуляции моторов'
        ),
        
        DeclareLaunchArgument(
            'log_level',
            default_value='info',
            description='Уровень логирования: debug, info, warn, error, fatal'
        ),
        
        # Узел контроллера моторов
        Node(
            package='ftservo_ros',
            executable='motor_controller_node',
            name='motor_controller',
            output='screen',
            parameters=[{
                'config_file': LaunchConfiguration('config_file'),
                'update_rate': LaunchConfiguration('update_rate'),
                'data_rate': LaunchConfiguration('data_rate'),
                'interface': LaunchConfiguration('interface'),
                'interface_baudrate': LaunchConfiguration('interface_baudrate'),
                'is_sim': LaunchConfiguration('is_sim'),
                'log_level': LaunchConfiguration('log_level'),
            }],
            arguments=[
                '--ros-args',
                '--log-level', LaunchConfiguration('log_level')
            ]
        )
    ]) 