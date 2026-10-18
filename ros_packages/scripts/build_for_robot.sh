#!/bin/bash

# Сборка всех пакетов для робота RDS-2P.
# Режимы (параметр вместо отдельного docker/build_robot.sh):
#   (без параметров)   native — установка в живую систему (colcon + dist-packages)
#   --prepare-only     подготовить docker-контекст и выйти (эквивалент PREPARE_ONLY=1)
#   --docker           подготовить контекст и выполнить docker build
#   --models           скачивать runtime-модели (Vosk, RNNoise) и в docker/prepare
#                      режимах (по умолчанию только native: модели — runtime-активы,
#                      монтируются в /models, в контекст/образ не нужны)
# Env для docker-режимов: IMAGE, PLATFORM (rk3588|rk3576|rk3562|rk3568|rk3588s|generic|auto),
# ALLOW_CROSS=1, BUILD_WORKERS, PREPARE_ONLY=1 (compat).
# Общая логика prepare (клоны, OnnxRuntime, twin-меши, Vosk, RNNoise-модель) едина для всех режимов.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROSPKG_DIR="$(dirname "$SCRIPT_DIR")"
ROOT_DIR="$(dirname "$ROSPKG_DIR")"
DOCKER_DIR="$ROOT_DIR/docker"

MODE=native
ROS_DEPS_IGNORE=false
MODELS=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --ros-deps-ignore)
            ROS_DEPS_IGNORE=true
            shift
            ;;
        --models)
            MODELS=true
            shift
            ;;
        --docker)
            MODE=docker
            shift
            ;;
        --prepare-only)
            MODE=prepare
            shift
            ;;
        *)
            echo "Неизвестный аргумент: $1"
            echo "Использование: $0 [--ros-deps-ignore] [--models] [--docker | --prepare-only]"
            exit 1
            ;;
    esac
done
if [ "${PREPARE_ONLY:-0}" = "1" ] && [ "$MODE" = native ]; then
    MODE=prepare
fi
IMAGE="${IMAGE:-rds2p/robot:humble}"

echo "🤖 Сборка пакетов для робота (режим: $MODE)..."

SCRIPT_START_TIME=$(date +%s)

show_duration() {
    local d=$(( $(date +%s) - SCRIPT_START_TIME ))
    local h=$((d/3600)) m=$(((d%3600)/60)) s=$((d%60))
    echo ""
    echo "⏱️  Общее время выполнения скрипта:"
    if [ $h -gt 0 ]; then echo "   ${h}ч ${m}м ${s}с"
    elif [ $m -gt 0 ]; then echo "   ${m}м ${s}с"
    else echo "   ${s}с"; fi
}

# ================= docker preflight (только для docker/prepare) =================
NPU_ENABLED=0
if [ "$MODE" != native ]; then
    detect_rk_platform() {
        local model=""
        if [ -f /proc/device-tree/model ]; then
            model="$(tr '\0' '\n' < /proc/device-tree/model 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -s ' _-')"
        fi
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
    resolve_platform() {
        local requested="${PLATFORM:-auto}"
        case "$requested" in
            auto) echo "$(detect_rk_platform)"; return 0 ;;
            rk3588|rk3576|rk3562|rk3568|rk3588s) echo "$requested"; return 0 ;;
            generic|cpu|no-npu) echo generic; return 0 ;;
            *) echo "⚠️ Неизвестный PLATFORM='$requested' — используем автоопределение." >&2; echo "$(detect_rk_platform)"; return 0 ;;
        esac
    }
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

    VENDOR_OK=true
    for f in lib/librkllmrt.so lib/librknnrt.so include/rkllm.h include/rknn_api.h; do
        if [ ! -f "$ROSPKG_DIR/src/rkllm_ros2/vendor/$f" ]; then
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

    RESOLVED_PLATFORM="$(resolve_platform)"
    if rk_platform_has_npu "$RESOLVED_PLATFORM"; then
        NPU_ENABLED=1
        echo "🎯 Платформа: $RESOLVED_PLATFORM (NPU вкл — будет собран rkllm_ros2)."
    else
        case "$RESOLVED_PLATFORM" in
            generic) echo "🎯 Платформа: generic (NPU выкл — rkllm_ros2 НЕ собран). Repka-Pi4 / Orange Pi без RK." ;;
            *) echo "🎯 Платформа: $RESOLVED_PLATFORM (NPU выкл — rkllm_ros2 НЕ собран: нет vendor RK-рантайма)." ;;
        esac
    fi
    echo "   Управление: PLATFORM=rk3588 (NPU) | PLATFORM=generic (без NPU) | PLATFORM=auto (авто)."
