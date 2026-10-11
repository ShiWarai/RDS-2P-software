#!/usr/bin/env python3
"""
Десктопный графический запуск виртуального двойника RDS-2P.
- MuJoCo viewer (если доступен)
- ftservo_ros в режиме симуляции
- Мост joint->motor (без реального железа)
- Опционально rds_2p_dance (джой может быть отключён)
- Без mtf02p, face/touchpad и прочего железа
- RViz НЕ запускается (можно запустить вручную при необходимости)
"""

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, ExecuteProcess
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node


def get_workspace_root():
    """Получить корень workspace (нужно для поиска venv)."""
    colcon_prefix = os.environ.get('COLCON_PREFIX_PATH', '')
    if colcon_prefix:
        install_dir = colcon_prefix.split(':')[0]
        return os.path.abspath(os.path.join(install_dir, '..', '..'))

    current_file = os.path.abspath(__file__)
    if 'install' in current_file:
        parts = current_file.split(os.sep)
        install_idx = next((i for i, p in enumerate(parts) if p == 'install'), None)
        if install_idx is not None:
            ros_packages_path = os.sep.join(parts[:install_idx])
            return os.path.abspath(os.path.join(ros_packages_path, '..'))
    return os.path.abspath(os.path.join(os.path.dirname(current_file), '..', '..', '..', '..'))


