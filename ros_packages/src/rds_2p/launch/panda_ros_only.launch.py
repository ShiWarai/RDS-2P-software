"""ROS-only стек панды: voice_system + commands_system + RAG (local) + база моторов.

Запускать вместо ``voice-control.service`` (он держит микрофон/динамик/ttysS7)::

    sudo systemctl stop voice-control.service
    ros2 launch rds_2p panda_ros_only.launch.py

Что поднимается:
  * virtual_twin_sim — motor_controller + bridge + MuJoCo-твин; он же даёт
    /imu и /joint_states, как в старом «бегать»;
  * inference_node — политика ходьбы (как rds_2p_inference_node.service);
  * rds_2p voice_system — audio + GigaAM + Paroli + lip_sync;
  * rkllm_ros — локальная LLM; system_one_ros — локальный OSM;
  * rds_2p_commands commands_system — команды всегда, на /audio/transcription;
  * mirea_rag_ros — RAG+LLM на том же топике, но команды он игнорирует.

RAG можно временно заблокировать/разблокировать сервисом::

    ros2 service call /mirea_rag/enable std_srvs/srv/SetBool "{data: false}"

Контейнер system-one-rknn должен быть поднят заранее
(``ros2 run rkllm_ros system_one_docker.sh run``).
"""
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    share_rag = Path(get_package_share_directory("mirea_rag_ros"))
    ftservo_config = PathJoinSubstitution([
        FindPackageShare("ftservo_ros"), "config", "config_example.yaml"])
    offsets_config = PathJoinSubstitution([
        FindPackageShare("rds_2p"), "config", "joint_offsets_example.yaml"])
    bundle = LaunchConfiguration("local_bundle_dir")

    return LaunchDescription([
        DeclareLaunchArgument(
            "stt", default_value="gigaam",
            description="STT для voice_system: gigaam | vosk"),
        DeclareLaunchArgument("capturer_device", default_value="-1"),
        DeclareLaunchArgument("vad_enabled", default_value="false"),
        DeclareLaunchArgument("denoise", default_value="none"),
        DeclareLaunchArgument("interface", default_value="/dev/ttyS7"),
        DeclareLaunchArgument("is_sim", default_value="false"),
        DeclareLaunchArgument(
            "include_base", default_value="true",
            description="Поднимать virtual_twin_sim (motor_controller, bridge, "
                        "MuJoCo: /imu + /joint_states)"),
        DeclareLaunchArgument(
            "include_inference", default_value="true",
            description="Поднимать inference policy (как rds_2p_inference_node.service)"),
        DeclareLaunchArgument(
            "require_control_input", default_value="true",
            description="Inference не едет без свежего /cmd_vel и active cmd_vel_mux"),
        DeclareLaunchArgument(
            "control_timeout_sec", default_value="0.5"),
        DeclareLaunchArgument(
            "encoder_model_path",
            default_value="/home/orangepi/models/qwen3.5-2b-rkllm-rk3588/"
                          "qwen3.5-2b_vision_rk3588.rknn"),
        DeclareLaunchArgument(
            "llm_model_path",
            default_value="/home/orangepi/models/qwen3.5-2b-rkllm-rk3588/"
                          "qwen3.5-2b_w8a8_rk3588.rkllm"),
        DeclareLaunchArgument(
            "system_one_url", default_value="http://127.0.0.1:18477"),
        DeclareLaunchArgument(
            "rag_enabled", default_value="true",
            description="Начальное состояние входа RAG (сервис /mirea_rag/enable)"),
        DeclareLaunchArgument(
            "local_search_backend", default_value="bundle",
            description="bundle — локальный BM25; api — удалённый /search"),
        DeclareLaunchArgument(
            "local_bundle_dir", default_value=str(share_rag / "bundle")),
        DeclareLaunchArgument(
            "rag_config", default_value="commands.yaml",
            description="commands.yaml для фильтра команд в RAG"),

        # --- база: моторы + MuJoCo (/imu, /joint_states) + face/joystick ----
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare("rds_2p_inference"), "launch",
                    "virtual_twin_sim.launch.py"])]),
            launch_arguments={
                "interface": LaunchConfiguration("interface"),
                "config_file": ftservo_config,
                "offsets_config_file": offsets_config,
                "is_sim": LaunchConfiguration("is_sim"),
                "log_level": "info",
            }.items(),
            condition=IfCondition(LaunchConfiguration("include_base")),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare("rds_2p_inference"), "launch",
                    "inference_node.launch.py"])]),
            launch_arguments={
                "require_control_input": LaunchConfiguration(
                    "require_control_input"),
                "control_timeout_sec": LaunchConfiguration(
                    "control_timeout_sec"),
            }.items(),
            condition=IfCondition(LaunchConfiguration("include_inference")),
        ),

        # --- голос/LLM/OSM --------------------------------------------------
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare("rds_2p"), "launch",
                    "voice_system.launch.py"])]),
            launch_arguments={
                "stt": LaunchConfiguration("stt"),
                "capturer_device": LaunchConfiguration("capturer_device"),
                "vad_enabled": LaunchConfiguration("vad_enabled"),
                "denoise": LaunchConfiguration("denoise"),
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare("rkllm_ros"), "launch",
                    "rkllm.launch.py"])]),
            launch_arguments={
                "encoder_model_path": LaunchConfiguration("encoder_model_path"),
                "llm_model_path": LaunchConfiguration("llm_model_path"),
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare("system_one_ros"), "launch",
                    "system_one.launch.py"])]),
            launch_arguments={
                "server_url": LaunchConfiguration("system_one_url"),
            }.items(),
        ),

        # --- команды (всегда) ----------------------------------------------
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare("rds_2p_commands"), "launch",
                    "commands_system.launch.py"])]),
            launch_arguments={
                "transcription_topics": "['/audio/transcription']",
                "command_debounce_sec": "3.0",
                "panda_llm_tts_enabled": "false",
            }.items(),
        ),

        # --- RAG на том же входе, команды фильтруются -----------------------
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    FindPackageShare("mirea_rag_ros"), "launch",
                    "mirea_rag.launch.py"])]),
            launch_arguments={
                "backend": "local",
                "transcription_topic": "/audio/transcription",
                "rag_enabled": LaunchConfiguration("rag_enabled"),
                "enable_service": "/mirea_rag/enable",
                "ignore_command_keywords": "true",
                "commands_config": LaunchConfiguration("rag_config"),
                "local_search_backend": LaunchConfiguration(
                    "local_search_backend"),
                "local_bundle_dir": bundle,
                "local_llm_clear_kv_before_query": "false",
            }.items(),
        ),
    ])
