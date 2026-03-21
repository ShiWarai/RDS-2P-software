#!/usr/bin/env python3
"""
Тестовый launch файл для запуска одометрии MTF-02P с слиянием данных IMU.

Этот launch файл позволяет:
1. Запустить mpu6500_simple_imu_node с настраиваемым топиком IMU (реальный IMU)
2. Запустить odom_fusion_node - объединяет позицию из /odom/raw (от virtual_twin_sim.launch.py) 
   с ориентацией из IMU и публикует /odom/test

Использование:
    ros2 launch mtf02p_ros mtf02p_odom_with_fusion_test.launch.py \
        imu_topic:=/imu_real \
        frame_id:=imu_link \
        enable_calibration:=true

Примечание:
    - Использует отдельные фреймы: odom_test -> odom_test_link (чтобы не конфликтовать с основным launch)
    - Публикует в /odom/test (чтобы не конфликтовать с /odom)
    - Использует /odom/raw от уже запущенного virtual_twin_sim.launch.py (НЕ запускает свой mtf02p_odom_node)
    - Для просмотра в RViz2 выберите fixed frame: odom_test
    - ВАЖНО: Если точки прыгают при использовании map как fixed frame, используйте odom_test вместо map
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.launch_description_sources import PythonLaunchDescriptionSource

def generate_launch_description():
    # Получаем пути к пакетам
    mtf02p_ros_pkg = FindPackageShare('mtf02p_ros')
    mpu6500_ros_pkg = FindPackageShare('mpu6500_ros')
    
    # Аргументы для odom_fusion (используем /odom/raw от virtual_twin_sim.launch.py)
    odom_frame_id_arg = DeclareLaunchArgument(
        'odom_frame_id',
        default_value='odom_test',
        description='Родительский frame для тестовой одометрии (по умолчанию odom_test для тестов)'
    )
    
    # Аргументы для mpu6500_simple_imu
    imu_address_arg = DeclareLaunchArgument(
        'imu_address',
        default_value='0',
        description='MPU6500 address: 0 or 1'
    )
    
    imu_publish_rate_arg = DeclareLaunchArgument(
        'imu_publish_rate',
        default_value='100.0',
        description='IMU data publish rate in Hz'
    )
    
    imu_frame_id_arg = DeclareLaunchArgument(
        'frame_id',
        default_value='imu_link',
        description='Frame ID for IMU messages'
    )
    
    enable_calibration_arg = DeclareLaunchArgument(
        'enable_calibration',
        default_value='true',
        description='Enable automatic calibration on startup'
    )
    
    enable_temperature_arg = DeclareLaunchArgument(
        'enable_temperature',
        default_value='false',
        description='Enable temperature publishing (every 5 seconds)'
    )
    
    # Аргумент для топика IMU
    imu_topic_arg = DeclareLaunchArgument(
        'imu_topic',
        default_value='/imu_real',
        description='Топик для публикации данных IMU (по умолчанию /imu_real для реального IMU)'
    )
    
    # Аргумент для топика одометрии
    odom_topic_arg = DeclareLaunchArgument(
        'odom_topic',
        default_value='/odom/test',
        description='Топик для публикации объединенной одометрии (по умолчанию /odom/test для тестов)'
    )
    
    # Аргументы для odom_fusion
    # Используем отдельный аргумент для child_frame_id odom_fusion, чтобы избежать конфликта с mtf02p_odom
    odom_fusion_child_frame_id_arg = DeclareLaunchArgument(
        'odom_fusion_child_frame_id',
        default_value='odom_test_link',
        description='Дочерний frame для odom_fusion (по умолчанию odom_test_link для тестов)'
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
    
    # Общие аргументы
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='info',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )
    
    # Примечание: mtf02p_odom_node НЕ запускается здесь
    # Используется /odom/raw от уже запущенного virtual_twin_sim.launch.py
    
    # Узел MPU6500 Simple IMU с remapping топика
    mpu6500_simple_imu_node = Node(
        package='mpu6500_ros',
        executable='mpu6500_simple_imu_node',
        name='mpu6500_simple_imu_node',
        output='screen',
        parameters=[{
            'address': LaunchConfiguration('imu_address'),
            'publish_rate': LaunchConfiguration('imu_publish_rate'),
            'frame_id': LaunchConfiguration('frame_id'),
            'enable_calibration': LaunchConfiguration('enable_calibration'),
            'enable_temperature': LaunchConfiguration('enable_temperature'),
        }],
        remappings=[
            ('/imu', LaunchConfiguration('imu_topic')),  # Remap /imu на настраиваемый топик
        ],
        arguments=[
            '--ros-args',
            '--log-level', LaunchConfiguration('log_level')
        ]
    )
    
    # Включение launch файла odom_fusion с настраиваемым топиком IMU
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
            'child_frame_id': LaunchConfiguration('odom_fusion_child_frame_id'),  # Используем отдельный аргумент
            'publish_tf': LaunchConfiguration('publish_tf_fusion'),
            'imu_timeout': LaunchConfiguration('imu_timeout'),
            'imu_topic': LaunchConfiguration('imu_topic'),  # Передаем настраиваемый топик IMU
            'odom_topic': LaunchConfiguration('odom_topic'),  # Передаем настраиваемый топик одометрии
            'log_level': LaunchConfiguration('log_level'),
        }.items()
    )
    
    # Статическая трансформация от map к odom_test для визуализации в RViz2
    # ВАЖНО: Используйте odom_test как fixed frame для стабильной визуализации, а не map!
    # Эта трансформация нужна только если вы хотите видеть оба дерева TF (основное и тестовое) одновременно
    # Если точки прыгают при использовании map как fixed frame, используйте odom_test вместо map
    static_transform_map_to_odom_test = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='static_transform_map_to_odom_test',
        arguments=[
            '--frame-id', 'map',
            '--child-frame-id', LaunchConfiguration('odom_frame_id'),  # odom_test
            '--x', '0',
            '--y', '0',
            '--z', '0',
            '--qx', '0',
            '--qy', '0',
            '--qz', '0',
            '--qw', '1',
        ],
        output='screen'
    )
    
    return LaunchDescription([
        # Аргументы для odom_fusion
        odom_frame_id_arg,
        
        # Аргументы для mpu6500_simple_imu
        imu_address_arg,
        imu_publish_rate_arg,
        imu_frame_id_arg,
        enable_calibration_arg,
        enable_temperature_arg,
        imu_topic_arg,
        
        # Аргументы для odom_fusion
        odom_topic_arg,
        odom_fusion_child_frame_id_arg,
        publish_tf_fusion_arg,
        imu_timeout_arg,
        
        # Общие аргументы
        log_level_arg,
        
        # Launch файлы и узлы
        # Примечание: mtf02p_odom_node НЕ запускается - используется /odom/raw от virtual_twin_sim.launch.py
        mpu6500_simple_imu_node,  # Запускается первым (публикует данные IMU в настраиваемый топик)
        odom_fusion_launch,  # Запускается вторым (подписывается на /odom/raw и настраиваемый топик IMU)
        static_transform_map_to_odom_test,  # Статическая трансформация map -> odom_test (опционально, для совместимости)
    ])