fi

# ================= общий prepare (все режимы) =================

cd "$ROSPKG_DIR"
if [ ! -d "src" ]; then
    echo "❌ Нет src/ рядом со скриптом — повреждена копия ros_packages"
    exit 1
fi

# Устанавливаем зависимости
echo "📦 Устанавливаем зависимости..."

# Проверяем и подгружаем OnnxRuntime (единая логика — fetch_onnxruntime.sh)
bash "$SCRIPT_DIR/fetch_onnxruntime.sh"

# Скачиваем FTServoLibrary если его нет или папка пустая
FTSERVO_LIB_PATH="src/ftservo_ros/library/FTServoLibrary"
if [ ! -d "$FTSERVO_LIB_PATH" ] || [ -z "$(ls -A "$FTSERVO_LIB_PATH" 2>/dev/null)" ]; then
    echo "📥 Скачиваем FTServoLibrary..."
    rm -rf "$FTSERVO_LIB_PATH"
    mkdir -p "src/ftservo_ros/library"
    cd "src/ftservo_ros/library"
    git clone https://github.com/ShiWarai/FTServoLibrary.git
    cd ../../..
    echo "✅ FTServoLibrary скачан"
else
    echo "ℹ️ FTServoLibrary уже существует"
fi

# Скачиваем mpu6500 библиотеку если её нет или папка пустая
MPU6500_LIB_PATH="src/mpu6500_ros/library/mpu6500"
if [ ! -d "$MPU6500_LIB_PATH" ] || [ -z "$(ls -A "$MPU6500_LIB_PATH" 2>/dev/null)" ]; then
    echo "📥 Скачиваем mpu6500 библиотеку..."
    rm -rf "$MPU6500_LIB_PATH"
    mkdir -p "src/mpu6500_ros/library"
    cd "src/mpu6500_ros/library"
    git clone https://github.com/libdriver/mpu6500.git
    cd ../../..
    echo "✅ mpu6500 библиотека скачана"
else
    echo "ℹ️ mpu6500 библиотека уже существует"
fi

# RDS-2P overlay: runtime-переназначение шины IMU (SPI/I2C из ROS2-параметров).
# Вендор клонится свежим без сеттеров — накладка обязательна для сборки mpu6500_ros.
MPU_PATCH="$ROSPKG_DIR/patches/mpu6500-runtime-bus-override.patch"
if [ -f "$MPU_PATCH" ]; then
    if git -C "$MPU6500_LIB_PATH" apply --check "$MPU_PATCH" 2>/dev/null; then
        git -C "$MPU6500_LIB_PATH" apply "$MPU_PATCH" && echo "🩹 RDS-2P mpu6500 overlay применён (runtime SPI/I2C)"
    elif git -C "$MPU6500_LIB_PATH" apply --reverse --check "$MPU_PATCH" 2>/dev/null; then
        echo "ℹ️ RDS-2P mpu6500 overlay уже применён — пропускаю"
    else
        echo "ERROR: $MPU_PATCH не накладывается на HEAD вендора libdriver/mpu6500 — обновите патч или запиньте коммит клона." >&2
        exit 1
    fi
else
    echo "ERROR: не найден патч оверлея mpu6500: $MPU_PATCH (mpu6500_ros не соберётся без сеттеров)." >&2
    exit 1
fi

# obj-меши для twin: canonical-источник — urdf_src/export/.../meshes/obj (GIT),
# в vendored subset (deps/mujoco_playground) не лежат — кладутся при prepare
# (та же логика, что в build_for_desktop.sh / docker-обёртках).
MP_MESHES="$ROSPKG_DIR/deps/mujoco_playground/_src/locomotion/rds2p/xmls/meshes"
URDF_OBJ_MESHES="$ROOT_DIR/urdf_src/export/rds-2p/meshes/obj"
if [ ! -d "$(dirname "$MP_MESHES")" ]; then
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

# Клонируем OrbbecSDK_ROS2 если его нет
ORBBEC_ROS2_PATH="src/OrbbecSDK_ROS2"
if [ ! -d "$ORBBEC_ROS2_PATH" ]; then
    echo "📥 Клонируем OrbbecSDK_ROS2 (ветка main для Astra Mini)..."
    cd src
    git clone -b main https://github.com/orbbec/OrbbecSDK_ROS2.git
    cd ..
    echo "✅ OrbbecSDK_ROS2 клонирован (ветка main)"
