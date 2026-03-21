#!/usr/bin/env python3
"""
Общий launch файл для запуска одометрии MTF-02P с слиянием данных IMU.

Этот launch файл запускает:
1. mtf02p_odom_node - публикует /odom/raw с позицией из оптического потока
2. odom_fusion_node - объединяет позицию из /odom/raw с ориентацией из /imu и публикует /odom
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare
from launch.launch_description_sources import PythonLaunchDescriptionSource

def generate_launch_description():
    # Получаем путь к пакету
    mtf02p_ros_pkg = FindPackageShare('mtf02p_ros')
    
    # Аргументы для mtf02p_odom
    uart_port_arg = DeclareLaunchArgument(
        'uart_port',
        default_value='/dev/ttyS3',
        description='Путь к UART устройству (UART3_M2 на Orange Pi 5 Pro)'
    )
    
    uart_baudrate_arg = DeclareLaunchArgument(
        'uart_baudrate',
        default_value='115200',
        description='Скорость передачи данных UART'
    )
    
    odom_frame_id_arg = DeclareLaunchArgument(
        'odom_frame_id',
        default_value='odom',
        description='Родительский frame для одометрии'
    )
    
    publish_tf_odom_arg = DeclareLaunchArgument(
        'publish_tf_odom',
        default_value='true',
        description='Публиковать ли трансформацию odom -> odom_raw_link из mtf02p_odom'
    )
    
    publish_rate_arg = DeclareLaunchArgument(
        'publish_rate',
        default_value='50.0',
        description='Частота публикации одометрии (Hz)'
    )
    
    kalman_process_variance_arg = DeclareLaunchArgument(
        'kalman_process_variance',
        default_value='0.01',
        description='Ковариация процесса для фильтра Калмана'
    )
    
    kalman_measurement_variance_arg = DeclareLaunchArgument(
        'kalman_measurement_variance',
        default_value='0.1',
        description='Ковариация измерения для фильтра Калмана'
    )
    
    max_velocity_change_arg = DeclareLaunchArgument(
        'max_velocity_change',
        default_value='50.0',
        description='Максимальное изменение скорости за шаг (см/с)'
    )
    
    dead_zone_threshold_arg = DeclareLaunchArgument(
        'dead_zone_threshold',
        default_value='1.0',
        description='Порог dead zone для фильтрации малых скоростей (см/с)'
    )
    
    min_dt_arg = DeclareLaunchArgument(
        'min_dt',
        default_value='0.001',
        description='Минимальный временной интервал между измерениями (секунды)'
    )
    
    max_dt_arg = DeclareLaunchArgument(
        'max_dt',
        default_value='2.0',
        description='Максимальный временной интервал между измерениями (секунды)'
    )
    
    # Аргументы для odom_fusion
    child_frame_id_arg = DeclareLaunchArgument(
        'child_frame_id',
        default_value='odom_link',
        description='Дочерний frame для объединенной одометрии (odom_fusion)'
    )
    
    publish_tf_fusion_arg = DeclareLaunchArgument(
        'publish_tf_fusion',
        default_value='true',
        description='Публиковать ли трансформацию odom -> odom_link из odom_fusion'
    )
    
    imu_timeout_arg = DeclareLaunchArgument(
        'imu_timeout',
        default_value='1.0',
        description='Максимальное время ожидания IMU данных (секунды)'
    )
    
    odom_topic_arg = DeclareLaunchArgument(
        'odom_topic',
        default_value='/odom',
        description='Топик для публикации объединенной одометрии'
    )
    
    # Общие аргументы
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )
    
    # Включение launch файла mtf02p_odom
    mtf02p_odom_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                mtf02p_ros_pkg,
                'launch',
                'mtf02p_odom.launch.py'
            ])
        ]),
        launch_arguments={
            'uart_port': LaunchConfiguration('uart_port'),
            'uart_baudrate': LaunchConfiguration('uart_baudrate'),
            'odom_frame_id': LaunchConfiguration('odom_frame_id'),
            'child_frame_id': 'odom_raw_link',  # Фиксированное значение для mtf02p_odom
            'publish_tf': LaunchConfiguration('publish_tf_odom'),
            'publish_rate': LaunchConfiguration('publish_rate'),
            'kalman_process_variance': LaunchConfiguration('kalman_process_variance'),
            'kalman_measurement_variance': LaunchConfiguration('kalman_measurement_variance'),
            'max_velocity_change': LaunchConfiguration('max_velocity_change'),
            'dead_zone_threshold': LaunchConfiguration('dead_zone_threshold'),
            'min_dt': LaunchConfiguration('min_dt'),
            'max_dt': LaunchConfiguration('max_dt'),
            'log_level': LaunchConfiguration('log_level'),
        }.items()
    )
    
    # Включение launch файла odom_fusion
    odom_fusion_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                mtf02p_ros_pkg,
                'launch',
                'odom_fusion.launch.py'
            ])
        ]),
        launch_arguments={
            'odom_frame_id': LaunchConfiguration('odom_frame_id'),
            'child_frame_id': LaunchConfiguration('child_frame_id'),
            'publish_tf': LaunchConfiguration('publish_tf_fusion'),
            'imu_timeout': LaunchConfiguration('imu_timeout'),
            'odom_topic': LaunchConfiguration('odom_topic'),
            'log_level': LaunchConfiguration('log_level'),
        }.items()
    )
    
    return LaunchDescription([
        # Аргументы для mtf02p_odom
        uart_port_arg,
        uart_baudrate_arg,
        odom_frame_id_arg,
        publish_tf_odom_arg,
        publish_rate_arg,
        kalman_process_variance_arg,
        kalman_measurement_variance_arg,
        max_velocity_change_arg,
        dead_zone_threshold_arg,
        min_dt_arg,
        max_dt_arg,
        
        # Аргументы для odom_fusion
        child_frame_id_arg,
        publish_tf_fusion_arg,
        imu_timeout_arg,
        odom_topic_arg,
        
        # Общие аргументы
        log_level_arg,
        
        # Launch файлы
        mtf02p_odom_launch,  # Запускается первым (публикует /odom/raw)
        odom_fusion_launch,  # Запускается вторым (подписывается на /odom/raw и /imu)
    ])

