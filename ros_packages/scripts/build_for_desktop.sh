#!/bin/bash

# Сборка пакетов для компьютера (без mpu6500_ros, с камерой Orbbec).
# Режимы (параметр вместо отдельного docker/build_desktop.sh):
#   (без параметров)   native — установка в живую систему (colcon + dist-packages)
#   --prepare-only     подготовить docker-контекст и выйти (эквивалент PREPARE_ONLY=1)
#   --docker           подготовить контекст и выполнить docker build
#   --models           скачивать runtime-модели (Vosk, RNNoise) и в docker/prepare
#                      режимах (по умолчанию только native: модели монтируются на runtime)
# Env для docker-режимов: IMAGE, PREPARE_ONLY=1 (compat).
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
IMAGE="${IMAGE:-rds2p/desktop:humble}"

echo "💻 Сборка пакетов для компьютера (режим: $MODE)..."

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

cd "$ROSPKG_DIR"
if [ ! -d "src" ]; then
    echo "❌ Нет src/ рядом со скриптом — повреждена копия ros_packages"
    exit 1
fi

# ================= общий prepare (все режимы) =================

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

# Клонируем OrbbecSDK_ROS2 если его нет (только для сообщений, сам пакет камеры не собираем)
ORBBEC_ROS2_PATH="src/OrbbecSDK_ROS2"
if [ ! -d "$ORBBEC_ROS2_PATH" ]; then
    echo "📥 Клонируем OrbbecSDK_ROS2 (ветка main для Astra Mini, только сообщения)..."
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
    git clone -b dev https://github.com/ShiWarai/vosk_ros2.git
    cd ..
    echo "✅ vosk_ros2 клонирован"
else
    echo "ℹ️ vosk_ros2 уже существует"
fi

# Модель Vosk — runtime-актив: native качает всегда, docker/prepare — только с --models.
# Зеркало на HF: alphacephei.com подвешивает тело ответа — соединение открывается,
# но байты не идут; размер файла сверен с официальным ETag: 46236750 байт.
VOSK_MODEL_PATH="src/vosk_ros2/models/vosk-model-small-ru-0.22"
VOSK_MODEL_DIR="src/vosk_ros2/models"
if [ -d "$VOSK_MODEL_PATH" ]; then
    echo "ℹ️ Модель Vosk уже установлена: $VOSK_MODEL_PATH"
elif [ "$MODE" = native ] || [ "$MODELS" = true ]; then
    echo "📥 Скачиваем модель Vosk (vosk-model-small-ru-0.22)..."
    mkdir -p "$VOSK_MODEL_DIR"
    pushd "$VOSK_MODEL_DIR" >/dev/null
    VOSK_MODEL_ZIP="vosk-model-small-ru-0.22.zip"
    VOSK_URL="https://huggingface.co/localstack/vosk-models/resolve/main/vosk-model-small-ru-0.22.zip"
    if [ ! -f "$VOSK_MODEL_ZIP" ]; then
        if [ "$MODE" = native ]; then
            wget -q --show-progress -O "$VOSK_MODEL_ZIP" "$VOSK_URL"
        else
            timeout 180 wget -q -T 30 --tries=1 -O "$VOSK_MODEL_ZIP" "$VOSK_URL" 2>/dev/null || true
        fi
    fi
    if [ -f "$VOSK_MODEL_ZIP" ] && [ -s "$VOSK_MODEL_ZIP" ]; then
        python3 -m zipfile -e "$VOSK_MODEL_ZIP" .
        rm -f "$VOSK_MODEL_ZIP"
        echo "✅ Модель Vosk установлена в $VOSK_MODEL_PATH"
    else
        echo "⚠️ Модель Vosk не скачалась (сеть/таймаут). Для образа модель — runtime-актив."
        rm -f "$VOSK_MODEL_ZIP" 2>/dev/null || true
    fi
    popd >/dev/null
else
    echo "ℹ️ Модель Vosk не качаем (docker/prepare): runtime-актив; --models — чтобы положить в контекст"
fi

