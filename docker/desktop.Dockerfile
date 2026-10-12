ARG ROS_BASE=ros:humble-ros-base

FROM ${ROS_BASE} AS builder
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget unzip git \
      cmake build-essential pkg-config autoconf automake libtool \
      python3-pip python3-opencv python3-numpy \
      python3-colcon-common-extensions \
      libsoxr-dev libasound2-dev \
      libgl1-mesa-dev libglu1-mesa-dev libx11-dev libxrandr-dev libxi-dev \
      libxxf86vm-dev libxcursor-dev libxinerama-dev libxkbcommon-dev \
    && rm -rf /var/lib/apt/lists/*

COPY ros_packages /opt/rds2p/ros-ws

# onnxruntime SDK кладёт в контекст prepare (docker/build_desktop.sh ->
# ros_packages/scripts/fetch_onnxruntime.sh, единый источник логики со сборкой на хосте).
# Здесь только проверка, что COPY принёс SDK нужной TARGETARCH-архитектуры.
RUN set -eux; \
    A="${TARGETARCH:-$(uname -m)}"; \
    case "$A" in \
      amd64|x86_64) ORT=onnxruntime-linux-x64-1.19.2 ;; \
      arm64|aarch64) ORT=onnxruntime-linux-aarch64-1.19.2 ;; \
      *) echo "unsupported arch: $A" >&2; exit 1 ;; \
    esac; \
    mkdir -p /opt/rds2p/ros-ws/src/rds_2p_inference/external_lib; \
    cd /opt/rds2p/ros-ws/src/rds_2p_inference/external_lib; \
    if [ ! -d "$ORT" ]; then \
      if [ -f "$ORT.tgz" ]; then tar -xf "$ORT.tgz"; rm -f "$ORT.tgz"; \
      else echo "ERROR: $ORT нет в контексте — собирай через docker/build_desktop.sh (он вызывает ros_packages/scripts/fetch_onnxruntime.sh)"; exit 1; fi; \
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
      ./autogen.sh; \
      ./configure --prefix=/opt/rds2p/ros-ws/deps/rnnoise_install --disable-examples; \
      make -j"$(nproc)"; \
      make install; \
    fi

# Runtime-pip только из нужного: twin = mujoco+etils+glfw+numba (без jax/flax/brax —
# они нужны только тренировочному окружению, из requirements.txt в образ не берём)
RUN cd /opt/rds2p/ros-ws \
    && python3 -m pip install --no-cache-dir \
         etils "mujoco==3.3.5" glfw numba \
         -r src/vosk_ros2/requirements.txt \
         -r src/rds_2p_telegram_bot/requirements.txt \
         "numpy<2" sounddevice

RUN mkdir -p /opt/rds2p/ros-ws/deps/mujoco_playground; \
    if [ -z "$(ls -A /opt/rds2p/ros-ws/deps/mujoco_playground)" ]; then \
      echo "WARNING: deps/mujoco_playground пуст — twin не запустится; собирайте через docker/build_desktop.sh"; \
    fi

RUN cd /opt/rds2p/ros-ws \
    && . /opt/ros/humble/setup.sh \
    && colcon build --parallel-workers "$(nproc)" \
         --install-base /opt/rds2p/install --build-base /tmp/colcon-build \
         --packages-skip mpu6500_ros rds_2p_joystick orbbec_camera mtf02p_ros rkllm_ros2 \
         --packages-ignore rds_2p_face

RUN for d in /opt/rds2p/install/*/lib; do \
      if [ -f "$d/libonnxruntime.so.1.19.2" ]; then \
        ln -sf libonnxruntime.so.1.19.2 "$d/libonnxruntime.so.1"; \
      fi; \
    done

FROM ${ROS_BASE} AS runtime
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libasound2 libsoxr0 libportaudio2 libglfw3 \
      libgl1 libglu1-mesa libegl1 libgles2 \
      libx11-6 libxrandr2 libxi6 libxxf86vm1 libxcursor1 libxinerama1 libxkbcommon0 \
      libwayland-client0 libglib2.0-0 \
      python3-opencv python3-numpy python3-pil python3-yaml python3-scipy \
      ros-humble-robot-state-publisher ros-humble-xacro \
      ros-humble-joint-state-publisher \
      ros-humble-cv-bridge ros-humble-image-transport \
      ros-humble-tf2-ros ros-humble-teleop-twist-keyboard \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/rds2p/install /opt/rds2p/install
COPY --from=builder /opt/rds2p/ros-ws/deps/mujoco_playground /opt/rds2p/deps/mujoco_playground
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "rds_2p_inference", "virtual_twin_desktop.launch.py"]
