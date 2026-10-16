# Launch файлы RDS-2P

## Основные launch файлы

### 🤖 Визуализация робота
- **`display.launch.py`** - Визуализация робота для реальных моторов и датчиков
  ```bash
  ros2 launch rds-2p display.launch.py
  ```

### 🔧 Дополнительные файлы
- **`bridge_motors_to_joints.launch.py`** - Только мост мотор-сустав (без визуализации)
  ```bash
  ros2 launch rds-2p bridge_motors_to_joints.launch.py
  ```
- **`fake_imu.launch.py`** - Фейковый IMU паблишер для разработки без железа
  ```bash
  ros2 launch rds-2p fake_imu.launch.py
  ```
- **`description.launch.py`** - Запуск robot_state_publisher (используется другими launch файлами)
- **`controllers.launch.py`** - Контроллеры суставов
- **`gazebo_sim.launch.py`** - Симуляция в Gazebo

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
ros2 launch rds-2p display.launch.py
```

### Для разработки без железа:
```bash
# Фейковый IMU для разработки
ros2 launch rds-2p fake_imu.launch.py

# Визуализация робота
ros2 launch rds-2p display.launch.py
```

### Для симуляции:
```bash
ros2 launch rds-2p gazebo_sim.launch.py
```