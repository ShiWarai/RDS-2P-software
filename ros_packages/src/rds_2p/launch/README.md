# Launch файлы RDS-2P

## Основные launch файлы

### 🤖 Визуализация робота
- **`sim/display.launch.py`** - Визуализация робота для реальных моторов и датчиков
  ```bash
  ros2 launch rds-2p sim/display.launch.py
  ```

### 🔧 Дополнительные файлы
- **`bridge_motors_to_joints.launch.py`** - Только мост мотор-сустав (без визуализации)
  ```bash
  ros2 launch rds-2p bridge_motors_to_joints.launch.py
  ```
- **`sim/fake_imu.launch.py`** - Фейковый IMU паблишер для разработки без железа
  ```bash
  ros2 launch rds-2p sim/fake_imu.launch.py
  ```
- **`sim/description.launch.py`** - Запуск robot_state_publisher (используется другими launch файлами)
- **`sim/controllers.launch.py`** - Контроллеры суставов
- **`sim/gazebo_sim.launch.py`** - Симуляция в Gazebo

### 🗣️ Голос + LLM
- **`voice_system.launch.py`** - голосовой контур: audio + STT (Vosk/GigaAM) + Paroli + lip_sync.
  Выбор распознавателя: `stt:=vosk` (по умолчанию, CPU) или `stt:=gigaam` (RKNN NPU).
  LLM (`rkllm_ros`/`system_one`/`mirea_rag`) сюда не входит — только распознавание, синтез и «рот».
  ```bash
  ros2 launch rds_2p voice_system.launch.py                 # Vosk
  ros2 launch rds_2p voice_system.launch.py stt:=gigaam     # GigaAM
  ```
- **`mirea_rag`** - диалог/LLM: транскрипции → OSM/поиск → `rkllm_ros` + Paroli.
  Команды идут отдельно через `rds_2p_commands` (`commands_mode:=osm|regex`).
  OSM работает нативно в `system_one_ros` (`/system_one/ask`), контейнер не нужен.

## Схема использования

### Для работы с реальными моторами:
```bash
# Терминал 1: Контроллер моторов
ros2 run ftservo_ros motor_controller_node --ros-args \
  -p interface:=/dev/ttyS7 \
  -p config_file:=src/ftservo_ros/config/config_example.yaml \
  -p is_sim:=false

# Терминал 2: Мост + визуализация
ros2 launch rds-2p bridge_motors_to_joints.launch.py
ros2 launch rds-2p sim/display.launch.py
```

### Для разработки без железа:
```bash
# Фейковый IMU для разработки
ros2 launch rds-2p sim/fake_imu.launch.py

# Визуализация робота
ros2 launch rds-2p sim/display.launch.py
```

### Для симуляции:
```bash
ros2 launch rds-2p sim/gazebo_sim.launch.py
```