else
    echo "ℹ️ OrbbecSDK_ROS2 уже существует, проверяем ветку..."
    if [ -d "$ORBBEC_ROS2_PATH/.git" ] || [ -f "$ORBBEC_ROS2_PATH/.git" ]; then
        pushd "$ORBBEC_ROS2_PATH" >/dev/null
        CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        if [ "$CURRENT_BRANCH" != "main" ]; then
            echo "🔄 Переключаемся на ветку main (рекомендуется для Astra Mini)..."
            git fetch origin main 2>/dev/null || true
            git checkout main 2>/dev/null || git checkout -b main origin/main 2>/dev/null || true
            git pull origin main 2>/dev/null || true
            echo "✅ Переключено на ветку main"
        else
            echo "ℹ️ Уже используется ветка main"
            git pull origin main 2>/dev/null || true
        fi
        popd >/dev/null
    else
        echo "⚠️ OrbbecSDK_ROS2 существует, но не является git репозиторием (возможно, удален .git). Пропускаем проверку ветки."
    fi
fi

# Патч orbbec_camera: upstream не включает astra_mini.launch.py (RDS-2P)
ORB_PATCH_LAUNCH="$SCRIPT_DIR/orbbec_camera_patches/astra_mini.launch.py"
ORB_PATCH_TARGET="src/OrbbecSDK_ROS2/orbbec_camera/launch/astra_mini.launch.py"
if [ -d "src/OrbbecSDK_ROS2/orbbec_camera" ]; then
    if [ -f "$ORB_PATCH_LAUNCH" ]; then
        mkdir -p "$(dirname "$ORB_PATCH_TARGET")"
        cp -f "$ORB_PATCH_LAUNCH" "$ORB_PATCH_TARGET"
        echo "✅ Применён патч Orbbec: astra_mini.launch.py → $ORB_PATCH_TARGET"
    else
        echo "⚠️ Файл патча не найден: $ORB_PATCH_LAUNCH"
    fi
else
    echo "⚠️ orbbec_camera не найден — патч astra_mini.launch.py пропущен"
fi

# Клонируем audio_common если его нет
AUDIO_COMMON_PATH="src/audio_common"
if [ ! -d "$AUDIO_COMMON_PATH" ]; then
    echo "📥 Клонируем audio_common..."
    cd src
    git clone https://github.com/mgonzs13/audio_common.git
    cd ..
    echo "✅ audio_common клонирован"
else
    echo "ℹ️ audio_common уже существует"
fi

# Клонируем vosk_ros2 если его нет
VOSK_ROS2_PATH="src/vosk_ros2"
if [ ! -d "$VOSK_ROS2_PATH" ]; then
    echo "📥 Клонируем vosk_ros2..."
    cd src
    git clone https://github.com/ShiWarai/vosk_ros2.git
    cd ..
    echo "✅ vosk_ros2 клонирован"
else
    echo "ℹ️ vosk_ros2 уже существует"
fi

# Модель Vosk — runtime-актив (монтируется в /models): native качает её всегда,
# docker/prepare — только с флагом --models (иначе лишние 44+88 МБ едут в контекст/образ).
# Качаем с HF-зеркала: alphacephei.com подвешивает тело ответа; размер сверен с ETag.
VOSK_MODEL_PATH="src/vosk_ros2/models/vosk-model-small-ru-0.22"
VOSK_MODEL_DIR="src/vosk_ros2/models"
if [ -d "$VOSK_MODEL_PATH" ]; then
    echo "ℹ️ Модель Vosk уже установлена: $VOSK_MODEL_PATH"
elif [ "$MODE" = native ] || [ "$MODELS" = true ]; then
    echo "📥 Скачиваем модель Vosk (vosk-model-small-ru-0.22)..."
    mkdir -p "$VOSK_MODEL_DIR"
    pushd "$VOSK_MODEL_DIR" >/dev/null
    VOSK_MODEL_ZIP="vosk-model-small-ru-0.22.zip"
    # Зеркало на HF: alphacephei.com подвешивает тело ответа (соединение открывается,
    # байты не идут); размер файла сверен с официальным ETag: 46236750 байт
    VOSK_URL="https://huggingface.co/localstack/vosk-models/resolve/main/vosk-model-small-ru-0.22.zip"
    if [ "$MODE" = native ]; then
        if [ ! -f "$VOSK_MODEL_ZIP" ]; then
            wget -q --show-progress -O "$VOSK_MODEL_ZIP" "$VOSK_URL"
        fi
    else
        timeout 180 wget -q -T 30 --tries=1 -O "$VOSK_MODEL_ZIP" "$VOSK_URL" 2>/dev/null || true
    fi
    if [ -f "$VOSK_MODEL_ZIP" ] && [ -s "$VOSK_MODEL_ZIP" ]; then
        python3 -m zipfile -e "$VOSK_MODEL_ZIP" .
        rm -f "$VOSK_MODEL_ZIP"
        echo "✅ Модель Vosk установлена в $VOSK_MODEL_PATH"
    else
        echo "⚠️ Модель Vosk не скачалась (сеть/таймаут). Для образа модель — runtime-актив (монтируется в /models)."
        rm -f "$VOSK_MODEL_ZIP" 2>/dev/null || true
    fi
    popd >/dev/null
