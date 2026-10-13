ARG ROS_BASE=ros:humble-ros-base

FROM ${ROS_BASE} AS builder
ARG DEBIAN_FRONTEND=noninteractive
ARG NPU=0
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget unzip git \
      cmake build-essential pkg-config autoconf automake libtool \
      python3-pip python3-opencv python3-numpy \
      python3-colcon-common-extensions \
      libgpiod-dev libsoxr-dev libasound2-dev libudev-dev libusb-1.0-0-dev \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && (apt-get install -y --no-install-recommends ros-humble-orbbec-camera \
        && touch /tmp/orbbec-apt-ok \
        && echo "orbbec_camera взят из apt") \
    || echo "ros-humble-orbbec-camera недоступен в apt — пробуем собрать из исходников"
RUN rm -rf /var/lib/apt/lists/*

COPY ros_packages /opt/rds2p/ros-ws

# onnxruntime SDK кладёт в контекст prepare (docker/build_robot.sh ->
# ros_packages/scripts/fetch_onnxruntime.sh; можно положить и $ORT.tgz руками —
# офлайн на роботе). Здесь только распаковка tgz/проверка наличия.
RUN set -eux; \
    mkdir -p /opt/rds2p/ros-ws/src/rds_2p_inference/external_lib; \
    cd /opt/rds2p/ros-ws/src/rds_2p_inference/external_lib; \
    ORT=onnxruntime-linux-aarch64-1.19.2; \
    if [ ! -d "$ORT" ]; then \
      if [ -f "$ORT.tgz" ]; then tar -xf "$ORT.tgz"; rm -f "$ORT.tgz"; \
      else echo "ERROR: $ORT нет в контексте — собирай через docker/build_robot.sh (он вызывает ros_packages/scripts/fetch_onnxruntime.sh)"; exit 1; fi; \
    fi

RUN if [ -d /opt/rds2p/ros-ws/src/OrbbecSDK_ROS2/orbbec_camera ]; then \
      cp -f /opt/rds2p/ros-ws/scripts/orbbec_camera_patches/astra_mini.launch.py \
            /opt/rds2p/ros-ws/src/OrbbecSDK_ROS2/orbbec_camera/launch/astra_mini.launch.py; \
    fi

RUN rosdep init || true \
    && rosdep update --rosdistro=humble \
    && apt-get update \
    && rosdep install --from-paths /opt/rds2p/ros-ws/src --ignore-src -r -y \
         --skip-keys "python3-sounddevice python3-aiogram"

RUN set -eux; \
    cd /opt/rds2p/ros-ws; \
    if [ ! -f deps/rnnoise_install/lib/librnnoise.a ]; then \
      mkdir -p deps; \
      git clone --depth 1 --branch v0.2 https://github.com/xiph/rnnoise.git deps/rnnoise_src; \
      cp -f src/audio_filters/third_party/rnnoise/rnnoise_os_support_stub.h deps/rnnoise_src/src/os_support.h; \
      cd deps/rnnoise_src; \
      RV=$(cat model_version); \
      if [ ! -f "rnnoise_data-$RV.tar.gz" ] && [ -f "../rnnoise_data-$RV.tar.gz" ]; then \
        cp -f "../rnnoise_data-$RV.tar.gz" .; \
      fi; \
      if [ ! -f "rnnoise_data-$RV.tar.gz" ]; then \
        timeout 120 curl -fsSL --connect-timeout 15 -o "rnnoise_data-$RV.tar.gz" "https://cdn.netbsd.org/pub/pkgsrc/distfiles/rnnoise-0.2/rnnoise_data-$RV.tar.gz" || rm -f "rnnoise_data-$RV.tar.gz"; \
      fi; \
      if [ ! -f "rnnoise_data-$RV.tar.gz" ]; then \
        timeout 90 sh ./download_model.sh || true; \
      fi; \
      if [ ! -f "rnnoise_data-$RV.tar.gz" ] || ! tar -tzf "rnnoise_data-$RV.tar.gz" >/dev/null 2>&1; then \
        echo "WARNING: rnnoise model недоступен — пропускаю сборку rnnoise и audio_filters"; \
        rm -f "rnnoise_data-$RV.tar.gz"; \
        touch /tmp/rnnoise-skip; \
      else \
        ./autogen.sh; \
        ./configure --prefix=/opt/rds2p/ros-ws/deps/rnnoise_install --disable-examples; \
        make -j"$(nproc)"; \
        make install; \
      fi; \
    fi

# Runtime-pip только из нужного: twin = mujoco+etils+glfw+numba (без jax/flax/brax —
# они нужны только тренировочному окружению, из requirements.txt в образ не берём)
RUN cd /opt/rds2p/ros-ws \
    && python3 -m pip install --no-cache-dir \
         etils "mujoco==3.3.5" glfw numba \
         -r src/vosk_ros2/requirements.txt \
         -r src/rds_2p_telegram_bot/requirements.txt \
          "numpy<2" sounddevice ds4drv

# Колонки colcon: на 2GB SBC 4 компилятора параллельно вызывают OOM — build_robot.sh
# считает значение по MemTotal. Ручной override: --build-arg BUILD_WORKERS=N.
# Объявлен прямо перед RUN, т.к. ARG в начале стадии инвалидирует кэш всех нижних слоёв.
ARG BUILD_WORKERS=4
# set -ex (без -u): ROS setup.sh использует $AMENT_TRACE_SETUP_FILES без дефолта —
# под set -u источник падает с "parameter not set"
RUN set -ex; \
    cd /opt/rds2p/ros-ws; \
    . /opt/ros/humble/setup.sh; \
    SKIP=""; \
    if [ "${NPU}" = "0" ]; then \
      SKIP="$SKIP rkllm_ros2"; \
      echo "INFO: NPU=0 — rkllm_ros2 НЕ собран (платформа без RK NPU). Команды работают, LLM-экшены отключены."; \
    else \
      for f in vendor/lib/librkllmrt.so vendor/lib/librknnrt.so vendor/include/rkllm.h vendor/include/rknn_api.h; do \
        if [ ! -f "src/rkllm_ros2/$f" ]; then SKIP="$SKIP rkllm_ros2"; break; fi; \
      done; \
      if [ -n "$SKIP" ]; then echo "WARNING: rkllm_ros2 НЕ собран (нет vendor RK-рантайма)"; fi; \
    fi; \
    if [ "${NPU}" = "1" ] && echo "$SKIP" | grep -q rkllm_ros2; then \
      echo "ERROR: NPU=1 запрошен, но vendor RK-рантайм отсутствует. Положите .so/заголовки по rkllm_ros2/vendor/README.md."; \
      exit 1; \
    fi; \
    if [ -f /tmp/orbbec-apt-ok ]; then SKIP="$SKIP orbbec_camera orbbec_camera_msgs orbbec_description"; fi; \
    if [ -f /tmp/rnnoise-skip ] || [ ! -f deps/rnnoise_install/lib/librnnoise.a ]; then \
      SKIP="$SKIP audio_filters"; \
      echo "WARNING: audio_filters пропущен (rnnoise недоступен)"; \
    fi; \
    colcon build --parallel-workers "${BUILD_WORKERS}" \
      --install-base /opt/rds2p/install --build-base /tmp/colcon-build \
      ${SKIP:+--packages-skip} ${SKIP}; \
    if [ ! -f /tmp/orbbec-apt-ok ] && [ -d src/OrbbecSDK_ROS2 ]; then \
      . /opt/ros/humble/setup.sh; \
      . /opt/rds2p/install/setup.sh; \
      colcon build --parallel-workers "${BUILD_WORKERS}" \
        --install-base /opt/rds2p/install --build-base /tmp/colcon-build \
        --packages-select orbbec_camera orbbec_camera_msgs orbbec_description \
        || echo "WARNING: orbbec_camera из исходников не собрался — камера в этом образе недоступна"; \
    fi

RUN for d in /opt/rds2p/install/*/lib; do \
      if [ -f "$d/libonnxruntime.so.1.19.2" ]; then \
        ln -sf libonnxruntime.so.1.19.2 "$d/libonnxruntime.so.1"; \
      fi; \
    done

FROM ${ROS_BASE} AS runtime
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libasound2 libgpiod2 libsoxr0 libudev1 libusb-1.0-0 libportaudio2 \
      alsa-utils \
      libglfw3 libgl1 libegl1 libgles2 \
      python3-opencv python3-numpy python3-pil python3-yaml python3-scipy \
      ros-humble-robot-state-publisher ros-humble-xacro \
      ros-humble-joint-state-publisher \
      ros-humble-cv-bridge ros-humble-image-transport \
      ros-humble-compressed-image-transport ros-humble-compressed-depth-image-transport \
      ros-humble-tf2-ros ros-humble-teleop-twist-keyboard \
      ros-humble-joy ros-humble-teleop-twist-joy \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update \
    && (apt-get install -y --no-install-recommends ros-humble-orbbec-camera \
        || echo "orbbec из apt недоступен, используем версию из install-дерева") \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/rds2p/install /opt/rds2p/install
COPY --from=builder /opt/rds2p/ros-ws/deps/mujoco_playground /opt/rds2p/deps/mujoco_playground
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "rds_2p", "rds_2p_complete.launch.py"]