# mujoco_playground (locomotion/rds2p) — вендорный subset прямо в репозитории
# (ros_packages/deps/mujoco_playground). Внешних клонов нет; если каталога нет —
# desktop собирается без twin (warn, как в desktop.Dockerfile).
SIM_DEPS_DIR="$ROSPKG_DIR/deps"
mkdir -p "$SIM_DEPS_DIR"
touch "$SIM_DEPS_DIR/COLCON_IGNORE"
if [ ! -d "$SIM_DEPS_DIR/mujoco_playground/_src" ]; then
    echo "⚠️  ros_packages/deps/mujoco_playground отсутствует — desktop будет собран без twin" >&2
else
    echo "ℹ️ $SIM_DEPS_DIR/mujoco_playground на месте (vendored)"
fi

# obj-меши для twin: canonical-источник — urdf_src/export/.../meshes/obj (GIT, по
# аналогии с dae для URDF), в subset-е в git не лежат — кладутся сюда при prepare.
MP_MESHES="$SIM_DEPS_DIR/mujoco_playground/_src/locomotion/rds2p/xmls/meshes"
URDF_OBJ_DIR="$ROOT_DIR/urdf_src/export/rds-2p/meshes/obj"
if [ -d "$SIM_DEPS_DIR/mujoco_playground/_src" ]; then
    if [ ! -d "$URDF_OBJ_DIR" ] || [ -z "$(ls -A "$URDF_OBJ_DIR" 2>/dev/null)" ]; then
        echo "ERROR: subset mujoco_playground на месте, но obj-меши не найдены в urdf_src/export/rds-2p/meshes/obj — twin упадёт на base.obj" >&2
        exit 1
    fi
    mkdir -p "$MP_MESHES"
    cp -a "$URDF_OBJ_DIR/." "$MP_MESHES/"
    echo "📦 twin-меши (.obj) скопированы в deps/mujoco_playground."
fi

# меши rds_2p: в git не лежат (rds_2p/.gitignore), берутся из urdf_src/export —
# как это делает urdf_src/update_rds2p.sh. Нужны для install(DIRECTORY meshes) в colcon.
if [ ! -d "$ROSPKG_DIR/src/rds_2p/meshes/dae" ] && [ -d "$ROOT_DIR/urdf_src/export/rds-2p/meshes/dae" ]; then
    echo "📥 Копируем меши rds_2p из urdf_src/export..."
    mkdir -p "$ROSPKG_DIR/src/rds_2p/meshes"
    cp -a "$ROOT_DIR/urdf_src/export/rds-2p/meshes/dae" "$ROSPKG_DIR/src/rds_2p/meshes/"
fi

# Модель RNNoise (rnnoise_data-<ver>.tar.gz): native предзагружает в deps/, чтобы
# сборка не зависела от media.xiph.org (в контейнере она часто недоступна).
# В docker/prepare — только с --models; без него Dockerfile попробует сам (time-boxed).
RNN_VER="$(cat "$SIM_DEPS_DIR/rnnoise_src/model_version" 2>/dev/null || echo 0b50c45)"
RNN_MODEL_TGZ="$SIM_DEPS_DIR/rnnoise_data-$RNN_VER.tar.gz"
if [ -s "$RNN_MODEL_TGZ" ]; then
    echo "ℹ️ Модель RNNoise уже на месте: $RNN_MODEL_TGZ"
elif [ "$MODE" = native ] || [ "$MODELS" = true ]; then
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
        echo "⚠️  Модель RNNoise не скачалась — сборка/Dockerfile попробует зеркала сам, иначе audio_filters будет пропущен."
    fi
else
    echo "ℹ️ Модель RNNoise не качаем (docker/prepare): попробует Dockerfile или --models"
fi