else
    echo "ℹ️ Модель Vosk не качаем (docker/prepare): runtime-актив, монтируется в /models; --models — чтобы положить в контекст"
fi

# Vendor для rkllm_ros2: RKLLM/RKNN runtime (.so + заголовки). Качаем с GitHub
# airockchip/rknn-llm; fallback — локальный клон (~/rknn-llm, override: RKLLM_SRC).
# Ref закреплён на теге (override: RKLLM_REF): в main API rkllm_init() уже изменено
# (RKLLMCallback*, без img_start), а rkllm_node.cpp написан под SDK 1.2.3.
# CMakeLists rkllm_ros2 фаталит без этих файлов, поэтому в native режиме отсутствующие
# файлы = ошибка сборки, в docker-prepare — предупреждение (NPU=0 всё равно скипает пакет).
RKLLM_VENDOR_DIR="src/rkllm_ros2/vendor"
RKLLM_REF="${RKLLM_REF:-release-v1.2.3}"
RKLLM_RAW="https://raw.githubusercontent.com/airockchip/rknn-llm/$RKLLM_REF"
RKLLM_LOCAL_CLONE="${RKLLM_SRC:-$HOME/rknn-llm}"
_rkllm_sz() { stat -c%s "$1" 2>/dev/null || echo 0; }
rkllm_ensure_file() {
    local dst="$RKLLM_VENDOR_DIR/$1" src_rel="$2" min="$3"
    if [ -f "$dst" ] && [ "$(_rkllm_sz "$dst")" -ge "$min" ]; then
        return 0
    fi
    mkdir -p "$(dirname "$dst")"
    if [ "$MODE" = native ]; then
        curl -fsSL --connect-timeout 15 -o "$dst" "$RKLLM_RAW/$src_rel" || rm -f "$dst"
    else
        timeout 120 curl -fsSL --connect-timeout 15 -o "$dst" "$RKLLM_RAW/$src_rel" 2>/dev/null || rm -f "$dst"
    fi
    if [ ! -f "$dst" ] && [ -f "$RKLLM_LOCAL_CLONE/$src_rel" ]; then
        cp "$RKLLM_LOCAL_CLONE/$src_rel" "$dst"
        echo "   📂 $1 — из локального клона $RKLLM_LOCAL_CLONE"
    fi
    if [ -f "$dst" ] && [ "$(_rkllm_sz "$dst")" -lt "$min" ]; then
        rm -f "$dst"
    fi
    [ -f "$dst" ]
}
echo "🧩 Готовим vendor rkllm_ros2 (librkllmrt.so / librknnrt.so / rkllm.h / rknn_api.h)..."
RKLLM_OK=true
rkllm_ensure_file "lib/librkllmrt.so" "rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so" 1000000 || RKLLM_OK=false
rkllm_ensure_file "lib/librknnrt.so" "examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so" 1000000 || RKLLM_OK=false
rkllm_ensure_file "include/rkllm.h" "rkllm-runtime/Linux/librkllm_api/include/rkllm.h" 1000 || RKLLM_OK=false
rkllm_ensure_file "include/rknn_api.h" "examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/include/rknn_api.h" 1000 || RKLLM_OK=false
if [ "$RKLLM_OK" != true ]; then
    if [ "$MODE" = native ]; then
        echo "❌ rkllm_ros2: vendor-библиотеки не получены (ни GitHub, ни локальный клон)." >&2
        echo "   Задайте RKLLM_SRC=/путь/к/rknn-llm или склонируйте: git clone --depth 1 https://github.com/airockchip/rknn-llm ~/rknn-llm" >&2
        exit 1
    fi
    echo "⚠️  rkllm_ros2: vendor неполный — docker-образ с NPU=1 не соберётся (NPU=0 скипнет пакет)." >&2
fi

