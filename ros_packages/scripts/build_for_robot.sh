#!/bin/bash

# Сборка всех пакетов для робота RDS-2P
set -e

# Определяем путь к самому скрипту (для кэша)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Парсим аргументы командной строки
ROS_DEPS_IGNORE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --ros-deps-ignore)
            ROS_DEPS_IGNORE=true
            shift
            ;;
        *)
            echo "Неизвестный аргумент: $1"
            echo "Использование: $0 [--ros-deps-ignore]"
            exit 1
            ;;
    esac
done

echo "🤖 Сборка пакетов для робота..."

# Засекаем время начала выполнения скрипта
SCRIPT_START_TIME=$(date +%s)

# Проверяем директорию
if [ ! -d "src" ]; then
    echo "❌ Запускайте из директории ros_packages"
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
    # Проверяем, что это действительно git репозиторий
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

# Скачиваем модель Vosk если её нет
VOSK_MODEL_PATH="src/vosk_ros2/models/vosk-model-small-ru-0.22"
VOSK_MODEL_DIR="src/vosk_ros2/models"
if [ ! -d "$VOSK_MODEL_PATH" ]; then
    echo "📥 Скачиваем модель Vosk (vosk-model-small-ru-0.22)..."
    mkdir -p "$VOSK_MODEL_DIR"
    pushd "$VOSK_MODEL_DIR" >/dev/null
    VOSK_MODEL_ZIP="vosk-model-small-ru-0.22.zip"
    if [ ! -f "$VOSK_MODEL_ZIP" ]; then
        wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
    fi
    if [ -f "$VOSK_MODEL_ZIP" ]; then
        # Используем Python для распаковки ZIP (не требует установки unzip)
        python3 -m zipfile -e "$VOSK_MODEL_ZIP" .
        rm -f "$VOSK_MODEL_ZIP"
        echo "✅ Модель Vosk установлена в $VOSK_MODEL_PATH"
    else
        echo "⚠️ Не удалось скачать модель Vosk"
    fi
    popd >/dev/null
else
    echo "ℹ️ Модель Vosk уже установлена: $VOSK_MODEL_PATH"
fi

# Устанавливаем Python-зависимости из всех requirements.txt (после скачивания всех пакетов)
echo "🐍 Ищем и устанавливаем Python-зависимости..."
REQ_FILES=$(find "src" -maxdepth 2 -name "requirements.txt" -type f 2>/dev/null)

# Кэш для хэшей requirements (чтобы не переустанавливать без изменений)
CACHE_FILE="$SCRIPT_DIR/.requirements_cache"
declare -A REQ_CACHE
if [ -f "$CACHE_FILE" ]; then
    while IFS='|' read -r path hash; do
        REQ_CACHE["$path"]="$hash"
    done < "$CACHE_FILE"
fi
if [ -n "$REQ_FILES" ]; then
    ROS_PYTHON_DIR="/opt/ros/${ROS_DISTRO:-humble}/local/lib/python3.10/dist-packages"
    
    # Проверяем права доступа к директории
    if [ -d "$ROS_PYTHON_DIR" ]; then
        if [ ! -w "$ROS_PYTHON_DIR" ]; then
            echo "🔐 Директория $ROS_PYTHON_DIR принадлежит root, исправляем права (требуется sudo)..."
            sudo chown -R $USER:$USER "$ROS_PYTHON_DIR"
            echo "✅ Права доступа исправлены"
        fi
    else
        # Директория не существует - вероятно ROS не установлен
        echo "❌ Директория $ROS_PYTHON_DIR не существует!" >&2
        echo "   Убедитесь, что ROS 2 Humble установлен правильно:" >&2
        echo "   sudo apt install ros-humble-desktop" >&2
        exit 1
    fi
    
    # Выбираем команду установки (uv если есть, иначе pip)
    if command -v uv &> /dev/null; then
        echo "   ⚡ Используем uv для ускорения"
        # Явно указываем системный Python, чтобы игнорировать активный venv и использовать правильную версию для ROS
        INSTALL_CMD="uv pip install --upgrade --python /usr/bin/python3 --target=$ROS_PYTHON_DIR"
    else
        # Используем системный pip напрямую
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

    # Сохраняем кэш
    : > "$CACHE_FILE"
    for path in "${!REQ_CACHE[@]}"; do
        echo "${path}|${REQ_CACHE[$path]}" >> "$CACHE_FILE"
    done

    echo "✅ Python-зависимости проверены в $ROS_PYTHON_DIR"
else
    echo "ℹ️ requirements.txt файлы не найдены в src/"
fi