def generate_launch_description():
    # Пути пакетов
    ftservo_ros_pkg = FindPackageShare('ftservo_ros')
    rds_2p_pkg = FindPackageShare('rds_2p')
    rds_2p_dance_pkg = FindPackageShare('rds_2p_dance')

    # Поиск venv для MuJoCo twin (fallback на системный python3)
    workspace_root = get_workspace_root()
    venv_python = os.path.join(workspace_root, 'learning', 'export_inference', '.venv', 'bin', 'python3')
    if not os.path.exists(venv_python):
        venv_python = 'python3'

    # Конфиги по умолчанию
    ftservo_config_file = PathJoinSubstitution([
        ftservo_ros_pkg,
        'config',
        'config_example.yaml',
    ])
    rds_2p_offsets_config_file = PathJoinSubstitution([
        rds_2p_pkg,
        'config',
        'joint_offsets_example.yaml',
    ])

    # Пути к URDF / RViz
    rds_2p_share = Path(get_package_share_directory('rds_2p'))
    default_model_path = rds_2p_share / 'urdf' / 'rds-2p_description_wrapper.urdf.xacro'
    default_rviz_config = rds_2p_share / 'rviz' / 'robot_description.rviz'

    # Аргументы
    use_sim_time_arg = DeclareLaunchArgument('use_sim_time', default_value='true', description='Использовать сим-время')
    model_arg = DeclareLaunchArgument('model', default_value=str(default_model_path), description='Путь к xacro')
    # RViz не запускаем здесь; аргумент не нужен

    interface_arg = DeclareLaunchArgument('interface', default_value='/dev/ttyS7', description='Последовательный интерфейс (сим)')
    config_file_arg = DeclareLaunchArgument('config_file', default_value=ftservo_config_file, description='Файл конфигурации моторов')
    is_sim_arg = DeclareLaunchArgument('is_sim', default_value='true', description='Режим симуляции моторов')
    log_level_arg = DeclareLaunchArgument('log_level', default_value='ERROR', description='Уровень логов ftservo')

    headless_arg = DeclareLaunchArgument('headless', default_value='false', description='Запустить виртуальный твин без окна (headless)')

    offsets_config_file_arg = DeclareLaunchArgument('offsets_config_file', default_value=rds_2p_offsets_config_file, description='Файл смещений суставов')
    motor_command_rate_arg = DeclareLaunchArgument('motor_command_rate', default_value='50.0', description='Частота команд моторам (Гц)')
    verbose_logging_arg = DeclareLaunchArgument('verbose_logging', default_value='false', description='Подробный лог моста суставов')

    enable_dance_joy_arg = DeclareLaunchArgument('enable_dance_joy', default_value='false', description='Включить контроллер джойстика для танцев')
    dance_joy_log_level_arg = DeclareLaunchArgument('dance_joy_log_level', default_value='info', description='Уровень логов dance_joy_controller')

    # ftservo в режиме симуляции
    motor_controller_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                ftservo_ros_pkg,
                'launch',
                'motor_controller.launch.py',
            ])
        ]),
        launch_arguments={
            'interface': LaunchConfiguration('interface'),
            'config_file': LaunchConfiguration('config_file'),
            'is_sim': LaunchConfiguration('is_sim'),
            'log_level': LaunchConfiguration('log_level'),
        }.items(),
    )

    # Мост joint->motor (без физики)
    bridge_joints_to_motors_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                rds_2p_pkg,
                'launch',
                'bridge_joints_to_motors.launch.py',
            ])
        ]),
        launch_arguments={
            'offsets_config_file': LaunchConfiguration('offsets_config_file'),
            'motor_command_rate': LaunchConfiguration('motor_command_rate'),
            'verbose_logging': LaunchConfiguration('verbose_logging'),
        }.items(),
    )

    # Отображение: описание + RViz + TF
    # Описание робота (URDF)
    description_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                rds_2p_pkg,
                'launch',
                'description.launch.py',
            ])
        ]),
        launch_arguments={
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'model': LaunchConfiguration('model'),
        }.items(),
    )

    # IMU transform
    imu_transform_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                rds_2p_pkg,
                'launch',
                'imu_transform.launch.py',
            ])
        ]),
        launch_arguments={
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }.items(),
    )

    # Статический TF map->odom
    static_transform_node = Node(
        package='rds_2p',
        executable='static_transform_publisher',
        name='static_transform_publisher',
        output='screen',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }],
    )

    # Путь к скрипту виртуального двойника (установочный prefix)
    pkg_share = get_package_share_directory('rds_2p_inference')
    install_dir = os.path.dirname(os.path.dirname(os.path.dirname(pkg_share)))
    virtual_twin_script = os.path.join(install_dir, 'rds_2p_inference', 'lib', 'rds_2p_inference', 'virtual_twin_node.py')

    virtual_twin_node_gui = ExecuteProcess(
        cmd=[venv_python, virtual_twin_script],
        output='screen',
        shell=False,
        condition=UnlessCondition(LaunchConfiguration('headless')),
    )

    virtual_twin_node_headless = ExecuteProcess(
        cmd=[venv_python, virtual_twin_script, '--headless'],
        output='screen',
        shell=False,
        condition=IfCondition(LaunchConfiguration('headless')),
    )

    # Dance action server (не требует железа)
    dance_action_server = ExecuteProcess(
        cmd=['ros2', 'run', 'rds_2p_dance', 'dance_action_server'],
        output='screen',
        shell=False,
    )

    # Опциональный контроллер джойстика
    dance_joy_controller_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                rds_2p_dance_pkg,
                'launch',
                'dance_joy_controller.launch.py',
            ])
        ]),
        condition=IfCondition(LaunchConfiguration('enable_dance_joy')),
        launch_arguments={
            'log_level': LaunchConfiguration('dance_joy_log_level'),
        }.items(),
    )

    return LaunchDescription([
        # Аргументы
        use_sim_time_arg,
        model_arg,
        interface_arg,
        config_file_arg,
        is_sim_arg,
        log_level_arg,
        headless_arg,
        offsets_config_file_arg,
        motor_command_rate_arg,
        verbose_logging_arg,
        enable_dance_joy_arg,
        dance_joy_log_level_arg,

        # Узлы / launch include
        description_launch,
        imu_transform_launch,
        static_transform_node,
        motor_controller_launch,
        bridge_joints_to_motors_launch,
        virtual_twin_node_gui,
        virtual_twin_node_headless,
        dance_action_server,
        dance_joy_controller_launch,
    ])
