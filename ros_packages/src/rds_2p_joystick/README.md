# rds_2p_joystick

ROS2 пакет для управления RDS-2P роботом через PS4 джойстик с поддержкой IMU данных.

## Описание

Этот пакет предоставляет единый интерфейс для работы с PS4 контроллером:
- **Базовое управление** через `teleop_twist_joy` (стики, кнопки → `/cmd_vel`)
- **IMU данные** (акселерометр и гироскоп) → `/joy/imu`
- **Данные тачпада** (координаты касания) → `/joy/touchpad`

## Установка зависимостей

### Системные зависимости

```bash
# Установка python3-evdev для чтения данных с устройств ввода
sudo apt install python3-evdev

# Добавление пользователя в группу input для доступа к устройствам
sudo usermod -a -G input $USER
# После этого нужно перелогиниться или выполнить: newgrp input
```

### Опционально: ds4drv для расширенного доступа к IMU

Для получения данных акселерометра и гироскопа PS4 контроллера рекомендуется использовать `ds4drv`:

```bash
# Установка ds4drv
sudo pip3 install ds4drv

# Или через apt (если доступно)
sudo apt install ds4drv
```

**Примечание:** Стандартный Linux драйвер джойстика (`/dev/input/js0`) не предоставляет доступ к данным IMU PS4 контроллера. Для получения этих данных требуется специальный драйвер или библиотека.

## Сборка

```bash
cd ~/RDS-2P-software/ros_packages
colcon build --packages-select rds_2p_joystick
source install/setup.bash
```

## Использование

### ⚠️ ВАЖНО: Запуск ds4drv

**Перед запуском launch файла необходимо самостоятельно запустить `ds4drv`** для работы IMU и тачпада:

```bash
# Запуск ds4drv с поддержкой hidraw (необходимо для IMU и тачпада)
ds4drv --hidraw

# Или в фоновом режиме (daemon)
ds4drv --hidraw --daemon
```

**Примечание:** Launch файл **не запускает** `ds4drv` автоматически. Пользователь должен запустить его вручную перед запуском launch файла.

### Базовый запуск

```bash
# 1. Сначала запустите ds4drv (см. выше)
# 2. Затем запустите launch файл
ros2 launch rds_2p_joystick ps4_joystick.launch.py
```

### С параметрами

```bash
ros2 launch rds_2p_joystick ps4_joystick.launch.py \
    enable_teleop:=true \
    enable_imu:=true \
    enable_touchpad:=true \
    imu_publish_rate:=100.0
```

### Параметры запуска

- `enable_teleop` (по умолчанию: `true`) - включить управление через teleop_twist_joy
- `enable_imu` (по умолчанию: `true`) - включить чтение IMU данных
- `enable_touchpad` (по умолчанию: `true`) - включить чтение данных тачпада
- `frame_id` (по умолчанию: `ps4_controller`) - frame_id для IMU сообщений
- `parent_frame_id` (по умолчанию: `odom_link`) - родительский frame_id для TF трансформации
- `publish_tf` (по умолчанию: `true`) - публиковать TF трансформацию для ориентации контроллера
- `imu_publish_rate` (по умолчанию: `50.0`) - частота публикации IMU данных (Гц)
- `imu_update_rate` (по умолчанию: `100.0`) - частота обновления ориентации для точности (Гц)
- `touchpad_publish_rate` (по умолчанию: `50.0`) - частота публикации данных тачпада (Гц)
- `debug_touchpad` (по умолчанию: `false`) - включить отладочное логирование для тачпада

**Примечание:** Устройства (`joy_dev`, `event_dev`, `hidraw_dev`) определяются автоматически. Ручное указание устройств не требуется.

## Топики

### Публикуемые топики (создаются нашим пакетом)

- `/joy/imu` (`sensor_msgs/msg/Imu`) - данные акселерометра и гироскопа PS4 контроллера
  - Публикуется узлом `ps4_imu_node.py`
  - Частота: 50 Гц (по умолчанию, настраивается через `imu_publish_rate`)
  - Содержит: линейное ускорение, угловую скорость, ориентацию (кватернион)

- `/joy/touchpad` (`geometry_msgs/msg/PointStamped`) - координаты касания на тачпаде PS4
  - Публикуется узлом `ps4_touchpad_node.py`
  - Частота: 50 Гц (по умолчанию, настраивается через `touchpad_publish_rate`)
  - Содержит: координаты X (0-1920) и Y (0-943) в сырых значениях
  - Публикуется только при активном касании

- `/joy/touchpad/active` (`std_msgs/msg/Bool`) - состояние касания тачпада
  - Публикуется узлом `ps4_touchpad_node.py`
  - `true` - есть активное касание, `false` - касания нет
  - Синхронизировано с `/joy/touchpad`

- `/cmd_vel` (`geometry_msgs/msg/Twist`) - команды движения (от `teleop_twist_joy`)
  - Публикуется узлом `teleop_twist_joy_node`
  - Преобразует команды джойстика в команды движения робота

