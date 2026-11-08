#!/usr/bin/env python3
"""
Launch файл для запуска виртуального двойника RDS-2P с MuJoCo симуляцией.

Этот launch файл запускает:
1. Контроллер моторов (ftservo_ros)
2. Мост суставов к моторам (rds_2p)
3. Одометрию MTF-02P с слиянием IMU (mtf02p_ros: публикует /odom/raw и /odom)
4. MuJoCo симуляцию в headless режиме (virtual_twin_node.py из пакета rds_2p_inference)
5. Систему отображения лица с тачпадом PS4 (rds_2p_face)
6. Dance action server (rds_2p_dance)
7. Dance joy controller (rds_2p_dance) - управление танцами через джойстик
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, ExecuteProcess
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
from pathlib import Path
import os


def generate_launch_description():
    # Получаем пути к пакетам
    ftservo_ros_pkg = FindPackageShare('ftservo_ros')
    rds_2p_pkg = FindPackageShare('rds_2p')
    mtf02p_ros_pkg = FindPackageShare('mtf02p_ros')
    rds_2p_face_pkg = FindPackageShare('rds_2p_face')
    rds_2p_dance_pkg = FindPackageShare('rds_2p_dance')
    
    # Python для twin: системный (зависимости ставятся build-скриптом из requirements.txt);
    # переопределяется переменным окружения RDS2P_TWIN_PYTHON
    venv_python = os.environ.get('RDS2P_TWIN_PYTHON', 'python3')
    
    # Получаем абсолютные пути для конфигурационных файлов
    ftservo_config_file = PathJoinSubstitution([
        FindPackageShare('ftservo_ros'),
        'config',
        'config_example.yaml'
    ])
    
    rds_2p_offsets_config_file = PathJoinSubstitution([
        FindPackageShare('rds_2p'),
        'config',
        'joint_offsets_example.yaml'
    ])
    
    # Аргументы запуска
    interface_arg = DeclareLaunchArgument(
        'interface',
        default_value='/dev/ttyS7',
        description='Путь к последовательному интерфейсу'
    )
    
    config_file_arg = DeclareLaunchArgument(
        'config_file',
        default_value=ftservo_config_file,
        description='Путь к файлу конфигурации моторов'
    )
    
    is_sim_arg = DeclareLaunchArgument(
        'is_sim',
        default_value='false',
        description='Включить режим симуляции моторов'
    )
    
    log_level_arg = DeclareLaunchArgument(
        'log_level',
        default_value='ERROR',
        description='Уровень логирования: debug, info, warn, error, fatal'
    )
    
    offsets_config_file_arg = DeclareLaunchArgument(
        'offsets_config_file',
        default_value=rds_2p_offsets_config_file,
        description='Путь к файлу конфигурации смещений суставов'
    )
    
    # Аргументы для mtf02p_odom_with_fusion (опционально, можно настроить)
    mtf02p_log_level_arg = DeclareLaunchArgument(
        'mtf02p_log_level',
        default_value='info',
        description='Уровень логирования для mtf02p_odom и odom_fusion: debug, info, warn, error, fatal'
    )
    
    # Аргументы для face_with_touchpad (опционально, можно настроить)
    face_log_level_arg = DeclareLaunchArgument(
        'face_log_level',
        default_value='info',
        description='Уровень логирования для face_with_touchpad: debug, info, warn, error, fatal'
    )
    
    # Аргументы для dance_joy_controller (опционально, можно настроить)
    dance_joy_log_level_arg = DeclareLaunchArgument(
        'dance_joy_log_level',
        default_value='info',
        description='Уровень логирования для dance_joy_controller: debug, info, warn, error, fatal'
    )
    
    # Включение launch файла контроллера моторов
    motor_controller_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                ftservo_ros_pkg,
                'launch',
                'motor_controller.launch.py'
            ])
        ]),
        launch_arguments={
            'interface': LaunchConfiguration('interface'),
            'config_file': LaunchConfiguration('config_file'),
            'is_sim': LaunchConfiguration('is_sim'),
            'log_level': LaunchConfiguration('log_level'),
        }.items()
    )
    
    # Включение launch файла bridge_joints_to_motors
    bridge_joints_to_motors_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                rds_2p_pkg,
                'launch',
                'bridge_joints_to_motors.launch.py'
            ])
        ]),
        launch_arguments={
            'offsets_config_file': LaunchConfiguration('offsets_config_file'),
        }.items()
    )
    
    # Примечание: IMU трансформации и статические трансформации должны запускаться
    # отдельно через display.launch.py, чтобы избежать дублирования трансформаций
    
    # Включение общего launch файла mtf02p_odom_with_fusion
    # Запускает и mtf02p_odom (публикует /odom/raw), и odom_fusion (публикует /odom)
    mtf02p_odom_with_fusion_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                mtf02p_ros_pkg,
                'launch',
                'mtf02p_odom_with_fusion.launch.py'
            ])
        ]),
        launch_arguments={
            'log_level': LaunchConfiguration('mtf02p_log_level'),
        }.items()
    )
    
    # Запуск MuJoCo симуляции в headless режиме
    # Используем Python из виртуального окружения для запуска скрипта
    # Скрипт устанавливается в lib/rds_2p_inference/virtual_twin_node.py
    pkg_share = get_package_share_directory('rds_2p_inference')
    # pkg_share = install/rds_2p_inference/share/rds_2p_inference
    # Нужно подняться на 3 уровня вверх: share -> rds_2p_inference -> install
    install_dir = os.path.dirname(os.path.dirname(os.path.dirname(pkg_share)))  # Go up from share/rds_2p_inference/share to install
    virtual_twin_script = os.path.join(install_dir, 'rds_2p_inference', 'lib', 'rds_2p_inference', 'virtual_twin_node.py')
    
    virtual_twin_node = ExecuteProcess(
        cmd=[venv_python, virtual_twin_script, '--headless'],
        output='screen',
        shell=False
    )
    
    # Включение launch файла face_with_touchpad для управления через PS4 джойстик и отображения лица
    face_with_touchpad_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                rds_2p_face_pkg,
                'launch',
                'face_with_touchpad.launch.py'
            ])
        ]),
        launch_arguments={
            'log_level': LaunchConfiguration('face_log_level'),
        }.items()
    )
    
    # Запуск dance action server
    dance_action_server = ExecuteProcess(
        cmd=['ros2', 'run', 'rds_2p_dance', 'dance_action_server'],
        output='screen',
        shell=False
    )
    
    # Включение launch файла dance_joy_controller для управления танцами через джойстик
    dance_joy_controller_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                rds_2p_dance_pkg,
                'launch',
                'dance_joy_controller.launch.py'
            ])
        ]),
        launch_arguments={
            'log_level': LaunchConfiguration('dance_joy_log_level'),
        }.items()
    )
    
    return LaunchDescription([
        # Аргументы
        interface_arg,
        config_file_arg,
        is_sim_arg,
        log_level_arg,
        offsets_config_file_arg,
        mtf02p_log_level_arg,
        face_log_level_arg,
        dance_joy_log_level_arg,
        
        # Launch файлы и процессы
        motor_controller_launch,
        bridge_joints_to_motors_launch,
        mtf02p_odom_with_fusion_launch,  # Одометрия MTF-02P с слиянием IMU (публикует /odom/raw и /odom)
        virtual_twin_node,
        
        # Face with touchpad (заменяет teleop_twist_joy)
        # Включает ps4_joystick, touchpad_drawer, image_processor и display_face
        face_with_touchpad_launch,
        
        # Dance action server
        dance_action_server,
        
        # Dance joy controller (управление танцами через джойстик)
        dance_joy_controller_launch,
    ])
