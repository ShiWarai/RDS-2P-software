#!/usr/bin/env python3
"""Launch rkllm_ros2: пути к моделям задаются явно (пустые по умолчанию — узел не стартует)."""

import os

from ament_index_python.packages import get_package_prefix

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _vendor_ld_library_path():
    """Первым ищем librkllmrt/librknnrt из префикса пакета (обходит старый LD_LIBRARY_PATH)."""
    vendor_lib = os.path.join(
        get_package_prefix('rkllm_ros2'), 'lib', 'rkllm_ros2', 'vendor', 'lib')
    prev = os.environ.get('LD_LIBRARY_PATH', '')
    return vendor_lib + (':' + prev if prev else '')


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'encoder_model_path',
            default_value='',
            description='Путь к vision encoder (.rknn)',
        ),
        DeclareLaunchArgument(
            'llm_model_path',
            default_value='',
            description='Путь к LLM (.rkllm)',
        ),
        DeclareLaunchArgument('max_new_tokens', default_value='2048'),
        DeclareLaunchArgument('max_context_len', default_value='4096'),
        DeclareLaunchArgument('rknn_core_num', default_value='3'),
        DeclareLaunchArgument('img_start', default_value='<|vision_start|>'),
        DeclareLaunchArgument('img_end', default_value='<|vision_end|>'),
        DeclareLaunchArgument('img_content', default_value='<|image_pad|>'),
        DeclareLaunchArgument(
            'top_k',
            default_value='20',
            description='Top-K (дефолт как generation_config Qwen3-VL-2B-Instruct на HF)',
        ),
        DeclareLaunchArgument(
            'top_p',
            default_value='0.8',
            description='Top-P (дефолт как generation_config Qwen3-VL-2B-Instruct на HF)',
        ),
        DeclareLaunchArgument(
            'temperature',
            default_value='0.7',
            description='Temperature RKLLMParam (дефолт как HF generation_config)',
        ),
        DeclareLaunchArgument(
            'repeat_penalty',
            default_value='1.0',
            description='repeat_penalty RKLLMParam (HF: repetition_penalty)',
        ),
        DeclareLaunchArgument(
            'frequency_penalty',
            default_value='0.0',
            description='frequency_penalty RKLLMParam (часто 0 в demo)',
        ),
        DeclareLaunchArgument(
            'presence_penalty',
            default_value='0.0',
            description='presence_penalty RKLLMParam',
        ),
        DeclareLaunchArgument(
            'persist_session_kv',
            default_value='true',
            description='true: как demo — keep_history всегда в infer, сброс KV только ~/clear_kv_cache; false: legacy по goal.keep_history',
        ),
        DeclareLaunchArgument(
            'clear_kv_after_idle_sec',
            default_value='0',
            description='Авто-сброс KV через N секунд после последнего завершённого запроса (goal). 0 = отключено.',
        ),
        DeclareLaunchArgument(
            'apply_chat_template',
            default_value='false',
            description='true: rkllm_set_chat_template (отключает встроенный шаблон .rkllm); false: шаблон модели',
        ),
        DeclareLaunchArgument(
            'system_prompt',
            default_value='',
            description='Строка system для rkllm_set_chat_template: пробрасывается в chat_template_system (если пусто — дефолт ноды). Имеет смысл при apply_chat_template:=true.',
        ),
        DeclareLaunchArgument('text_chunk_topic', default_value='text_chunks'),
        DeclareLaunchArgument('text_topic', default_value='text'),
        Node(
            package='rkllm_ros2',
            executable='rkllm_node',
            name='rkllm_ros2',
            output='screen',
            additional_env={'LD_LIBRARY_PATH': _vendor_ld_library_path()},
            parameters=[{
                'encoder_model_path': LaunchConfiguration('encoder_model_path'),
                'llm_model_path': LaunchConfiguration('llm_model_path'),
                'max_new_tokens': ParameterValue(
                    LaunchConfiguration('max_new_tokens'), value_type=int),
                'max_context_len': ParameterValue(
                    LaunchConfiguration('max_context_len'), value_type=int),
                'rknn_core_num': ParameterValue(
                    LaunchConfiguration('rknn_core_num'), value_type=int),
                'img_start': LaunchConfiguration('img_start'),
                'img_end': LaunchConfiguration('img_end'),
                'img_content': LaunchConfiguration('img_content'),
                'top_k': ParameterValue(LaunchConfiguration('top_k'), value_type=int),
                'top_p': ParameterValue(LaunchConfiguration('top_p'), value_type=float),
                'temperature': ParameterValue(
                    LaunchConfiguration('temperature'), value_type=float),
                'repeat_penalty': ParameterValue(
                    LaunchConfiguration('repeat_penalty'), value_type=float),
                'frequency_penalty': ParameterValue(
                    LaunchConfiguration('frequency_penalty'), value_type=float),
                'presence_penalty': ParameterValue(
                    LaunchConfiguration('presence_penalty'), value_type=float),
                'persist_session_kv': ParameterValue(
                    LaunchConfiguration('persist_session_kv'), value_type=bool),
                'clear_kv_after_idle_sec': ParameterValue(
                    LaunchConfiguration('clear_kv_after_idle_sec'), value_type=float),
                'apply_chat_template': ParameterValue(
                    LaunchConfiguration('apply_chat_template'), value_type=bool),
                'chat_template_system': LaunchConfiguration('system_prompt'),
                'text_chunk_topic': LaunchConfiguration('text_chunk_topic'),
                'text_topic': LaunchConfiguration('text_topic'),
            }],
        ),
    ])
