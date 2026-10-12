ARG ROS_BASE=ros:humble-ros-base

FROM ${ROS_BASE} AS builder
ARG DEBIAN_FRONTEND=noninteractive
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

RUN cd /opt/rds2p/ros-ws/src/rds_2p_inference/external_lib \
    && tar -xf onnxruntime-linux-aarch64-1.19.2.tgz

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
      ./autogen.sh; \
      ./configure --prefix=/opt/rds2p/ros-ws/deps/rnnoise_install --disable-examples; \
      make -j"$(nproc)"; \
      make install; \
    fi

RUN cd /opt/rds2p/ros-ws \
    && python3 -m pip install --no-cache-dir \
         -r src/vosk_ros2/requirements.txt \
         -r src/rds_2p_telegram_bot/requirements.txt \
         "numpy<2" sounddevice ds4drv

RUN set -eux; \
    cd /opt/rds2p/ros-ws; \
    . /opt/ros/humble/setup.sh; \
    SKIP=""; \
    for f in vendor/lib/librkllmrt.so vendor/lib/librknnrt.so vendor/include/rkllm.h vendor/include/rknn_api.h; do \
      if [ ! -f "src/rkllm_ros2/$f" ]; then SKIP="$SKIP rkllm_ros2"; break; fi; \
    done; \
    if [ -n "$SKIP" ]; then echo "WARNING: rkllm_ros2 НЕ собран (нет vendor RK-рантайма)"; fi; \
    if [ -f /tmp/orbbec-apt-ok ]; then SKIP="$SKIP orbbec_camera orbbec_camera_msgs orbbec_description"; fi; \
    colcon build --parallel-workers "$(nproc)" \
      --install-base /opt/rds2p/install --build-base /tmp/colcon-build \
      ${SKIP:+--packages-skip} ${SKIP}; \
    if [ ! -f /tmp/orbbec-apt-ok ] && [ -d src/OrbbecSDK_ROS2 ]; then \
      . /opt/ros/humble/setup.sh; \
      . /opt/rds2p/install/setup.sh; \
      colcon build --parallel-workers "$(nproc)" \
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
      python3-opencv python3-numpy python3-pil python3-yaml python3-scipy \
      ros-humble-robot-state-publisher ros-humble-xacro \
      ros-humble-joint-state-publisher ros-humble-joint-state-publisher-gui \
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
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "rds_2p", "rds_2p_complete.launch.py"]
