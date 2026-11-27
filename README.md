# RDS-2P Software

![Deploy](https://github.com/ShiWarai/RDS-2P-software/actions/workflows/deploy.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![ROS 2](https://img.shields.io/badge/ROS%202-Humble-blueviolet.svg)
![platform](https://img.shields.io/badge/platform-linux%20amd64%20%7C%20arm64-orange.svg)
![docker](https://img.shields.io/badge/docker-GHCR-blue.svg)

Программное обеспечение для квадропеда RDS-2P: ROS 2 workspace, модели (URDF/MJCF), веб-симуляция на MuJoCo WASM, самодостаточные Docker-образы и материалы по обратной кинематике.

## Структура репозитория

| Каталог | Содержимое |
|---------|------------|
| [`ros_packages/`](ros_packages/README.md) | Colcon workspace: пакет `rds_2p`, драйверы, инференс, телеметрия и др. |
| [`ros_packages/scripts/`](ros_packages/scripts/) | Скрипты быстрой сборки (`build_for_desktop.sh`, `build_for_robot.sh`) и вспомогательные утилиты |
| `urdf_src/` | Исходники/черновики URDF |
| `mjcf_src/` | Скрипты и конфигурации для MJCF |
| `experiments/inverse_kinematic/` | Наброски по обратной кинематике |
| [`experiments/wasm_demo/`](experiments/wasm_demo/README.md) | Простая браузерная симуляция (MuJoCo + three.js) |
| [`experiments/rds-2p_mujoco_wasm/`](experiments/rds-2p_mujoco_wasm/README.md) | Веб-симулятор «Панда»: MuJoCo WASM + ONNX-политика ходьбы, Laya, Vosk |
| [`docker/`](docker/README.md) | Docker-образы desktop / robot / web на `ros:humble-ros-base` |

Подробная установка и запуск ROS 2 — в [ros_packages/README.md](ros_packages/README.md).

## Docker-образы (без ROS на хосте)

Вместо нативной сборки можно использовать самодостаточные образы на `ros:humble-ros-base` — весь ROS 2-стек RDS-2P живёт внутри контейнера, на хостах ROS 2 не нужен:

| Образ | Арх | Назначение |
|---|---|---|
| `rds2p/desktop:humble` | amd64 | twin-симуляция MuJoCo GUI (WSL/WSLg) |
| `rds2p/robot:humble` | arm64 | всё железо робота (RK3588: IMU, камера, голос, NPU) |
| `rds2p/web:latest` | amd64/arm64 | веб-мастер-класс «Панда» в браузере, без ROS |

Сборка и запуск — скрипты из [`docker/`](docker/README.md). CI публикует образы в GHCR: `ghcr.io/<owner>/rds-2p-software-{desktop,robot,web}` (теги `:main` — после зелёного Deploy на `main`, `:prerelease` — с `[prerelease]` в коммите `dev`). Подробности — [docker/README.md](docker/README.md).

## Быстрый старт (ROS 2)

Сборку и зависимости проще всего поднять готовыми скриптами из [`ros_packages/scripts/`](ros_packages/scripts/) (нужны установленный ROS 2 Humble, `git`, сеть; для шагов с пакетами — `sudo`). Перед первым запуском подключите окружение ROS, если оно ещё не в `~/.bashrc`:

```bash
source /opt/ros/humble/setup.bash
```

**Рабочий ПК / симуляция и разработка без полного набора «роботных» пакетов** — скрипт сам переходит в `ros_packages`, тянет внешние репозитории (Orbbec SDK для сообщений, FTServoLibrary, ONNX x64, audio/vosk и т.д.), ставит зависимости и собирает workspace с пропуском пакетов вроде `mpu6500_ros` и узкоспециализированных узлов под железо робота:

```bash
# из корня репозитория
bash ros_packages/scripts/build_for_desktop.sh
```

**Борт робота (полная сборка под ARM, IMU, джойстик, камера и т.д.)** — скрипт нужно запускать **из каталога `ros_packages`**:

```bash
cd ros_packages
./scripts/build_for_robot.sh
```

У обоих скриптов есть опция `--ros-deps-ignore`, если нужно пропустить `rosdep install`. После успешной сборки окружение подхватывается через `source install/setup.bash` (скрипты также дописывают эту строку в `~/.bashrc`, если её ещё не было). Путь в `~/.bashrc` фиксируется на момент сборки; если репозиторий потом перенесли в другой каталог, обновите эту строку вручную.

**Первый запуск на новой машине:** один раз выполните `sudo rosdep init` и `rosdep update` (если ещё не делали), иначе скрипты остановятся с подсказкой.

**Смещения суставов:** до сборки скопируйте `src/rds_2p/config/joint_offsets_example.yaml` в `src/rds_2p/config/joint_offsets.yaml` и при необходимости откалибруйте — иначе `bridge_motors_to_joints` по умолчанию укажет на файл, которого нет в установленном пакете. Подробнее — [ros_packages/README.md](ros_packages/README.md).

Ручная последовательность `rosdep` + `colcon build` описана в [ros_packages/README.md](ros_packages/README.md), если скрипты использовать не нужно.

Скрипт **`build_for_desktop.sh` не собирает** пакеты `mpu6500_ros`, `orbbec_camera`, `mtf02p_ros`, `rds_2p_joystick`, `rds_2p_face` (см. `--packages-skip` в скрипте). Команды ниже для IMU, камеры и телеопа с джойстиком из этого репозитория рассчитаны на **`build_for_robot.sh`** или на отдельную сборку нужных пакетов. Пакет `teleop_twist_joy` ставится из дистрибутива ROS (`ros-humble-teleop-twist-joy`), его launch доступен после установки зависимостей.

Примеры запуска (окружение — `source install/setup.bash`; имя пакета модели — **`rds_2p`**). Пути вида `$(pwd)/src/...` верны, если текущий каталог — **`ros_packages`**; иначе укажите абсолютный путь к YAML или путь внутри `install/`.

```bash
# Базовая цепочка моторы → joint_states → RViz (конфиг моторов обязателен)
ros2 launch ftservo_ros motor_controller.launch.py \
  interface:=/dev/ttyS7 \
  config_file:=$(pwd)/src/ftservo_ros/config/config_example.yaml \
  is_sim:=false \
  log_level:=ERROR

ros2 launch rds_2p bridge_motors_to_joints.launch.py

ros2 launch rds_2p sim/display.launch.py

# Дополнительно (нужна сборка робота / соответствующих пакетов, не desktop-скрипт)
ros2 launch mpu6500_ros mpu6500_simple_imu.launch.py \
  frame_id:=imu_link \
  enable_calibration:=true

ros2 launch orbbec_camera astra_mini.launch.py \
  enable_depth:=true \
  enable_point_cloud:=true

ros2 launch ftservo_ros motor_gui.launch.py \
  config_file:=$(pwd)/src/ftservo_ros/config/config_example.yaml

# Из системного пакета ROS 2 Humble (joy + teleop)
ros2 launch teleop_twist_joy teleop-launch.py joy_config:=ps3
```

> **Про скорость шины моторов:** SCS40 работают на 1 Мбит/с, но штатный UART Repka Pi 4 (Allwinner H6) физически не может выдать 1M — реальная линия получается 750k, и моторы не отвечают. Подробности и варианты (USB-UART или перевод шины на 500k) — в [ros_packages/src/ftservo_ros/README.md](ros_packages/src/ftservo_ros/README.md).
