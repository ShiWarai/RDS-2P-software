#!/usr/bin/env python3
"""Orbbec Astra Mini через ``orbbec_camera`` (пакет Orbbec SDK ROS2).

Пресет **``stream_profile``**:

- **``default``** — полный набор по аргументам ниже (depth, point cloud и т.д. по умолчанию).
- **``rgb_only``** — только цвет: глубина, IR, point cloud выключены.
- **``rgb_depth``** — цвет + глубина без IR и без point cloud.

Готовые профили: ``astra_mini_rgb.launch.py``, ``astra_mini_rgb_depth.launch.py`` (thin include
с ``stream_profile``). Для тонкой настройки с параметрами удобнее:
``ros2 launch rds_2p astra_mini.launch.py stream_profile:=rgb_only``.
"""

from __future__ import annotations

import os
from typing import Any, Sequence

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node, PushRosNamespace
from launch_ros.descriptions import ComposableNode


def declare_camera_launch_arguments(include_stream_profile: bool) -> list[DeclareLaunchArgument]:
    decls = [
        DeclareLaunchArgument(
            "stream_profile",
            default_value="default",
            description=(
                "default — полный пресет из аргументов ниже (point cloud и т.д. по умолчанию). "
                "rgb_only — только RGB; rgb_depth — RGB + глубина (без IR / point cloud)."
            ),
        )
        if include_stream_profile
        else None,
        DeclareLaunchArgument("camera_name", default_value="camera"),
        DeclareLaunchArgument("depth_registration", default_value="false"),
        DeclareLaunchArgument("serial_number", default_value=""),
        DeclareLaunchArgument("usb_port", default_value=""),
        DeclareLaunchArgument("device_num", default_value="1"),
        DeclareLaunchArgument("vendor_id", default_value="0x2bc5"),
        DeclareLaunchArgument("product_id", default_value=""),
        DeclareLaunchArgument("enable_point_cloud", default_value="true"),
        DeclareLaunchArgument("enable_colored_point_cloud", default_value="false"),
        DeclareLaunchArgument("cloud_frame_id", default_value=""),
        DeclareLaunchArgument("point_cloud_qos", default_value="default"),
        DeclareLaunchArgument("connection_delay", default_value="100"),
        DeclareLaunchArgument("color_width", default_value="640"),
        DeclareLaunchArgument("color_height", default_value="480"),
        DeclareLaunchArgument("color_fps", default_value="30"),
        DeclareLaunchArgument("color_format", default_value="RGB888"),
        DeclareLaunchArgument("enable_color", default_value="true"),
        DeclareLaunchArgument("flip_color", default_value="false"),
        DeclareLaunchArgument("color_qos", default_value="default"),
        DeclareLaunchArgument("color_camera_info_qos", default_value="default"),
        DeclareLaunchArgument(
            "enable_color_auto_exposure", default_value="true"
        ),
        DeclareLaunchArgument("color_exposure", default_value="-1"),
        DeclareLaunchArgument("color_gain", default_value="-1"),
        DeclareLaunchArgument(
            "enable_color_auto_white_balance", default_value="true"
        ),
        DeclareLaunchArgument("color_white_balance", default_value="-1"),
        DeclareLaunchArgument("depth_width", default_value="640"),
        DeclareLaunchArgument("depth_height", default_value="480"),
        DeclareLaunchArgument("depth_fps", default_value="30"),
        DeclareLaunchArgument("depth_format", default_value="Y11"),
        DeclareLaunchArgument("enable_depth", default_value="true"),
        DeclareLaunchArgument("flip_depth", default_value="false"),
        DeclareLaunchArgument("depth_qos", default_value="default"),
        DeclareLaunchArgument("depth_camera_info_qos", default_value="default"),
        DeclareLaunchArgument("ir_width", default_value="640"),
        DeclareLaunchArgument("ir_height", default_value="480"),
        DeclareLaunchArgument("ir_fps", default_value="10"),
        DeclareLaunchArgument("ir_format", default_value="Y10"),
        DeclareLaunchArgument("enable_ir", default_value="false"),
        DeclareLaunchArgument("flip_ir", default_value="false"),
        DeclareLaunchArgument("ir_qos", default_value="default"),
        DeclareLaunchArgument("ir_camera_info_qos", default_value="default"),
        DeclareLaunchArgument("enable_ir_auto_exposure", default_value="true"),
        DeclareLaunchArgument("ir_exposure", default_value="-1"),
        DeclareLaunchArgument("ir_gain", default_value="-1"),
        DeclareLaunchArgument("publish_tf", default_value="true"),
        DeclareLaunchArgument("tf_publish_rate", default_value="0.0"),
        DeclareLaunchArgument("ir_info_url", default_value=""),
        DeclareLaunchArgument("color_info_url", default_value=""),
        DeclareLaunchArgument("log_level", default_value="none"),
        DeclareLaunchArgument("enable_publish_extrinsic", default_value="false"),
        DeclareLaunchArgument("enable_d2c_viewer", default_value="false"),
        DeclareLaunchArgument("enable_ldp", default_value="true"),
        DeclareLaunchArgument("enable_soft_filter", default_value="true"),
        DeclareLaunchArgument("soft_filter_max_diff", default_value="-1"),
        DeclareLaunchArgument("soft_filter_speckle_size", default_value="-1"),
        DeclareLaunchArgument("ordered_pc", default_value="false"),
        DeclareLaunchArgument("use_hardware_time", default_value="false"),
        DeclareLaunchArgument("enable_depth_scale", default_value="true"),
        DeclareLaunchArgument("align_mode", default_value="HW"),
        DeclareLaunchArgument("laser_energy_level", default_value="-1"),
        DeclareLaunchArgument("enable_heartbeat", default_value="false"),
    ]
    return [d for d in decls if d is not None]