# Модель RNNoise (rnnoise_data-<ver>.tar.gz): native предзагружает в deps/, чтобы
# сборка не зависела от media.xiph.org. В docker/prepare — только с --models;
# без него Dockerfile скачает её сам (time-boxed fallback), либо audio_filters скипнется.
RNN_VER="$(cat "$ROSPKG_DIR/deps/rnnoise_src/model_version" 2>/dev/null || echo 0b50c45)"
RNN_MODEL_TGZ="$ROSPKG_DIR/deps/rnnoise_data-$RNN_VER.tar.gz"
if [ -s "$RNN_MODEL_TGZ" ]; then
    echo "ℹ️ Модель RNNoise уже на месте: $RNN_MODEL_TGZ"
elif [ "$MODE" = native ] || [ "$MODELS" = true ]; then
    mkdir -p "$ROSPKG_DIR/deps"
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
        echo "⚠️  Модель RNNoise не скачалась — нативная сборка/Dockerfile попробует зеркала сам, иначе audio_filters будет пропущен."
    fi
else
    echo "ℹ️ Модель RNNoise не качаем (docker/prepare): скачает Dockerfile (time-boxed) или --models"
fi

# ================= docker/prepare: хвост контекста и сборка образа =================
if [ "$MODE" != native ]; then
    # robot-образ максимально тонкий: визуальные меши (48MB dae) не кладём —
    # rviz/симуляция живут на desktop (вернутся: urdf_src/update_rds2p.sh).
    if [ -d "$ROSPKG_DIR/src/rds_2p/meshes" ]; then
        echo "🧹 robot-контекст: удаляю rds_2p/meshes (тонкий образ; вернутся: urdf_src/update_rds2p.sh)"
        rm -rf "$ROSPKG_DIR/src/rds_2p/meshes"
    fi

    cp -f "$DOCKER_DIR/.dockerignore" "$ROOT_DIR/.dockerignore"

    if [ "$MODE" = prepare ]; then
        echo "✅ Контекст robot-сборки подготовлен (--prepare-only/PREPARE_ONLY=1) — docker build пропущен"
        show_duration
        exit 0
    fi

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
    docker build --build-arg "NPU=$NPU_ENABLED" --build-arg "BUILD_WORKERS=$WORKERS" -f "$DOCKER_DIR/robot.Dockerfile" -t "$IMAGE" "$ROOT_DIR"

    rm -f "$ROOT_DIR/.dockerignore"
    echo "✅ Образ $IMAGE собран. Запуск: docker/run_robot.sh (MODELS_DIR=... RKLLM_MODEL=...)"
    show_duration
    exit 0
fi

# ================= native: установка в живую систему =================

# Устанавливаем Python-зависимости из всех requirements.txt (после скачивания всех пакетов)
echo "🐍 Ищем и устанавливаем Python-зависимости..."
REQ_FILES=$(find "src" -maxdepth 2 -name "requirements.txt" -type f 2>/dev/null)

CACHE_FILE="$SCRIPT_DIR/.requirements_cache"
declare -A REQ_CACHE
if [ -f "$CACHE_FILE" ]; then
    while IFS='|' read -r path hash; do
        REQ_CACHE["$path"]="$hash"
    done < "$CACHE_FILE"
fi
if [ -n "$REQ_FILES" ]; then
    ROS_PYTHON_DIR="/opt/ros/${ROS_DISTRO:-humble}/local/lib/python3.10/dist-packages"

    if [ -d "$ROS_PYTHON_DIR" ]; then
        if [ ! -w "$ROS_PYTHON_DIR" ]; then
            echo "🔐 Директория $ROS_PYTHON_DIR принадлежит root, исправляем права (требуется sudo)..."
            sudo chown -R $USER:$USER "$ROS_PYTHON_DIR"
            echo "✅ Права доступа исправлены"
        fi
    else
        echo "❌ Директория $ROS_PYTHON_DIR не существует!" >&2
        echo "   Убедитесь, что ROS 2 Humble установлен правильно:" >&2
        echo "   sudo apt install ros-humble-desktop" >&2
        exit 1
    fi

    if command -v uv &> /dev/null; then
        echo "   ⚡ Используем uv для ускорения"
        INSTALL_CMD="uv pip install --upgrade --python /usr/bin/python3 --target=$ROS_PYTHON_DIR"
    else
        INSTALL_CMD="/usr/bin/python3 -m pip install --upgrade --target=$ROS_PYTHON_DIR"
    fi

    for REQ_FILE in $REQ_FILES; do
        REQ_PATH=$(realpath "$REQ_FILE")
        REQ_HASH=$(sha256sum "$REQ_FILE" | awk '{print $1}')
        CACHED_HASH="${REQ_CACHE[$REQ_PATH]}"

        if [ "$CACHED_HASH" = "$REQ_HASH" ]; then
            echo "   ⏭️ Зависимости из: $REQ_FILE (без изменений, пропускаем)"
            continue
        fi

        echo "   📦 Устанавливаем зависимости из: $REQ_FILE"
        if $INSTALL_CMD -r "$REQ_FILE"; then
            REQ_CACHE["$REQ_PATH"]="$REQ_HASH"
        else
            echo "⚠️ Не удалось установить зависимости из $REQ_FILE" >&2
        fi
    done

    : > "$CACHE_FILE"
    for path in "${!REQ_CACHE[@]}"; do
        echo "${path}|${REQ_CACHE[$path]}" >> "$CACHE_FILE"
    done

    echo "✅ Python-зависимости проверены в $ROS_PYTHON_DIR"
