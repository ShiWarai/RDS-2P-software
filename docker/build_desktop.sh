#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ROSPKG="$ROOT_DIR/ros_packages"

IMAGE="${IMAGE:-rds2p/desktop:humble}"

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

cd "$ROOT_DIR"

echo "🛠️ Готовим контекст desktop-сборки..."

# mujoco_playground (locomotion/rds2p) — вендорный subset прямо в репозитории
# (ros_packages/deps/mujoco_playground). Внешних клонов при сборке нет; если
# каталога нет — desktop собирается без twin (warn в desktop.Dockerfile).
if [ ! -d "$ROSPKG/deps/mujoco_playground/_src" ]; then
  echo "⚠️  ros_packages/deps/mujoco_playground отсутствует — desktop будет собран без twin"
else
  echo "ℹ️ mujoco_playground на месте (vendored)"
fi
mkdir -p "$ROSPKG/deps"
touch "$ROSPKG/deps/COLCON_IGNORE"

# obj-меши для twin: canonical-источник — urdf_src/export/.../meshes/obj (GIT, по
# аналогии с dae для URDF), в subset-е в git не лежат — кладутся сюда при prepare.
MP_MESHES="$ROSPKG/deps/mujoco_playground/_src/locomotion/rds2p/xmls/meshes"
if [ -d "$ROSPKG/deps/mujoco_playground/_src" ] && [ -d "$ROOT_DIR/urdf_src/export/rds-2p/meshes/obj" ]; then
  mkdir -p "$MP_MESHES"
  cp -a "$ROOT_DIR/urdf_src/export/rds-2p/meshes/obj/." "$MP_MESHES/"
fi

clone_if_missing "$ROSPKG/src/audio_common" "https://github.com/mgonzs13/audio_common.git"
clone_if_missing "$ROSPKG/src/vosk_ros2" "https://github.com/ShiWarai/vosk_ros2.git" "dev"
clone_if_missing "$ROSPKG/src/ftservo_ros/library/FTServoLibrary" "https://github.com/ShiWarai/FTServoLibrary.git"
# desktop собирает orbbec_camera_msgs/orbbec_description (сам orbbec_camera скипается) —
# как в ros_packages/scripts/build_for_desktop.sh
clone_if_missing "$ROSPKG/src/OrbbecSDK_ROS2" "https://github.com/orbbec/OrbbecSDK_ROS2.git" "main"

# OnnxRuntime SDK в контекст (единая логика с нативной сборкой: fetch_onnxruntime.sh).
bash "$ROSPKG/scripts/fetch_onnxruntime.sh" "$ROSPKG"

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

# меши rds_2p: в git не лежат (rds_2p/.gitignore), берутся из urdf_src/export —
# как это делает urdf_src/update_rds2p.sh. Нужны для install(DIRECTORY meshes) в colcon.
if [ ! -d "$ROSPKG/src/rds_2p/meshes/dae" ] && [ -d "$ROOT_DIR/urdf_src/export/rds-2p/meshes/dae" ]; then
  echo "📥 Копируем меши rds_2p из urdf_src/export..."
  mkdir -p "$ROSPKG/src/rds_2p/meshes"
  cp -a "$ROOT_DIR/urdf_src/export/rds-2p/meshes/dae" "$ROSPKG/src/rds_2p/meshes/"
fi

cp -f "$SCRIPT_DIR/.dockerignore" "$ROOT_DIR/.dockerignore"

if [ "${PREPARE_ONLY:-0}" = "1" ]; then
  echo "✅ Контекст desktop-сборки подготовлен (PREPARE_ONLY=1) — docker build пропущен"
  exit 0
fi

echo "🐳 docker build -f docker/desktop.Dockerfile -t $IMAGE"
docker build -f "$SCRIPT_DIR/desktop.Dockerfile" -t "$IMAGE" "$ROOT_DIR"

rm -f "$ROOT_DIR/.dockerignore"
echo "✅ Образ $IMAGE собран. Запуск: docker/run_desktop.sh"
