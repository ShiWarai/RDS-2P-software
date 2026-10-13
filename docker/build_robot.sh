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

# Определение аппаратной платформы робота (NPU/SoC).
# Возвращает: rk3588 | rk3576 | rk3568 | generic
detect_rk_platform() {
  local model=""
  if [ -f /proc/device-tree/model ]; then
    model="$(tr '\0' '\n' < /proc/device-tree/model 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -s ' _-')"
  fi
  # RK-процессоры определяем по модели и наличию NPU-устройств (/dev/rknn, /dev/rga, /dev/mpp_service).
  if echo "$model" | grep -Eq "rk3588|rk3576|rk3568|orange pi ?5|orange_pi|rk3562|rk3588s"; then
    if echo "$model" | grep -q rk3562; then echo rk3562
    elif echo "$model" | grep -q rk3588s; then echo rk3588s
    elif echo "$model" | grep -q rk3576; then echo rk3576
    elif echo "$model" | grep -q rk3568; then echo rk3568
    else echo rk3588
    fi
    return 0
  fi
  for d in rknn rga mpp_service; do
    if [ -e "/dev/$d" ]; then echo rk3588; return 0; fi
  done
  echo generic
}

# Разрешить PLATFORM в конкретный результат с проверкой.
# auto — автоопределение; rk3588|rk3576|rk3562|rk3568|rk3588s — с NPU; generic — без NPU.
resolve_platform() {
  local requested="${PLATFORM:-auto}"
  case "$requested" in
    auto) echo "$(detect_rk_platform)"; return 0 ;;
    rk3588|rk3576|rk3562|rk3568|rk3588s) echo "$requested"; return 0 ;;
    generic|cpu|no-npu) echo generic; return 0 ;;
    *) echo "⚠️ Неизвестный PLATFORM='$requested' — используем автоопределение." >&2; echo "$(detect_rk_platform)"; return 0 ;;
  esac
}

# NPU доступен только на RK-платформах И при наличии vendor RK-рантайма.
rk_platform_has_npu() {
  local plat="$1"
  [ "$plat" != "generic" ] || return 1
  [ "$VENDOR_OK" = true ] || return 1
  return 0
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
if [ "$VENDOR_OK" = true ]; then
  echo "✅ vendor RK-рантайм (librkllmrt.so/librknnrt.so + заголовки) в vendor/ — rkllm_ros2 соберётся при наличии NPU."
else
  echo "⚠️  RK-рантайм не полностью в vendor/ — rkllm_ros2 НЕ соберётся (LLM-экшены отключатся)."
  echo "    Положите .so и заголовки по инструкции ros_packages/src/rkllm_ros2/vendor/README.md"
  echo "    и пересоберите, если нужны LLM-экшены."
fi

# Платформа: supported = rk3588|rk3576|rk3562|rk3568|rk3588s|generic|auto
PLATFORM="${PLATFORM:-auto}"
RESOLVED_PLATFORM="$(resolve_platform)"
NPU_ENABLED=0
if rk_platform_has_npu "$RESOLVED_PLATFORM"; then
  NPU_ENABLED=1
  echo "🎯 Платформа: $RESOLVED_PLATFORM (NPU вкл — будет собран rkllm_ros2)."
else
  case "$RESOLVED_PLATFORM" in
    generic)
      echo "🎯 Платформа: generic (NPU выкл — rkllm_ros2 НЕ собран). Repka-Pi4 / Orange Pi без RK." ;;
    *)
      echo "🎯 Платформа: $RESOLVED_PLATFORM (NPU выкл — rkllm_ros2 НЕ собран: нет vendor RK-рантайма)." ;;
  esac
fi
echo "   Управление: PLATFORM=rk3588 (NPU) | PLATFORM=generic (без NPU) | PLATFORM=auto (авто)."