else
    echo "ℹ️ requirements.txt файлы не найдены в src/"
fi

# Установка ds4drv (PS4 контроллер драйвер) — CLI-демон, поэтому ставится в систему
# (в dist-packages из find-цикла он не попадёт на PATH); состав — в requirements пакета.
echo "🎮 Проверяем установку ds4drv..."
if ! command -v ds4drv &> /dev/null; then
    echo "📥 Устанавливаем ds4drv (из src/rds_2p_joystick/requirements.txt)..."
    if command -v pip3 &> /dev/null; then
        sudo pip3 install -r "$ROSPKG_DIR/src/rds_2p_joystick/requirements.txt"
        echo "✅ ds4drv установлен через pip3"
    elif command -v pip &> /dev/null; then
        sudo pip install -r "$ROSPKG_DIR/src/rds_2p_joystick/requirements.txt"
        echo "✅ ds4drv установлен через pip"
    else
        echo "⚠️ pip не найден. Установите вручную: sudo pip3 install -r src/rds_2p_joystick/requirements.txt"
    fi
else
    echo "ℹ️ ds4drv уже установлен: $(which ds4drv)"
fi

# Настройка прав доступа для ds4drv (PS4 контроллер)
echo "🎮 Настраиваем права доступа для ds4drv..."
UDEV_RULES_FILE="/etc/udev/rules.d/99-ds4drv-permissions.rules"
if [ ! -f "$UDEV_RULES_FILE" ]; then
    echo "📝 Создаём udev правила для ds4drv..."
    sudo tee "$UDEV_RULES_FILE" > /dev/null << 'EOF'
# udev rules for ds4drv access to PS4 controller

# Allow access to uinput for users in input group
KERNEL=="uinput", MODE="0666", GROUP="input"

# Allow access to hidraw devices for users in input group
KERNEL=="hidraw*", MODE="0664", GROUP="input"

# Specific rule for Sony PS4 controller (USB)
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="09cc", MODE="0664", GROUP="input"

# Rule for Sony PS4 controller (Bluetooth)
SUBSYSTEM=="hidraw", ATTRS{name}=="*Wireless Controller*", MODE="0664", GROUP="input"
EOF
    echo "✅ udev правила созданы"

    echo "🔄 Применяем udev правила..."
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    echo "✅ Правила применены"
else
    echo "ℹ️ udev правила уже существуют"
fi

# Проверяем, что пользователь в группе input
if ! groups | grep -q "\binput\b"; then
    echo "👤 Добавляем пользователя $USER в группу input..."
    sudo usermod -a -G input $USER
    echo "⚠️ Пользователь добавлен в группу input. Перелогиньтесь или выполните: newgrp input"
else
    echo "ℹ️ Пользователь уже в группе input"
fi

