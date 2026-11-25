#!/usr/bin/env python3
"""
Launch файл для узла inference RDS-2P.

Этот launch файл запускает узел inference, который:
- Подписывается на /joint_states, /imu, /cmd_vel и /cmd_vel_mux/active
- Выполняет ONNX inference
- Публикует команды суставов в /joint_commands с частотой 50Hz
"""

from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    # Declare arguments
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation time if true'
    )
    require_control_arg = DeclareLaunchArgument(
        'require_control_input',
        default_value='true',
        description='Не запускать походку без свежего /cmd_vel и active cmd_vel_mux'
    )
    control_timeout_arg = DeclareLaunchArgument(
        'control_timeout_sec',
        default_value='0.5',
        description='Сколько секунд без /cmd_vel и cmd_vel_mux/active считать '
                    'управление потерянным'
    )

    # Create inference node
    inference_node = Node(
        package='rds_2p_inference',
        executable='inference_node',
        name='rds2p_inference',
        output='screen',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'require_control_input': ParameterValue(
                LaunchConfiguration('require_control_input'), value_type=bool),
            'control_timeout_sec': ParameterValue(
                LaunchConfiguration('control_timeout_sec'), value_type=float),
        }],
        emulate_tty=True
    )

    return LaunchDescription([
        use_sim_time_arg,
        require_control_arg,
        control_timeout_arg,
        inference_node
    ])
