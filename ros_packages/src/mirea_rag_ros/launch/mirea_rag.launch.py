"""Запуск голосового RAG-помощника: транскрипция → RAG → TTS.

    # прежний HTTP RAG API (по умолчанию)
    ros2 launch mirea_rag_ros mirea_rag.launch.py

    # локальный стек: ROS OSM (system-one) + RKLLM action
    ros2 launch mirea_rag_ros mirea_rag.launch.py backend:=local

    # локальный стек целиком: ROS OSM + RKLLM + BM25 по bundle
    ros2 launch mirea_rag_ros mirea_rag.launch.py \
      backend:=local local_search_backend:=bundle
"""
import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    share = Path(get_package_share_directory("mirea_rag_ros"))
    env_file = os.environ.get(
        "MIREA_RAG_ENV",
        str(Path.home() / ".config" / "mirea_rag" / "mirea_rag.env"),
    )
    bundle = os.environ.get("MIREA_RAG_BUNDLE", str(share / "bundle"))

    topic = LaunchConfiguration("transcription_topic")
    service = LaunchConfiguration("speak_service")
    echo = LaunchConfiguration("speak_echo_seconds")
    volume = LaunchConfiguration("tts_volume")
    backend = LaunchConfiguration("backend")
    local_osm_service = LaunchConfiguration("local_osm_service")
    local_osm_service_type = LaunchConfiguration("local_osm_service_type")
    local_osm_model = LaunchConfiguration("local_osm_model")
    local_osm_timeout = LaunchConfiguration("local_osm_timeout")
    local_osm_max_state_chars = LaunchConfiguration(
        "local_osm_max_state_chars")
    local_llm_action = LaunchConfiguration("local_llm_action")
    local_llm_clear_kv_service = LaunchConfiguration(
        "local_llm_clear_kv_service")
    local_llm_keep_history = LaunchConfiguration("local_llm_keep_history")
    local_llm_clear_kv_before_query = LaunchConfiguration(
        "local_llm_clear_kv_before_query")
    local_llm_max_new_tokens = LaunchConfiguration(
        "local_llm_max_new_tokens")
    local_llm_system_prompt = LaunchConfiguration("local_llm_system_prompt")
    local_llm_wait_server_sec = LaunchConfiguration(
        "local_llm_wait_server_sec")
    local_llm_timeout = LaunchConfiguration("local_llm_timeout")
    local_bundle_dir = LaunchConfiguration("local_bundle_dir")
    local_search_backend = LaunchConfiguration("local_search_backend")

    return LaunchDescription([
        DeclareLaunchArgument("transcription_topic",
                              default_value="/audio/input/transcription"),
        DeclareLaunchArgument("speak_service",
                              default_value="/audio/output/speak"),
        DeclareLaunchArgument("speak_echo_seconds", default_value="3.0"),
        DeclareLaunchArgument("tts_volume", default_value="3.0"),

        DeclareLaunchArgument(
            "backend",
            default_value=os.environ.get("MIREA_RAG_BACKEND", "api"),
            description="api (HTTP RAG API) | local (ROS OSM + RKLLM)"),
        DeclareLaunchArgument(
            "local_osm_service", default_value="",
            description="Сервис OSM; пусто — авто (/system_one_client/ask "
                        "или /system_one/systemone)"),
        DeclareLaunchArgument(
            "local_osm_service_type", default_value="auto",
            description="auto | ask | systemone"),
        DeclareLaunchArgument("local_osm_model", default_value="kev-0.8b"),
        DeclareLaunchArgument("local_osm_timeout", default_value="5.0"),
        DeclareLaunchArgument("local_osm_max_state_chars", default_value="0",
                              description="0 — потолок по модели"),
        DeclareLaunchArgument("local_llm_action",
                              default_value="/rkllm_ros/complete"),
        DeclareLaunchArgument(
            "local_llm_clear_kv_service",
            default_value="/rkllm_ros/clear_kv_cache"),
        DeclareLaunchArgument("local_llm_keep_history", default_value="true"),
        DeclareLaunchArgument(
            "local_llm_clear_kv_before_query", default_value="false"),
        DeclareLaunchArgument("local_llm_max_new_tokens", default_value="0"),
        DeclareLaunchArgument(
            "local_llm_system_prompt", default_value="",
            description="Пусто — встроенная персона панады"),
        DeclareLaunchArgument("local_llm_wait_server_sec",
                              default_value="5.0"),
        DeclareLaunchArgument("local_llm_timeout", default_value="180.0"),
        DeclareLaunchArgument(
            "local_bundle_dir",
            default_value=os.environ.get("MIREA_RAG_BUNDLE", ""),
            description="Путь к bundle; пусто — share/mirea_rag_ros/bundle"),
        DeclareLaunchArgument(
            "local_search_backend", default_value="bundle",
            description="bundle/bm25 — локальный BM25; api — удалённый "
                        "/search; none — без ретривала"),

        Node(
            package="mirea_rag_ros",
            executable="mirea_rag_node",
            name="mirea_rag",
            output="screen",
            additional_env={
                "MIREA_RAG_ENV": env_file,
                "MIREA_RAG_BUNDLE": bundle,
            },
            parameters=[{
                "transcription_topic": topic,
                "speak_service": service,
                "speak_echo_seconds": ParameterValue(
                    echo, value_type=float),
                "backend": backend,
                "local_osm_service": local_osm_service,
                "local_osm_service_type": local_osm_service_type,
                "local_osm_model": local_osm_model,
                "local_osm_timeout": ParameterValue(
                    local_osm_timeout, value_type=float),
                "local_osm_max_state_chars": ParameterValue(
                    local_osm_max_state_chars, value_type=int),
                "local_llm_action": local_llm_action,
                "local_llm_clear_kv_service": local_llm_clear_kv_service,
                "local_llm_keep_history": ParameterValue(
                    local_llm_keep_history, value_type=bool),
                "local_llm_clear_kv_before_query": ParameterValue(
                    local_llm_clear_kv_before_query, value_type=bool),
                "local_llm_max_new_tokens": ParameterValue(
                    local_llm_max_new_tokens, value_type=int),
                "local_llm_system_prompt": local_llm_system_prompt,
                "local_llm_wait_server_sec": ParameterValue(
                    local_llm_wait_server_sec, value_type=float),
                "local_llm_timeout": ParameterValue(
                    local_llm_timeout, value_type=float),
                "local_bundle_dir": local_bundle_dir,
                "local_search_backend": local_search_backend,
            }],
        ),
    ])