# Устанавливаем зависимости через rosdep (если не отключено)
if [ "$ROS_DEPS_IGNORE" = false ]; then
    if command -v rosdep &> /dev/null; then
        export PYTHONWARNINGS="ignore::DeprecationWarning"

        ROSDEP_CACHE_DIR="$HOME/.ros/rosdep"
        ROSDEP_UPDATE_INTERVAL=86400
        NEED_UPDATE=true

        if [ -d "$ROSDEP_CACHE_DIR" ]; then
            if command -v stat &> /dev/null; then
                LAST_UPDATE_FILE=$(find "$ROSDEP_CACHE_DIR" -type f -exec stat -c '%Y %n' {} \; 2>/dev/null | sort -n | tail -1 | cut -d' ' -f1)
                if [ -n "$LAST_UPDATE_FILE" ] && [ "$LAST_UPDATE_FILE" != "0" ]; then
                    CURRENT_TIME=$(date +%s)
                    TIME_DIFF=$((CURRENT_TIME - LAST_UPDATE_FILE))
                    if [ $TIME_DIFF -lt $ROSDEP_UPDATE_INTERVAL ]; then
                        NEED_UPDATE=false
                        HOURS_AGO=$((TIME_DIFF / 3600))
                        if [ $HOURS_AGO -lt 1 ]; then
                            MINUTES_AGO=$((TIME_DIFF / 60))
                            echo "ℹ️ rosdep кэш свежий (обновлен ${MINUTES_AGO}м назад), пропускаем обновление"
                        else
                            echo "ℹ️ rosdep кэш свежий (обновлен ${HOURS_AGO}ч назад), пропускаем обновление"
                        fi
                    fi
                fi
            fi
        fi

        if ! rosdep db 1>/dev/null 2>&1; then
            echo "❌ rosdep не инициализирован. Пожалуйста, выполните команды:" >&2
            echo "    sudo rosdep init" >&2
            echo "    rosdep update" >&2
            echo "После этого перезапустите скрипт." >&2
            echo "⏹️ Останавливаем сборку из-за неинициализированного rosdep" >&2
            exit 1
        else
            if [ "$NEED_UPDATE" = true ]; then
                echo "🔄 Обновляем rosdep кэш (только для $ROS_DISTRO)..."
                if [ -n "$ROS_DISTRO" ]; then
                    rosdep update --rosdistro=$ROS_DISTRO 2>/dev/null || true
                else
                    echo "⚠️ ROS_DISTRO не установлен, обновляем все дистрибутивы"
                    rosdep update 2>/dev/null || true
                fi
            fi
            rosdep install --from-paths src --ignore-src -y --rosdistro $ROS_DISTRO 2>/dev/null || true
            echo "✅ rosdep выполнен"
        fi
    else
        echo "⚠️ rosdep не найден, пропускаем зависимости"
    fi
else
    echo "⏭️ Пропускаем обновление зависимостей ROS2 (--ros-deps-ignore)"
fi

# RNNoise для audio_filters: vendor в deps/ (autotools; до colcon)
echo "📥 RNNoise (audio_filters) → deps/rnnoise_install..."
RNN_SRC="$(pwd)/deps/rnnoise_src"
RNN_INST="$(pwd)/deps/rnnoise_install"
STUB="$(pwd)/src/audio_filters/third_party/rnnoise/rnnoise_os_support_stub.h"
JOBS="$(nproc 2>/dev/null || echo 4)"
if [[ ! -f "${RNN_INST}/lib/librnnoise.a" ]] || [[ ! -f "${RNN_INST}/include/rnnoise.h" ]]; then
    mkdir -p "$(pwd)/deps"
    touch "$(pwd)/deps/COLCON_IGNORE"
    if [[ ! -f "${RNN_SRC}/src/denoise.c" ]]; then
        echo "📥 Клонируем xiph/rnnoise (v0.2)..."
        rm -rf "${RNN_SRC}"
        git clone --depth 1 --branch v0.2 https://github.com/xiph/rnnoise.git "${RNN_SRC}"
    fi
    if [[ ! -f "${STUB}" ]]; then
        echo "❌ Нет заглушки os_support: ${STUB}" >&2
        exit 1
    fi
    cp -f "${STUB}" "${RNN_SRC}/src/os_support.h"
    RNN_VER_LOCAL="$(cat "${RNN_SRC}/model_version" 2>/dev/null || echo 0b50c45)"
    RNN_MODEL_TGZ_LOCAL="$(pwd)/deps/rnnoise_data-${RNN_VER_LOCAL}.tar.gz"
    RNN_MODEL_LOCAL="${RNN_SRC}/rnnoise_data-${RNN_VER_LOCAL}.tar.gz"
    if [[ ! -f "${RNN_MODEL_LOCAL}" ]] && [[ -s "${RNN_MODEL_TGZ_LOCAL}" ]]; then
        cp -f "${RNN_MODEL_TGZ_LOCAL}" "${RNN_MODEL_LOCAL}"
        echo "ℹ️ Модель RNNoise взята из deps/ (локальный tarball)."
    fi
    if [[ ! -f "${RNN_MODEL_LOCAL}" ]]; then
        echo "📥 Скачиваем модель RNNoise (time-boxed, зеркала)..."
        for url in \
            "https://cdn.netbsd.org/pub/pkgsrc/distfiles/rnnoise-0.2/rnnoise_data-${RNN_VER_LOCAL}.tar.gz" \
            "https://media.xiph.org/rnnoise/models/rnnoise_data-${RNN_VER_LOCAL}.tar.gz"; do
            if timeout 240 curl -fL --connect-timeout 15 --max-time 230 -o "${RNN_MODEL_LOCAL}" "$url" 2>/dev/null \
               && [[ -s "${RNN_MODEL_LOCAL}" ]] && tar -tzf "${RNN_MODEL_LOCAL}" >/dev/null 2>&1; then
                cp -f "${RNN_MODEL_LOCAL}" "${RNN_MODEL_TGZ_LOCAL}"
                break
            fi
            rm -f "${RNN_MODEL_LOCAL}" 2>/dev/null || true
        done
    fi
    if [[ ! -f "${RNN_MODEL_LOCAL}" ]] || ! tar -tzf "${RNN_MODEL_LOCAL}" >/dev/null 2>&1; then
        echo "⚠️  Модель RNNoise недоступна — пропускаю сборку rnnoise, audio_filters будет исключён из colcon." >&2
        rm -f "${RNN_MODEL_LOCAL}" 2>/dev/null || true
    else
        pushd "${RNN_SRC}" >/dev/null
        ./autogen.sh
        ./configure --prefix="${RNN_INST}" --disable-examples
        make "-j${JOBS}"
        make install
        popd >/dev/null
        echo "✅ RNNoise: ${RNN_INST}"
    fi