# ================= docker/prepare: хвост контекста и сборка образа =================
if [ "$MODE" != native ]; then
    cp -f "$DOCKER_DIR/.dockerignore" "$ROOT_DIR/.dockerignore"

    if [ "$MODE" = prepare ]; then
        echo "✅ Контекст desktop-сборки подготовлен (--prepare-only/PREPARE_ONLY=1) — docker build пропущен"
        show_duration
        exit 0
    fi

    if ! docker info >/dev/null 2>&1; then
        echo "❌ Docker daemon недоступен. Проверьте: sudo systemctl start docker / группы docker."
        exit 1
    fi

    echo "🐳 docker build -f docker/desktop.Dockerfile -t $IMAGE"
    docker build -f "$DOCKER_DIR/desktop.Dockerfile" -t "$IMAGE" "$ROOT_DIR"

    rm -f "$ROOT_DIR/.dockerignore"
    echo "✅ Образ $IMAGE собран. Запуск: docker/run_desktop.sh"
    show_duration
    exit 0
fi

# ================= native: установка в живую систему =================

# Устанавливаем desktop-зависимости (rviz2, xacro)
echo "🖥️ Проверяем и устанавливаем desktop-зависимости..."
DESKTOP_DEPS_MISSING=false
if ! dpkg -s ros-${ROS_DISTRO:-humble}-rviz2 >/dev/null 2>&1; then
    echo "   📦 rviz2 не установлен"
    DESKTOP_DEPS_MISSING=true
fi
if ! dpkg -s ros-${ROS_DISTRO:-humble}-xacro >/dev/null 2>&1; then
    echo "   📦 xacro не установлен"
    DESKTOP_DEPS_MISSING=true
fi

if [ "$DESKTOP_DEPS_MISSING" = true ]; then
    echo "🔐 Устанавливаем desktop-зависимости (требуется sudo)..."
    sudo apt update -qq
    sudo apt install -y ros-${ROS_DISTRO:-humble}-rviz2 ros-${ROS_DISTRO:-humble}-xacro
    echo "✅ Desktop-зависимости установлены"
else
    echo "✅ Desktop-зависимости уже установлены"
fi

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
        INSTALL_CMD="uv pip install --python /usr/bin/python3 --target=$ROS_PYTHON_DIR"
    else
        INSTALL_CMD="/usr/bin/python3 -m pip install --target=$ROS_PYTHON_DIR"
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

# SoXR для audio_filters/RNNoise (менее приоритетно, перед colcon)
echo "🔊 [опционально] libsoxr-dev для audio_filters..."
if ! dpkg -s libsoxr-dev >/dev/null 2>&1; then
    echo "📦 Устанавливаем libsoxr-dev (sudo apt)..."
    sudo apt-get install -y libsoxr-dev
    echo "✅ libsoxr-dev установлен"
else
    echo "ℹ️ libsoxr-dev уже установлен"
fi

# Собираем все пакеты кроме...
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
echo "🔨 Собираем пакеты (кроме тех, что запускаются только на роботе, и orbbec_camera - собираем только сообщения, mtf02p_ros - только на роботе)"

COLCON_SKIP_EXTRA=""
if [[ ! -f "${RNN_INST}/lib/librnnoise.a" ]]; then
    COLCON_SKIP_EXTRA="audio_filters"
    echo "⚠️  audio_filters в сборку не входит (нет собранного RNNoise)."
fi
colcon build --parallel-workers "${JOBS}" --symlink-install --packages-skip mpu6500_ros rds_2p_joystick orbbec_camera mtf02p_ros rkllm_ros2 ${COLCON_SKIP_EXTRA} --packages-ignore rds_2p_face

echo "✅ Готово! Загрузите переменные: source install/setup.bash"

# Добавляем в .bashrc если еще не добавлено
echo "📝 Добавляем в .bashrc..."
BASH_SOURCE_LINE="source $(pwd)/install/setup.bash"
if ! grep -q "$(pwd)/install/setup.bash" ~/.bashrc; then
    echo "" >> ~/.bashrc
    echo "# RDS-2P desktop packages" >> ~/.bashrc
    echo "$BASH_SOURCE_LINE" >> ~/.bashrc
    echo "✅ Добавлено в .bashrc"
else
    echo "ℹ️ Уже добавлено в .bashrc"
fi

echo "🔄 Загружаем переменные окружения..."
source install/setup.bash
echo "✅ Переменные загружены!"

show_duration