clone_if_missing "$ROSPKG/src/ftservo_ros/library/FTServoLibrary" "https://github.com/ShiWarai/FTServoLibrary.git"
clone_if_missing "$ROSPKG/src/mpu6500_ros/library/mpu6500" "https://github.com/libdriver/mpu6500.git"
# RDS-2P overlay: runtime-переназначение шины IMU (SPI/I2C девайсы берутся из ROS2-параметров).
# Вендор libdriver/mpu6500 клонится свежим без этих сеттеров — накладка обязательна для сборки mpu6500_ros.
MPU_PATCH="$ROSPKG/patches/mpu6500-runtime-bus-override.patch"
MPU_LIB="$ROSPKG/src/mpu6500_ros/library/mpu6500"
if [ -f "$MPU_PATCH" ]; then
  if git -C "$MPU_LIB" apply --check "$MPU_PATCH" 2>/dev/null; then
    git -C "$MPU_LIB" apply "$MPU_PATCH" && echo "🩹 RDS-2P mpu6500 overlay применён (runtime SPI/I2C)"
  else
    echo "ℹ️ RDS-2P mpu6500 overlay уже применён (или не подходит к HEAD) — пропускаю"
  fi
fi
clone_if_missing "$ROSPKG/src/OrbbecSDK_ROS2" "https://github.com/orbbec/OrbbecSDK_ROS2.git" "main"
clone_if_missing "$ROSPKG/src/audio_common" "https://github.com/mgonzs13/audio_common.git"
clone_if_missing "$ROSPKG/src/vosk_ros2" "https://github.com/ShiWarai/vosk_ros2.git"

# OnnxRuntime SDK в контекст (единая логика с нативной сборкой: fetch_onnxruntime.sh,
# там же её используют build_for_robot.sh / build_for_desktop.sh).
bash "$ROSPKG/scripts/fetch_onnxruntime.sh" "$ROSPKG"

# obj-меши для twin: canonical-источник — urdf_src/export/.../meshes/obj (GIT),
# в vendored subset (deps/mujoco_playground) не лежат — кладутся при prepare
# (та же логика, что в build_desktop.sh). Без них virtual_twin_node падает на base.obj.
MP_MESHES="$ROSPKG/deps/mujoco_playground/_src/locomotion/rds2p/xmls/meshes"
URDF_OBJ_MESHES="$ROOT_DIR/urdf_src/export/rds-2p/meshes/obj"
if [ ! -d "$ROSPKG/deps/mujoco_playground/_src" ]; then
  echo "ERROR: нет vendored subset deps/mujoco_playground/_src — twin не соберётся" >&2
  exit 1
fi
if [ ! -d "$URDF_OBJ_MESHES" ] || [ -z "$(ls -A "$URDF_OBJ_MESHES" 2>/dev/null)" ]; then
  echo "ERROR: obj-меши не найдены в urdf_src/export/rds-2p/meshes/obj — virtual_twin_node упадёт на base.obj" >&2
  exit 1
fi
mkdir -p "$MP_MESHES"
cp -a "$URDF_OBJ_MESHES/." "$MP_MESHES/"
echo "📦 twin-меши (.obj) скопированы в deps/mujoco_playground."

VOSK_MODEL="$ROSPKG/src/vosk_ros2/models/vosk-model-small-ru-0.22"
if [ ! -d "$VOSK_MODEL" ]; then
  mkdir -p "$ROSPKG/src/vosk_ros2/models"
  pushd "$ROSPKG/src/vosk_ros2/models" >/dev/null
  if timeout 180 wget -q -T 30 --tries=1 \
        https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip 2>/dev/null \
     && [ -f vosk-model-small-ru-0.22.zip ] && [ -s vosk-model-small-ru-0.22.zip ]; then
    python3 -m zipfile -e vosk-model-small-ru-0.22.zip .
    rm -f vosk-model-small-ru-0.22.zip
    echo "✅ Модель Vosk скачана."
  else
    echo "⚠️  Модель Vosk не успела скааться (сеть/таймаут). Модель — runtime-актив (монтируется в /models), сборка продолжается без неё в образе."
    rm -f vosk-model-small-ru-0.22.zip 2>/dev/null || true
  fi
  popd >/dev/null
else
  echo "ℹ️ Модель Vosk уже на месте"
fi

