#!/usr/bin/env python3
"""
Компактный пресет «Команды Панды»: классификация через system_one_ros.

panda_commands исполняет then-цепочку (PandaCommand / cmd_vel / Paroli).
Запускает:
- system_one_ros/system_one.launch.py — нативный Kev-0.8B на NPU (/system_one/ask);
- unified_action_server — исполнитель PandaCommand;
- panda_commands — классификация и сценарий.

Командный парсер (command_parser) не нужен: routine_id отправляются напрямую.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    args = [
        DeclareLaunchArgument(
            'mode', default_value='native',
            description='native — Kev в ROS 2 ноде; http — клиент контейнера'),
        DeclareLaunchArgument(
            'model_root', default_value='/home/orangepi/models/kev-0.8b-rknn',
            description='Каталог Kev для native'),
        DeclareLaunchArgument(
            'rkllm_lib', default_value='/opt/npu/librkllmrt-1.3.1.so'),
        DeclareLaunchArgument(
            'rknpu_lib', default_value='/opt/npu/librknnrt-2.3.2.so'),
        DeclareLaunchArgument(
            'server_url', default_value='http://127.0.0.1:18477',
            description='HTTP API system-one-rknn (только mode=http)'),
        DeclareLaunchArgument(
            'include_system_one', default_value='true',
            description='Поднимать system_one_ros/system_one.launch.py'),
        DeclareLaunchArgument(
            'include_action_server', default_value='true',
            description='Поднимать unified_action_server (PandaCommand)'),
        DeclareLaunchArgument(
            'config_file', default_value='panda_commands.yaml',
            description='Сценарий в share/rds_2p_commands/config/'),
        DeclareLaunchArgument(
            'input_topic', default_value='/audio/input/transcription',
            description='Топик rds_2p_audio/Transcription'),
        DeclareLaunchArgument(
            'system_one_service', default_value='/system_one/ask',
            description='Сервис llm_msgs_ros/srv/Ask'),
        DeclareLaunchArgument(
            'model', default_value='kev-0.8b',
            description='Модель system-one'),
        DeclareLaunchArgument(
            'min_confidence', default_value='0.0',
            description='Порог уверенности choice (0 = выключен)'),
        DeclareLaunchArgument(
            'timeout_sec', default_value='30.0',
            description='Таймаут HTTP-запроса классификации, с'),
        DeclareLaunchArgument(
            'panda_action', default_value='/robot/panda_command',
            description='Action rds_2p_commands/PandaCommand'),
        DeclareLaunchArgument(
            'speak_service', default_value='/audio/output/speak',
            description='Сервис rds_2p_audio/Speak'),
        DeclareLaunchArgument(
            'say_enabled', default_value='true',
            description='Выполнять шаги say'),
        DeclareLaunchArgument(
            'publish_cmd_vel', default_value='true',
            description='Публиковать motion_commands в /cmd_vel/voice'),
        DeclareLaunchArgument(
            'cmd_vel_topic', default_value='/cmd_vel/voice',
            description='Топик geometry_msgs/Twist для шагов (вход cmd_vel_mux)'),
        DeclareLaunchArgument(
            'dry_run', default_value='false',
            description='Только классифицировать, не выполнять команды'),
        DeclareLaunchArgument(
            'post_action_cooldown_sec', default_value='1.5',
            description='Пауза после сценария, чтобы не слушать своё эхо'),
        DeclareLaunchArgument(
            'interrupt_keywords', default_value='стоп,хватит',
            description='Фразы прерывания текущего сценария через запятую'),
        DeclareLaunchArgument(
            'log_level', default_value='info',
            description='Уровень логирования: debug, info, warn, error, fatal'),
    ]

    system_one_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            get_package_share_directory('system_one_ros'),
            '/launch/system_one.launch.py',
        ]),
        condition=IfCondition(LaunchConfiguration('include_system_one')),
        launch_arguments={
            'mode': LaunchConfiguration('mode'),
            'model_root': LaunchConfiguration('model_root'),
            'rkllm_lib': LaunchConfiguration('rkllm_lib'),
            'rknpu_lib': LaunchConfiguration('rknpu_lib'),
            'server_url': LaunchConfiguration('server_url'),
        }.items(),
    )

    action_server_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            get_package_share_directory('rds_2p_commands'),
            '/launch/unified_action_server.launch.py',
        ]),
        condition=IfCondition(LaunchConfiguration('include_action_server')),
        launch_arguments={
            'log_level': LaunchConfiguration('log_level'),
        }.items(),
    )

    panda_commands_node = Node(
        package='rds_2p_commands',
        executable='panda_commands',
        name='panda_commands',
        output='screen',
        parameters=[{
            'config_file': LaunchConfiguration('config_file'),
            'input_topic': LaunchConfiguration('input_topic'),
            'system_one_service': LaunchConfiguration('system_one_service'),
            'model': LaunchConfiguration('model'),
            'min_confidence': ParameterValue(
                LaunchConfiguration('min_confidence'), value_type=float),
            'timeout_sec': ParameterValue(
                LaunchConfiguration('timeout_sec'), value_type=float),
            'panda_action': LaunchConfiguration('panda_action'),
            'speak_service': LaunchConfiguration('speak_service'),
            'say_enabled': ParameterValue(
                LaunchConfiguration('say_enabled'), value_type=bool),
            'publish_cmd_vel': ParameterValue(
                LaunchConfiguration('publish_cmd_vel'), value_type=bool),
            'cmd_vel_topic': LaunchConfiguration('cmd_vel_topic'),
            'dry_run': ParameterValue(
                LaunchConfiguration('dry_run'), value_type=bool),
            'post_action_cooldown_sec': ParameterValue(
                LaunchConfiguration('post_action_cooldown_sec'), value_type=float),
            'interrupt_keywords': LaunchConfiguration('interrupt_keywords'),
        }],
        arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
        emulate_tty=True,
    )

    return LaunchDescription([
        *args,
        system_one_launch,
        action_server_launch,
        panda_commands_node,
    ])
