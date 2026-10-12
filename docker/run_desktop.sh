#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-rds2p/desktop:humble}"
LAUNCH="${LAUNCH_OVERRIDE:-ros2 launch rds_2p_inference virtual_twin_desktop.launch.py}"

ARGS=(docker run --rm -i --network host --shm-size=1g)
if [ -t 0 ]; then ARGS+=(-t); fi

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