else
    echo "ℹ️ RNNoise уже в ${RNN_INST}"
fi

# SoXR для audio_filters/RNNoise (вторично относительно основного робота-сборки)
echo "🔊 [опционально] libsoxr-dev для audio_filters..."
if ! dpkg -s libsoxr-dev >/dev/null 2>&1; then
    echo "📦 Устанавливаем libsoxr-dev (sudo apt)..."
    sudo apt-get install -y libsoxr-dev
    echo "✅ libsoxr-dev установлен"
else
    echo "ℹ️ libsoxr-dev уже установлен"
fi

# Собираем все пакеты
# colcon требует ROS-окружение (ament_cmake через AMENT_PREFIX_PATH); при запуске
# из «чистого» шелла саурсим /opt/ros сами, иначе все пакеты падают на find_package.
if [[ ":${AMENT_PREFIX_PATH:-}:" != *":/opt/ros/${ROS_DISTRO:-humble}:"* ]]; then
    ROS_SETUP="/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
    if [ -f "$ROS_SETUP" ]; then
        echo "🐚 Саурсим ROS-окружение: $ROS_SETUP"
        # shellcheck disable=SC1091
        source "$ROS_SETUP"
    else
        echo "❌ ROS не найден: $ROS_SETUP (нужен ros-${ROS_DISTRO:-humble})" >&2
        exit 1
    fi
fi
echo "🔨 Собираем пакеты..."
COLCON_SKIP=""
if [[ ! -f "${RNN_INST}/lib/librnnoise.a" ]]; then
    COLCON_SKIP="--packages-skip audio_filters"
    echo "⚠️  audio_filters в сборку не входит (нет собранного RNNoise)."
fi
MEM_GB="$(awk '/MemTotal/{print int($2/1048576)}' /proc/meminfo 2>/dev/null || echo 0)"
if [ "${MEM_GB:-0}" -lt 4 ]; then
    COLCON_WORKERS=$(( JOBS < 2 ? JOBS : 2 ))
else
    COLCON_WORKERS="$JOBS"
fi
echo "⚙️  colcon workers: $COLCON_WORKERS (RAM=${MEM_GB}GB, cores=$JOBS)"
colcon build --parallel-workers "${COLCON_WORKERS}" --symlink-install ${COLCON_SKIP}

echo "✅ Готово! Загрузите переменные: source install/setup.bash"

# Добавляем в .bashrc если еще не добавлено
echo "📝 Добавляем в .bashrc..."
BASH_SOURCE_LINE="source $(pwd)/install/setup.bash"
if ! grep -q "$(pwd)/install/setup.bash" ~/.bashrc; then
    echo "" >> ~/.bashrc
    echo "# RDS-2P robot packages" >> ~/.bashrc
    echo "$BASH_SOURCE_LINE" >> ~/.bashrc
    echo "✅ Добавлено в .bashrc"
else
    echo "ℹ️ Уже добавлено в .bashrc"
fi

# Source пакета
echo "🔄 Загружаем переменные окружения..."
source install/setup.bash
echo "✅ Переменные загружены!"

show_duration
