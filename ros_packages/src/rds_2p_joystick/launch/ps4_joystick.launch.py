#!/usr/bin/env python3
"""
Launch файл для управления RDS-2P через PS4 джойстик.

Этот launch файл запускает:
1. joy_node - чтение базовых данных джойстика (оси, кнопки)
2. teleop_twist_joy_node - преобразование команд джойстика в /cmd_vel
3. ps4_imu_node - чтение данных акселерометра и гироскопа PS4 контроллера
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution
import os


def generate_launch_description():
    # Получаем пути к пакетам
    teleop_twist_joy_pkg = FindPackageShare('teleop_twist_joy')
    rds_2p_joystick_pkg = FindPackageShare('rds_2p_joystick')
    
    # Получаем путь к конфигурационному файлу teleop_twist_joy
    teleop_config_file = PathJoinSubstitution([
        teleop_twist_joy_pkg,
        'config',
        'ps3.config.yaml'  # Используем ps3 конфигурацию для PS4 (совместима)
    ])
    
    # Аргументы запуска
    enable_teleop_arg = DeclareLaunchArgument(
        'enable_teleop',
        default_value='true',
        description='Включить teleop_twist_joy для управления через джойстик'
    )
    
    enable_imu_arg = DeclareLaunchArgument(
        'enable_imu',
        default_value='true',
        description='Включить чтение данных IMU с PS4 контроллера'
    )
    
    enable_touchpad_arg = DeclareLaunchArgument(
        'enable_touchpad',
        default_value='true',
        description='Включить чтение данных тачпада с PS4 контроллера'
    )
    
    frame_id_arg = DeclareLaunchArgument(
        'frame_id',
        default_value='ps4_controller',
        description='Frame ID для IMU сообщений и TF трансформации'
    )
    
    parent_frame_id_arg = DeclareLaunchArgument(
        'parent_frame_id',
        default_value='odom_link',
        description='Родительский frame ID для TF трансформации'
    )
    
    publish_tf_arg = DeclareLaunchArgument(
        'publish_tf',
        default_value='true',
        description='Публиковать TF трансформацию для ориентации контроллера'
    )
    
    imu_publish_rate_arg = DeclareLaunchArgument(
        'imu_publish_rate',
        default_value='50.0',
        description='Частота публикации IMU данных (Гц)'
    )
    
    imu_update_rate_arg = DeclareLaunchArgument(
        'imu_update_rate',
        default_value='100.0',
        description='Частота обновления ориентации для точности (Гц)'
    )
    
    touchpad_publish_rate_arg = DeclareLaunchArgument(
        'touchpad_publish_rate',
        default_value='50.0',
        description='Частота публикации данных тачпада (Гц)'
    )
    
    debug_touchpad_arg = DeclareLaunchArgument(
        'debug_touchpad',
        default_value='false',
        description='Включить отладочное логирование для тачпада'
    )
    
    # Joy node для чтения данных с джойстика
    # Устройство определяется автоматически joy_node (обычно /dev/input/js0)
    joy_node = Node(
        package='joy',
        executable='joy_node',
        name='joy_node',
        parameters=[{
            'deadzone': 0.1,
            'autorepeat_rate': 20.0,
        }],
        arguments=['--ros-args', '--log-level', 'WARN'],  # Подавление INFO логов о неизвестных типах событий
        condition=IfCondition(LaunchConfiguration('enable_teleop')),
        output='screen'
    )
    
    # Teleop twist joy node для преобразования команд джойстика в cmd_vel
    teleop_twist_joy_node = Node(
        package='teleop_twist_joy',
        executable='teleop_node',
        name='teleop_twist_joy_node',
        parameters=[
            teleop_config_file,
            {
                'require_enable_button': False,  # Отключаем требование удержания кнопки
                # Оси управления
                'axis_linear.x': 1,  # Левый стик вверх/вниз для движения вперед/назад
                'axis_linear.y': 2,  # Правый стик влево/вправо для движения вбок
                'axis_angular.yaw': 0,  # Левый стик влево/вправо для поворота
                # Масштабы движения (обычный режим)
                'scale_linear.x': 0.5,  # Ограничение движения вперед/назад до 0.5
                'scale_linear.y': 0.5,  # Масштаб движения вбок
                'scale_angular.yaw': 1.0,  # Увеличенный поворот
                # Турбо режим (активируется кнопкой L1)
                'enable_turbo_button': 4,  # L1 кнопка для активации турбо режима (PS4: кнопка 4)
                'scale_linear_turbo.x': 1.0,  # Увеличенная скорость вперед/назад в турбо режиме
                'scale_linear_turbo.y': 1.0,  # Увеличенная скорость вбок в турбо режиме
                'scale_angular_turbo.yaw': 1.5,  # Увеличенный поворот в турбо режиме
            }
        ],
        arguments=['--ros-args', '--log-level', 'WARN'],  # Подавление INFO логов при инициализации
        condition=IfCondition(LaunchConfiguration('enable_teleop')),
        output='screen'
    )
    
    # Узел PS4 IMU для чтения данных акселерометра и гироскопа
    # Устройство определяется автоматически нодой из логов ds4drv или поиском
    ps4_imu_node = Node(
        package='rds_2p_joystick',
        executable='ps4_imu_node.py',
        name='ps4_imu_node',
        parameters=[{
            'frame_id': LaunchConfiguration('frame_id'),
            'parent_frame_id': LaunchConfiguration('parent_frame_id'),
            'publish_rate': LaunchConfiguration('imu_publish_rate'),
            'update_rate': LaunchConfiguration('imu_update_rate'),
            'publish_tf': LaunchConfiguration('publish_tf'),
        }],
        condition=IfCondition(LaunchConfiguration('enable_imu')),
        output='screen'
    )
    
    # Узел PS4 Touchpad для чтения данных тачпада
    # Устройство определяется автоматически нодой (проверка структуры отчёта PS4)
    ps4_touchpad_node = Node(
        package='rds_2p_joystick',
        executable='ps4_touchpad_node.py',
        name='ps4_touchpad_node',
        parameters=[{
            'frame_id': LaunchConfiguration('frame_id'),
            'publish_rate': LaunchConfiguration('touchpad_publish_rate'),
            'debug_touchpad': LaunchConfiguration('debug_touchpad'),
        }],
        condition=IfCondition(LaunchConfiguration('enable_touchpad')),
        output='screen'
    )
    
    return LaunchDescription([
        # Аргументы
        enable_teleop_arg,
        enable_imu_arg,
        enable_touchpad_arg,
        frame_id_arg,
        parent_frame_id_arg,
        publish_tf_arg,
        imu_publish_rate_arg,
        imu_update_rate_arg,
        touchpad_publish_rate_arg,
        debug_touchpad_arg,
        
        # Узлы
        joy_node,
        teleop_twist_joy_node,
        ps4_imu_node,
        ps4_touchpad_node,
    ])