# Установка ds4drv (PS4 контроллер драйвер)
echo "🎮 Проверяем установку ds4drv..."
if ! command -v ds4drv &> /dev/null; then
    echo "📥 Устанавливаем ds4drv..."
    if command -v pip3 &> /dev/null; then
        sudo pip3 install ds4drv
        echo "✅ ds4drv установлен через pip3"
    elif command -v pip &> /dev/null; then
        sudo pip install ds4drv
        echo "✅ ds4drv установлен через pip"
    else
        echo "⚠️ pip не найден. Установите ds4drv вручную: sudo pip3 install ds4drv"
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
    
    # Применяем правила
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
        # Подавляем предупреждения о deprecation
        export PYTHONWARNINGS="ignore::DeprecationWarning"
        
        # Оптимизация: обновляем rosdep только если прошло больше 24 часов
        ROSDEP_CACHE_DIR="$HOME/.ros/rosdep"
        ROSDEP_UPDATE_INTERVAL=86400  # 24 часа в секундах
        NEED_UPDATE=true
        
        if [ -d "$ROSDEP_CACHE_DIR" ]; then
            # Находим самый новый файл в кэше (используем stat для совместимости)
            if command -v stat &> /dev/null; then
                # Получаем время модификации самого нового файла
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
        
        # Проверяем, инициализирован ли rosdep (до попытки update/install)
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
                # Обновляем только нужный дистрибутив, чтобы не загружать end-of-life дистрибутивы
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
    # Модель rnnoise: локальный tarball в deps/ (предзагружен), иначе time-boxed-загрузка
    # с зеркал (media.xiph.org из роботов часто недоступна). Без модели — пропускаем rnnoise.
    RNN_VER="$(cat "${RNN_SRC}/model_version" 2>/dev/null || echo 0b50c45)"
    RNN_MODEL_TGZ="$(pwd)/deps/rnnoise_data-${RNN_VER}.tar.gz"
    RNN_MODEL_LOCAL="${RNN_SRC}/rnnoise_data-${RNN_VER}.tar.gz"
    if [[ ! -f "${RNN_MODEL_LOCAL}" ]] && [[ -s "${RNN_MODEL_TGZ}" ]]; then
        cp -f "${RNN_MODEL_TGZ}" "${RNN_MODEL_LOCAL}"
        echo "ℹ️ Модель RNNoise взята из deps/ (локальный tarball)."
    fi
    if [[ ! -f "${RNN_MODEL_LOCAL}" ]]; then
        echo "📥 Скачиваем модель RNNoise (time-boxed, зеркала)..."
        for url in \
            "https://cdn.netbsd.org/pub/pkgsrc/distfiles/rnnoise-0.2/rnnoise_data-${RNN_VER}.tar.gz" \
            "https://media.xiph.org/rnnoise/models/rnnoise_data-${RNN_VER}.tar.gz"; do
            if timeout 240 curl -fL --connect-timeout 15 --max-time 230 -o "${RNN_MODEL_LOCAL}" "$url" 2>/dev/null \
               && [[ -s "${RNN_MODEL_LOCAL}" ]] && tar -tzf "${RNN_MODEL_LOCAL}" >/dev/null 2>&1; then
                cp -f "${RNN_MODEL_LOCAL}" "${RNN_MODEL_TGZ}"
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
echo "🔨 Собираем пакеты..."
COLCON_SKIP=""
if [[ ! -f "${RNN_INST}/lib/librnnoise.a" ]]; then
    COLCON_SKIP="--packages-skip audio_filters"
    echo "⚠️  audio_filters в сборку не входит (нет собранного RNNoise)."
fi
# Колонки colcon по MemTotal (как в docker/build_robot.sh): на 2GB SBC 4 компилятора
# параллельно ловят OOM, на длинных сборкахworkers=2; на RAM>=4 — все ядра.
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

# Вычисляем и выводим общее время выполнения скрипта
SCRIPT_END_TIME=$(date +%s)
SCRIPT_DURATION=$((SCRIPT_END_TIME - SCRIPT_START_TIME))
HOURS=$((SCRIPT_DURATION / 3600))
MINUTES=$(((SCRIPT_DURATION % 3600) / 60))
SECONDS=$((SCRIPT_DURATION % 60))

echo ""
echo "⏱️  Общее время выполнения скрипта:"
if [ $HOURS -gt 0 ]; then
    echo "   ${HOURS}ч ${MINUTES}м ${SECONDS}с"
elif [ $MINUTES -gt 0 ]; then
    echo "   ${MINUTES}м ${SECONDS}с"
else
    echo "   ${SECONDS}с"
fi