### Публикуемые топики (создаются стандартным joy_node)

- `/joy` (`sensor_msgs/msg/Joy`) - базовые данные джойстика
  - Публикуется стандартным узлом `joy_node` из пакета `joy`
  - Содержит: оси (стики, триггеры) и кнопки

### Подписываемые топики

- `/joy/set_feedback` (`sensor_msgs/msg/JoyFeedback`) - обратная связь (вибрация, LED)
  - Подписывается стандартным узлом `joy_node` из пакета `joy`
  - **⚠️ ВАЖНО:** Топик существует, но **не работает** через стандартный Linux драйвер `/dev/input/js0`
  - Стандартный драйвер не поддерживает haptic feedback (вибрацию) для PS4 контроллера
  - `joy_node` выводит сообщение: "No haptic (rumble) available, skipping initialization"
  - Для работы вибрации требуется специальный драйвер или прямой доступ к HID устройству

## Автоматическое определение устройств

Пакет автоматически определяет нужные устройства:
- **Джойстик** (`/dev/input/js*`) - определяется стандартным `joy_node`
- **Event устройство для IMU** (`/dev/input/event*`) - автоматически ищется устройство PS4 с поддержкой IMU (оси гироскопа)
- **Hidraw устройство для тачпада** (`/dev/hidraw*`) - автоматически определяется по структуре отчёта PS4

Ручное указание устройств не требуется. Если устройство не найдено, проверьте:
1. Запущен ли `ds4drv --hidraw`
2. Подключен ли PS4 контроллер
3. Есть ли доступ к устройствам (пользователь в группе `input`)

## Ограничения

1. **Стандартный Linux драйвер** не предоставляет доступ к IMU данным PS4 контроллера через `/dev/input/js0` или `/dev/input/event*`.

2. **Для получения IMU данных** требуется:
   - Использование `ds4drv --hidraw` (обязательно запускать вручную перед launch файлом)
   - Или использование библиотеки `hidapi` для прямого доступа к HID устройству
   - Или использование специального ROS2 пакета типа `ps_ros2_common`

3. **Вибрация (haptic feedback) не работает** через стандартный Linux драйвер:
   - Топик `/joy/set_feedback` создается автоматически `joy_node`, но вибрация не функционирует
   - Стандартный драйвер `/dev/input/js0` не поддерживает haptic feedback для PS4
   - Для работы вибрации требуется специальный драйвер или прямой доступ к HID устройству

4. **Данные тачпада** требуют `ds4drv` с флагом `--hidraw`:
   - Стандартный драйвер не предоставляет доступ к данным тачпада через `evdev`
   - `ps4_touchpad_node.py` читает данные напрямую из `/dev/hidraw*` устройства
   - **Важно:** `ds4drv` должен быть запущен пользователем вручную перед запуском launch файла

## Интеграция с ds4drv

**⚠️ ВАЖНО:** Launch файл **не запускает** `ds4drv` автоматически. Пользователь **должен запустить** `ds4drv` вручную перед запуском launch файла.

### Запуск ds4drv

```bash
# Запуск ds4drv с поддержкой hidraw (необходимо для IMU и тачпада)
ds4drv --hidraw

# Или в фоновом режиме (daemon)
ds4drv --hidraw --daemon
```

### Проверка работы ds4drv

После запуска `ds4drv` проверьте, что устройство создано:

```bash
# Проверка процессов ds4drv
pgrep -a ds4drv

# Проверка созданных устройств
ls -la /dev/input/event* | grep -i "wireless\|sony\|dualshock"
ls -la /dev/hidraw*

# Просмотр логов ds4drv
cat ~/.cache/ds4drv.log | tail -20
```

### Полный пример запуска

```bash
# 1. Запустите ds4drv
ds4drv --hidraw --daemon

# 2. Подождите несколько секунд для инициализации устройств
sleep 3

# 3. Запустите launch файл
ros2 launch rds_2p_joystick ps4_joystick.launch.py
```

**Примечание:** Если возникают проблемы с сетью или зависание системы при использовании `ds4drv`, попробуйте:
1. Запустить `ds4drv` вручную перед launch файлом (не в daemon режиме)
2. Проверить логи: `journalctl -f` или `dmesg | tail -50`
3. Использовать стандартный драйвер Linux (без IMU данных, но без `ds4drv`)

## Пример использования в других launch файлах

```python
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.substitutions import FindPackageShare
from launch.substitutions import PathJoinSubstitution

def generate_launch_description():
    ps4_joystick_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('rds_2p_joystick'),
                'launch',
                'ps4_joystick.launch.py'
            ])
        ]),
        launch_arguments={
            'enable_teleop': 'true',
            'enable_imu': 'true',
        }.items()
    )
    
    return LaunchDescription([
        ps4_joystick_launch,
    ])
```

## Лицензия

MIT License

## Автор

Zhuravliov Pavel (zhuravliov.pav@yandex.ru)