def _camera_param_keys(decls: Sequence[DeclareLaunchArgument]) -> tuple[str, ...]:
    return tuple(d.name for d in decls if d.name != "stream_profile")


_PROFILE_PATCH: dict[str, dict[str, str]] = {
    "rgb_only": {
        "enable_color": "true",
        "enable_depth": "false",
        "enable_ir": "false",
        "enable_point_cloud": "false",
        "enable_colored_point_cloud": "false",
    },
    "rgb_depth": {
        "enable_color": "true",
        "enable_depth": "true",
        "enable_ir": "false",
        "enable_point_cloud": "false",
        "enable_colored_point_cloud": "false",
    },
}


def _merge_camera_parameters(
    lc: dict[str, str], keys: Sequence[str], profile_raw: str
) -> dict[str, str]:
    params = {k: lc[k] for k in keys}
    profile = profile_raw.strip().lower()
    if profile == "default":
        return params
    patch = _PROFILE_PATCH.get(profile)
    if patch is None:
        raise RuntimeError(
            f"stream_profile '{profile_raw}' не поддерживается. "
            "Допустимо: default, rgb_only, rgb_depth."
        )
    params.update(patch)
    return params


# В ``OpaqueFunction`` все значения — строки; ``orbbec_camera`` задаёт параметры через
# ``declare_parameter<int/double/bool>`` и проверку типов — строки недопустимы.
_BOOL_KEYS = frozenset({
    "depth_registration",
    "enable_point_cloud",
    "enable_colored_point_cloud",
    "enable_color",
    "flip_color",
    "enable_color_auto_exposure",
    "enable_color_auto_white_balance",
    "enable_depth",
    "flip_depth",
    "enable_ir",
    "flip_ir",
    "enable_ir_auto_exposure",
    "publish_tf",
    "enable_publish_extrinsic",
    "enable_d2c_viewer",
    "enable_ldp",
    "enable_soft_filter",
    "ordered_pc",
    "use_hardware_time",
    "enable_depth_scale",
    "enable_heartbeat",
})
_FLOAT_KEYS = frozenset({"tf_publish_rate"})
_INT_KEYS = frozenset({
    "connection_delay",
    "device_num",
    "color_width",
    "color_height",
    "color_fps",
    "color_exposure",
    "color_gain",
    "color_white_balance",
    "depth_width",
    "depth_height",
    "depth_fps",
    "ir_width",
    "ir_height",
    "ir_fps",
    "ir_exposure",
    "ir_gain",
    "soft_filter_max_diff",
    "soft_filter_speckle_size",
    "laser_energy_level",
})
_STR_KEYS = frozenset({
    "camera_name",
    "serial_number",
    "usb_port",
    "vendor_id",
    "product_id",
    "cloud_frame_id",
    "point_cloud_qos",
    "color_format",
    "color_qos",
    "color_camera_info_qos",
    "depth_format",
    "depth_qos",
    "depth_camera_info_qos",
    "ir_format",
    "ir_qos",
    "ir_camera_info_qos",
    "ir_info_url",
    "color_info_url",
    "log_level",
    "align_mode",
})


def _launch_bool(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "on")


def _ros2_typed_camera_params(flat: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, raw in flat.items():
        if k in _BOOL_KEYS:
            out[k] = _launch_bool(raw)
        elif k in _FLOAT_KEYS:
            out[k] = float(raw)
        elif k in _INT_KEYS:
            out[k] = int(float(raw))
        elif k in _STR_KEYS:
            out[k] = raw
        else:
            out[k] = raw
    return out


def generate_launch_description():
    declarations = declare_camera_launch_arguments(include_stream_profile=True)
    param_keys = _camera_param_keys(declarations)

    def _opaque_spawn(context, *_args, **_kwargs):
        lc = context.launch_configurations
        merged = _merge_camera_parameters(lc, param_keys, lc["stream_profile"])
        typed = _ros2_typed_camera_params(merged)
        ros_distro = os.environ.get("ROS_DISTRO", "humble")

        parameters_payload = [typed]

        if ros_distro == "foxy":
            return [
                Node(
                    package="orbbec_camera",
                    executable="orbbec_camera_node",
                    name="ob_camera_node",
                    namespace=LaunchConfiguration("camera_name"),
                    parameters=parameters_payload,
                    output="screen",
                )
            ]

        camera_name_lit = lc["camera_name"]

        compose_node = ComposableNode(
            package="orbbec_camera",
            plugin="orbbec_camera::OBCameraNodeDriver",
            name=camera_name_lit,
            namespace="",
            parameters=parameters_payload,
        )

        container = ComposableNodeContainer(
            name="camera_container",
            namespace="",
            package="rclcpp_components",
            executable="component_container",
            composable_node_descriptions=[compose_node],
            output="screen",
        )

        return [
            GroupAction(
                actions=[
                    PushRosNamespace(LaunchConfiguration("camera_name")),
                    container,
                ]
            ),
        ]

    return LaunchDescription(declarations + [OpaqueFunction(function=_opaque_spawn)])
