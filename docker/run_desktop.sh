#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-rds2p/desktop:humble}"
LAUNCH="${LAUNCH_OVERRIDE:-ros2 launch rds_2p_inference virtual_twin_desktop.launch.py}"

# Сеть DDS: дефолты проекта (domain 2 = как на рабочих машинах, Fast DDS = что реально стоит в образах).
# DDS_PROFILES_FILE — xml профиля активного rmw:
#   fastdds  (fastrtps) -> FASTRTPS_DEFAULT_PROFILES_FILE   (<profiles xmlns="...fastRTPS_Profiles">)
#   cyclonedds (cyclone) -> CYCLONEDDS_URI=file://            (<CycloneDDS><Domain>...)
DDS_PROFILES_FILE="${DDS_PROFILES_FILE:-}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-2}"
RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"

ARGS=(docker run --rm -i --network host --shm-size=1g
      -e "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
      -e "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION}")
if [ -t 0 ]; then ARGS+=(-t); fi

if [ -n "$DDS_PROFILES_FILE" ]; then
  if [ -f "$DDS_PROFILES_FILE" ]; then
    ARGS+=(-v "$DDS_PROFILES_FILE:/opt/rds2p/dds_profile.xml:ro"
           -e "FASTRTPS_DEFAULT_PROFILES_FILE=/opt/rds2p/dds_profile.xml"
           -e "CYCLONEDDS_URI=file:///opt/rds2p/dds_profile.xml")
  else
    echo "⚠️  DDS_PROFILES_FILE=$DDS_PROFILES_FILE не найден — профиль не подключён." >&2
  fi
fi

if [ -n "${DISPLAY:-}" ]; then
  ARGS+=(-e "DISPLAY=$DISPLAY")
  if [ -d /tmp/.X11-unix ]; then
    ARGS+=(-v /tmp/.X11-unix:/tmp/.X11-unix:rw)
  else
    echo "⚠️  /tmp/.X11-unix не найден — X11-сокет не примонтирован, GUI может не открыться."
  fi
fi
if [ -n "${WAYLAND_DISPLAY:-}" ] && [ -n "${XDG_RUNTIME_DIR:-}" ]; then
  ARGS+=(-e "WAYLAND_DISPLAY=$WAYLAND_DISPLAY"
         -e "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
         -v "$XDG_RUNTIME_DIR:$XDG_RUNTIME_DIR:rw")
fi
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "⚠️  DISPLAY и WAYLAND_DISPLAY оба не заданы — MuJoCo GUI не откроется."
  echo "   В WSLg должно быть DISPLAY=:0 (или WAYLAND_DISPLAY=wayland-0)."
  echo "   Если окно не появляется, выполните на хосте: xhost +local:"
fi

exec "${ARGS[@]}" "$IMAGE" "$LAUNCH"
