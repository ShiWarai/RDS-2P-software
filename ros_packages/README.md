# RDS-2P — ROS 2 workspace

Рабочее пространство Colcon для квадропеда RDS-2P (ROS 2 Humble). Основной пакет модели и launch-файлов — `rds_2p`; рядом лежат пакеты для моторов, IMU, инференса, телеграм-бота и др.

## Состав `src/`

| Пакет | Назначение |
|--------|------------|
| `rds_2p` | URDF/xacro, RViz, Gazebo, мосты мотор↔суставы, вспомогательные узлы |
| `ftservo_ros` | Контроллер сервоприводов |
| `mpu6500_ros`, `mtf02p_ros` | IMU и дальномер |
| `rds_2p_inference`, `rds_2p_commands`, `rds_2p_dance`, `rds_2p_audio`, `rds_2p_face`, `rds_2p_joystick`, `rds_2p_telegram_bot` | Прикладная логика и интерфейсы |
| `audio_filters` | Фильтрация аудио (RNNoise, SoXR) |
| `paroli_ros2` | TTS Paroli для RK3588 (ONNX + RKNN) |
| `rkllm_ros2` | LLM инференс (RKNN vision encoder + RKLLM) |
| `ros2_perf_test` | Тесты производительности |

Подробности по отдельным пакетам — в их `README.md` внутри `src/<пакет>/`.

## Предварительные требования

- ОС: ориентир **Ubuntu 22.04** (ROS 2 Humble); скрипты в `scripts/` подставляют Python-пакеты в `.../python3.10/dist-packages` под этот стек.
- ROS 2 Humble: `source /opt/ros/humble/setup.bash` задаёт в том числе `ROS_DISTRO` (нужен для `rosdep` в скриптах).
- Один раз на машине: **`sudo rosdep init`** и **`rosdep update`**, если `rosdep` ещё не настраивали.
- Для типичной установки — скрипты в `scripts/`; при необходимости — `rosdep` и `colcon` вручную (см. ниже).

## Быстрая сборка (`scripts/`)

Рекомендуемый способ: скрипты подтягивают внешние репозитории (FTServoLibrary, OrbbecSDK_ROS2, ONNX, при необходимости audio/vosk и др.), ставят системные и Python-зависимости и запускают `colcon build`.

| Скрипт | Как запускать | Назначение |
|--------|----------------|------------|
| `scripts/build_for_desktop.sh` | Из **любого** каталога: `bash /path/to/ros_packages/scripts/build_for_desktop.sh` (или из `ros_packages`: `./scripts/build_for_desktop.sh`) | ПК: x86_64 ONNX; репозиторий **OrbbecSDK_ROS2** клонируется в `src/`, но пакет **`orbbec_camera` в сборку не входит** (`--packages-skip` вместе с `mpu6500_ros`, `mtf02p_ros`, `rds_2p_joystick`, `rds_2p_face` и др.) |
| `scripts/build_for_robot.sh` | Только из **`ros_packages`**: `cd ros_packages && ./scripts/build_for_robot.sh` | Робот: ARM64 ONNX, библиотека MPU6500, полный `colcon build`, ds4drv/udev для геймпада |

Перед запуском выполните `source /opt/ros/humble/setup.bash`, если окружение ROS ещё не подключено. Опция **`--ros-deps-ignore`** отключает шаг `rosdep install` в обоих скриптах.

## Настройка DDS (по желанию)

```bash
export ROS_DOMAIN_ID=1
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
```

Для постоянной настройки можно добавить те же строки в `~/.bashrc` и выполнить `source ~/.bashrc`.

- `ROS_DOMAIN_ID` — изоляция сетевого трафика между группами узлов
- `RMW_IMPLEMENTATION=rmw_fastrtps_cpp` — типичный выбор для Humble

## Сборка вручную (без скриптов)

Если не используете `build_for_desktop.sh` / `build_for_robot.sh`, из каталога `ros_packages`:

```bash
cd /path/to/RDS-2P-software/ros_packages
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --packages-select rds_2p
# или полная сборка:
# colcon build
source install/setup.bash
```

Внешние зависимости (FTServoLibrary, ONNX, клоны Orbbec/audio/vosk и т.д.) в этом случае нужно подготовить самостоятельно — см. логику в скриптах в `scripts/`.

## Имя пакета в командах

В `package.xml` пакет называется **`rds_2p`** (подчёркивание). Команды запуска:

```bash
ros2 launch rds_2p display.launch.py
ros2 launch rds_2p bridge_motors_to_joints.launch.py
```

## Конфиг смещений суставов