# Модель RNNoise (rnnoise_data-<ver>.tar.gz): предзагружаем в ros_packages/deps/,
# чтобы docker build не зависел от media.xiph.org (в контейнере она часто недоступна).
# Dockerfile сам подхватит файл из контекста; fallback — time-boxed-загрузка внутри образа.
RNN_VER="$(cat "$ROSPKG/deps/rnnoise_src/model_version" 2>/dev/null || echo 0b50c45)"
RNN_MODEL_TGZ="$ROSPKG/deps/rnnoise_data-$RNN_VER.tar.gz"
if [ ! -s "$RNN_MODEL_TGZ" ]; then
  mkdir -p "$ROSPKG/deps"
  echo "📥 Скачиваем модель RNNoise (rnnoise_data-$RNN_VER.tar.gz)..."
  RNN_DL_OK=false
  for url in \
    "https://cdn.netbsd.org/pub/pkgsrc/distfiles/rnnoise-0.2/rnnoise_data-$RNN_VER.tar.gz" \
    "https://media.xiph.org/rnnoise/models/rnnoise_data-$RNN_VER.tar.gz"; do
    if timeout 240 curl -fL --connect-timeout 15 --max-time 230 -o "$RNN_MODEL_TGZ" "$url" 2>/dev/null \
       && [ -s "$RNN_MODEL_TGZ" ] && tar -tzf "$RNN_MODEL_TGZ" >/dev/null 2>&1; then
      RNN_DL_OK=true
      break
    fi
    rm -f "$RNN_MODEL_TGZ" 2>/dev/null || true
  done
  if [ "$RNN_DL_OK" = true ]; then
    echo "✅ Модель RNNoise готова в ros_packages/deps/."
  else
    echo "⚠️  Модель RNNoise не скачалась — Dockerfile попробует time-boxed-загрузку в контейнере, иначе пропустит rnnoise/audio_filters."
  fi
else
  echo "ℹ️ Модель RNNoise уже на месте: $RNN_MODEL_TGZ"
fi

# robot-образ максимально тонкий: визуальные меши (48MB dae) в него не кладём —
# rviz/симуляция живут на desktop. Убираем и локальную копию из контекста,
# иначе COPY ros_packages затащит их в каждый robot-образ.
if [ -d "$ROSPKG/src/rds_2p/meshes" ]; then
  echo "🧹 robot-контекст: удаляю rds_2p/meshes (тонкий образ; вернутся: urdf_src/update_rds2p.sh)"
  rm -rf "$ROSPKG/src/rds_2p/meshes"
fi

cp -f "$SCRIPT_DIR/.dockerignore" "$ROOT_DIR/.dockerignore"

if [ "${PREPARE_ONLY:-0}" = "1" ]; then
  echo "✅ Контекст robot-сборки подготовлен (PREPARE_ONLY=1) — docker build пропущен"
  exit 0
fi

# Колонки colcon по MemTotal: на 2GB SBC (Pi4) четыре компилятора параллельно ловят OOM.
# Ручной override: BUILD_WORKERS=8 ./docker/build_robot.sh
MEM_GB="$(awk '/MemTotal/{print int($2/1048576)}' /proc/meminfo 2>/dev/null || echo 0)"
CORES="$(nproc)"
if [ "${BUILD_WORKERS:-0}" -gt 0 ] 2>/dev/null; then
  WORKERS="$BUILD_WORKERS"
elif [ "${MEM_GB:-0}" -lt 4 ]; then
  WORKERS=$(( CORES < 2 ? CORES : 2 ))
else
  WORKERS="$CORES"
fi
echo "⚙️  colcon workers: $WORKERS (RAM=${MEM_GB}GB, cores=$CORES)"

echo "🐳 docker build --build-arg NPU=$NPU_ENABLED --build-arg BUILD_WORKERS=$WORKERS -f docker/robot.Dockerfile -t $IMAGE (нативная сборка, это займёт время)"
docker build --build-arg "NPU=$NPU_ENABLED" --build-arg "BUILD_WORKERS=$WORKERS" -f "$SCRIPT_DIR/robot.Dockerfile" -t "$IMAGE" "$ROOT_DIR"

rm -f "$ROOT_DIR/.dockerignore"
echo "✅ Образ $IMAGE собран. Запуск: docker/run_robot.sh (MODELS_DIR=... RKLLM_MODEL=...)"
