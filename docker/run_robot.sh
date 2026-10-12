#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-rds2p/robot:humble}"
MODELS_DIR="${MODELS_DIR:-$HOME/RDS-2P-models}"
LAUNCH="${LAUNCH_OVERRIDE:-ros2 launch rds_2p rds_2p_complete.launch.py}"

if [ ! -d "$MODELS_DIR" ]; then
  echo "⚠️  MODELS_DIR=$MODELS_DIR не существует — создаём пустой (модели монтируются в /models)."
  mkdir -p "$MODELS_DIR"
fi

# Закомментированный вариант точечных прав вместо --privileged (будущий hardening):
# docker run --rm -it --network host --shm-size=4g \
#   --device /dev/ttyS7 --device /dev/video0 \
#   --cap-add NET_ADMIN --cap-add SYS_ADMIN \
#   --group-add audio --group-add input --group-add video \
#   --device /dev/rga --device /dev/mpp_service --device /dev/dri/renderD128 \
#   --device /dev/snd ...

ARGS=(docker run --rm -i --network host --privileged --shm-size=4g
      --group-add audio
      -v "$MODELS_DIR:/models:ro")
if [ -t 0 ]; then ARGS+=(-t); fi

if [ -n "${RKLLM_MODEL:-}" ]; then
  ARGS+=(-e "RKLLM_MODEL=/models/$(basename "$RKLLM_MODEL")")
fi
if [ -n "${RKNN_ENCODER_MODEL:-}" ]; then
  ARGS+=(-e "RKNN_ENCODER_MODEL=/models/$(basename "$RKNN_ENCODER_MODEL")")
fi

exec "${ARGS[@]}" "$IMAGE" "$LAUNCH"