По умолчанию `bridge_motors_to_joints.launch.py` подставляет путь к **`config/joint_offsets.yaml`** в share пакета. В git обычно есть только **`joint_offsets_example.yaml`**, поэтому **до `colcon build`** скопируйте пример в `src/rds_2p/config/joint_offsets.yaml`, чтобы файл попал в установку. Иначе узел моста не сможет загрузить конфигурацию. Альтернатива без копирования в исходники — всегда передавать абсолютный путь:

```bash
ros2 launch rds_2p bridge_motors_to_joints.launch.py \
  offsets_config_file:=/абсолютный/путь/к/joint_offsets_example.yaml
```

## Работа с реальными моторами (пример)

Терминал 1 — контроллер моторов (путь к `config_file` подставьте свой; удобно указывать абсолютный путь к YAML в исходниках или в install):

```bash
ros2 launch ftservo_ros motor_controller.launch.py \
  interface:=/dev/ttyS7 \
  config_file:=/path/to/ftservo_ros/config/config_example.yaml \
  is_sim:=false \
  log_level:=ERROR
```

Терминал 2 — мост мотор → `joint_states`:

```bash
ros2 launch rds_2p bridge_motors_to_joints.launch.py
```

Терминал 3 — визуализация:

```bash
ros2 launch rds_2p display.launch.py
```

Дополнительно при необходимости: IMU (`mpu6500_ros`), камера Orbbec и т.д. — см. корневой `README.md` репозитория и README соответствующих пакетов.

## Визуализация и симуляция

```bash
ros2 launch rds_2p display.launch.py
ros2 launch rds_2p fake_imu.launch.py
ros2 launch rds_2p gazebo_sim.launch.py
ros2 launch rds_2p gazebo_sim.launch.py use_rviz:=true
```

## Публикация суставов из командной строки

```bash
ros2 topic pub /joint_states sensor_msgs/msg/JointState \
  "{header: {stamp: {sec: 0, nanosec: 0}, frame_id: 'base_link'}, name: ['leg_block_bl_joint', 'hip_bl_joint', 'shin_bl_joint', 'leg_block_br_joint', 'hip_br_joint', 'shin_br_joint', 'leg_block_fl_joint', 'hip_fl_joint', 'shin_fl_joint', 'leg_block_fr_joint', 'hip_fr_joint', 'shin_fr_joint'], position: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], velocity: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], effort: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}" \
  --once
```

Интерактивная консоль ключевых поз (после сборки `rds_2p`, при необходимости укажите `keyframes_file`):

```bash
ros2 run rds_2p keyframe_console.py
```

## Суставы (12 шт., по 3 на ногу)

**Задние:** `leg_block_bl_joint`, `hip_bl_joint`, `shin_bl_joint`, `leg_block_br_joint`, `hip_br_joint`, `shin_br_joint`

**Передние:** `leg_block_fl_joint`, `hip_fl_joint`, `shin_fl_joint`, `leg_block_fr_joint`, `hip_fr_joint`, `shin_fr_joint`

## Структура пакета `rds_2p`

```
rds_2p/
├── launch/           # display, gazebo_sim, bridge_motors_to_joints, bridge_joints_to_motors,
│                     # fake_imu, controllers, description, battery_monitor, imu_transform, …
├── urdf/             # rds-2p.urdf, rds-2p_ros.urdf, *.xacro
├── rviz/
├── worlds/
├── meshes/dae/
├── config/           # controllers.yaml, motor_pid.yaml, joint_offsets_example.yaml
├── src/              # C++ и Python узлы
├── package.xml
└── CMakeLists.txt
```

Краткий обзор launch-файлов: `src/rds_2p/launch/README.md`.

## Основные топики

- `/joint_states` — `sensor_msgs/msg/JointState`
- `/robot_description` — `std_msgs/msg/String`
- `/tf` — трансформы

Моторы (`ftservo_ros`): `/motors/states`, `/motors/joint_mapping`, `/motors/cmd` (типы сообщений см. в пакете).

## Диагностика

```bash
ros2 topic info /joint_states
ros2 topic echo /joint_states
ros2 node list
ros2 node info /motor_to_joint_bridge
ros2 param list /motor_to_joint_bridge
```

Остановка узлов — через `Ctrl+C` в соответствующих терминалах или завершение процессов вручную; универсальной команды `ros2 node kill /all` в ROS 2 нет.

## Типичные проблемы

**Нет `xacro`:** `sudo apt install ros-humble-xacro`

**Package not found:** `colcon build --packages-select rds_2p` и снова `source install/setup.bash`

**QoS / сеть:** проверьте `ROS_DOMAIN_ID` и `RMW_IMPLEMENTATION`

## Лицензия и автор

MIT License. Maintainer пакета `rds_2p`: Zhuravliov Pavel (zhuravliov.pav@yandex.ru).

## Ссылки

- [ROS 2 Humble](https://docs.ros.org/en/humble/)
- [Gazebo](https://gazebosim.org/docs)
- [RViz2](https://github.com/ros2/rviz)
