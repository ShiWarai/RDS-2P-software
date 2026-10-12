#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ROSPKG="$ROOT_DIR/ros_packages"

IMAGE="${IMAGE:-rds2p/robot:humble}"

clone_if_missing() {
  local dir="$1" url="$2" branch="${3:-}"
  if [ ! -d "$dir" ] || [ -z "$(ls -A "$dir" 2>/dev/null)" ]; then
    echo "📥 Клонируем $dir"
    rm -rf "$dir"
    mkdir -p "$(dirname "$dir")"
    if [ -n "$branch" ]; then
      git clone -b "$branch" "$url" "$dir"
    else
      git clone "$url" "$dir"
    fi
  else
    echo "ℹ️ $dir уже существует"
  fi
}

ARCH="$(uname -m)"
if [ "$ARCH" != "aarch64" ] && [ "${ALLOW_CROSS:-0}" != "1" ]; then
  echo "❌ Архитектура хоста: $ARCH. robot-образ собирается нативно на роботе (aarch64)."
  echo "   На другом хосте: ALLOW_CROSS=1 (нужен эммулятор/buildx) — медленно, не рекомендуется."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "❌ Docker daemon недоступен. Проверьте: sudo systemctl start docker / группы docker."
  exit 1
fi

cd "$ROOT_DIR"

echo "🛠️ Превалидация и подготовка контекста robot-сборки..."

VENDOR_OK=true
for f in lib/librkllmrt.so lib/librknnrt.so include/rkllm.h include/rknn_api.h; do
  if [ ! -f "$ROSPKG/src/rkllm_ros2/vendor/$f" ]; then
    VENDOR_OK=false
    echo "❗ Нет ros_packages/src/rkllm_ros2/vendor/$f"
  fi
done
if [ "$VENDOR_OK" != true ]; then
  echo "⚠️  RK-рантайм не полностью в vendor/ — образ соберётся БЕЗ rkllm_ros2."
  echo "    Положите .so и заголовки по инструкции ros_packages/src/rkllm_ros2/vendor/README.md"
  echo "    и пересоберите, если нужны LLM-экшены."
else
  echo "✅ vendor rkllm на месте — rkllm_ros2 будет собран"
fi

if [ ! -f "$ROSPKG/src/rds_2p_inference/external_lib/onnxruntime-linux-aarch64-1.19.2.tgz" ]; then
  echo "📥 Скачиваем OnnxRuntime aarch64 1.19.2..."
  curl -L -o "$ROSPKG/src/rds_2p_inference/external_lib/onnxruntime-linux-aarch64-1.19.2.tgz" \
    https://github.com/microsoft/onnxruntime/releases/download/v1.19.2/onnxruntime-linux-aarch64-1.19.2.tgz
fi

clone_if_missing "$ROSPKG/src/ftservo_ros/library/FTServoLibrary" "https://github.com/ShiWarai/FTServoLibrary.git"
clone_if_missing "$ROSPKG/src/mpu6500_ros/library/mpu6500" "https://github.com/libdriver/mpu6500.git"
clone_if_missing "$ROSPKG/src/OrbbecSDK_ROS2" "https://github.com/orbbec/OrbbecSDK_ROS2.git" "main"
clone_if_missing "$ROSPKG/src/audio_common" "https://github.com/mgonzs13/audio_common.git"
clone_if_missing "$ROSPKG/src/vosk_ros2" "https://github.com/ShiWarai/vosk_ros2.git"

VOSK_MODEL="$ROSPKG/src/vosk_ros2/models/vosk-model-small-ru-0.22"
if [ ! -d "$VOSK_MODEL" ]; then
  echo "📥 Скачиваем модель Vosk..."
  mkdir -p "$ROSPKG/src/vosk_ros2/models"
  pushd "$ROSPKG/src/vosk_ros2/models" >/dev/null
  wget -q https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
  python3 -m zipfile -e vosk-model-small-ru-0.22.zip .
  rm -f vosk-model-small-ru-0.22.zip
  popd >/dev/null
else
  echo "ℹ️ Модель Vosk уже на месте"
fi

cp -f "$SCRIPT_DIR/.dockerignore" "$ROOT_DIR/.dockerignore"

echo "🐳 docker build -f docker/robot.Dockerfile -t $IMAGE (нативная сборка, это займёт время)"
docker build -f "$SCRIPT_DIR/robot.Dockerfile" -t "$IMAGE" "$ROOT_DIR"

rm -f "$ROOT_DIR/.dockerignore"
echo "✅ Образ $IMAGE собран. Запуск: docker/run_robot.sh (MODELS_DIR=... RKLLM_MODEL=...)"
