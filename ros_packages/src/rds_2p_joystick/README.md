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

### Подготовка контроллера: два режима по типу ядра

- **Ядро с рабочим HIDP** (OrangePi 5 Pro и большинство SBC): штатный bluez +
  kernel-HID. Достаточно сопряжения `ps4_bt_reconnect.sh <MAC>` — `/dev/input/js0`
  поднимает ядро. IMU/тачпад: опционально `ds4drv --hidraw` (читает kernel hidraw).
- **Ядро без HIDP** (RepkaPi/Allwinner H6: `socket(AF_BLUETOOTH,HIDP)` →
  `ESOCKTNOSUPPORT`): HID ведёт userspace-`ds4drv`. Одноразово —
  `sudo ros_packages/scripts/ps4_ds4drv_setup.sh`; далее `ds4drv` работает
  systemd-сервисом (`systemctl status ds4drv`), вручную его запускать не нужно.
  Тачпад читается нодой из DSU UDP-потока (`--udp`, порт 26760) автоматически.

**Примечание:** Стандартный Linux драйвер джойстика (`/dev/input/js0`) не предоставляет
доступ к данным IMU PS4 контроллера — для IMU нужен `ds4drv` (в любом из режимов выше).

## Сборка

```bash
cd ~/RDS-2P-software/ros_packages
colcon build --packages-select rds_2p_joystick
source install/setup.bash
```

## Использование

### ⚠️ ВАЖНО: Подготовка джойстика на хосте

Launch файл сам `ds4drv`/сопряжение не поднимает — джойстик должен быть готов **до** запуска:

- **RepkaPi (ядро без HIDP)**: `ds4drv` — systemd-сервис, уже работает
  (`systemctl status ds4drv`); при «слёте»: включи геймпад (PS/PS+Share) и запусти
  `ps4_bt_reconnect.sh` — он подключит без перепары («быстрый путь») и при
  необходимости перезапустит ds4drv. Power-cycle геймпада (PS 10 с) — крайняя мера.
- **OrangePi 5 Pro (kernel-HIDP)**: сопряжение `ps4_bt_reconnect.sh <MAC>`,
  при желании IMU — `ds4drv --hidraw` вручную.

Подробности — в секции «Подключение джойстика по Bluetooth (wireless)» ниже.

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

### Просмотр данных (внутри контейнера)

```bash
docker exec -it <имя_контейнера> bash    # на тестовом стенде: joy_test
source /opt/ros/humble/setup.bash

ros2 topic echo /joy --once        # стики/кнопки (поток ~200 Гц — читать лучше через --once)
ros2 topic echo /joy/imu --once    # IMU: линейное ускорение + угловая скорость
ros2 topic echo /joy/touchpad      # тачпад: печатает, пока ведёшь пальцем
ros2 topic echo /joy/touchpad/active
ros2 topic hz /joy                 # быстрая проверка живости частот
ros2 topic hz /joy/imu
```

Одной строкой без захода: `docker exec joy_test bash -c "source /opt/ros/humble/setup.bash && ros2 topic echo /joy --once"`.

Диагностика: если `/joy` молчит, а js0 живой — `docker restart joy_test` (ноды переоткроют устройство). Если молчит и js0 — power-cycle геймпада (см. выше).

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
- **Тачпад** - из `/dev/hidraw*` (kernel-HID/uhid) **или**, если hidraw недоступен
  (ядро без HIDP), из DSU UDP-потока `ds4drv --udp` (`udp_host`/`udp_port`,
  по умолчанию `127.0.0.1:26760`; отключается параметром `use_udp`)

Ручное указание устройств не требуется. Если тачпад не работает, проверьте:
1. RepkaPi: `systemctl status ds4drv` (сервис `active`, в ExecStart есть `--udp`)
2. OrangePi: запущен ли `ds4drv --hidraw` (hidraw от kernel-HID)
3. Подключен ли PS4 контроллер (js0 живой)
4. Есть ли доступ к устройствам (пользователь в группе `input`)

## Ограничения

1. **Стандартный Linux драйвер** не предоставляет доступ к IMU данным PS4 контроллера через `/dev/input/js0` или `/dev/input/event*`.

2. **Для получения IMU данных** требуется `ds4drv`:
   - RepkaPi: systemd-сервис `ds4drv --udp` (ставится `ps4_ds4drv_setup.sh`, работает автоматически)
   - OrangePi: `ds4drv --hidraw` (kernel hidraw) вручную перед launch файлом
   - Или использование специального ROS2 пакета типа `ps_ros2_common`

3. **Вибрация (haptic feedback) не работает** через стандартный Linux драйвер:
   - Топик `/joy/set_feedback` создается автоматически `joy_node`, но вибрация не функционирует
   - Стандартный драйвер `/dev/input/js0` не поддерживает haptic feedback для PS4
   - Для работы вибрации требуется специальный драйвер или прямой доступ к HID устройству

4. **Данные тачпада** требуют `ds4drv` (в любом режиме):
   - Стандартный драйвер не предоставляет доступ к данным тачпада через `evdev`
   - OrangePi: `ps4_touchpad_node.py` читает `/dev/hidraw*` (`ds4drv --hidraw`, вручную)
   - RepkaPi: нода автоматически читает тачпад из DSU UDP-потока `ds4drv --udp`
     (hidraw на ядре без HIDP недоступен) — параметры `use_udp`/`udp_host`/`udp_port`

## Интеграция с ds4drv

**⚠️ ВАЖНО:** Launch файл **не запускает** `ds4drv` автоматически.

- **RepkaPi**: `ds4drv` уже работает systemd-сервисом (ставится `ps4_ds4drv_setup.sh`,
  `ExecStart=/usr/local/bin/ds4drv --udp`) — вручную ничего запускать не нужно.
- **OrangePi (kernel hidraw)**: запустите `ds4drv --hidraw` перед launch файлом (см. ниже).

### Запуск ds4drv (OrangePi / kernel hidraw)

```bash
# Читает kernel-hidraw устройство (IMU + тачпад доступны ноде)
ds4drv --hidraw

# Или в фоновом режиме (daemon)
ds4drv --hidraw --daemon
```

### Проверка работы ds4drv

```bash
# RepkaPi (systemd-сервис):
systemctl status ds4drv
journalctl -u ds4drv -n 30 --no-pager

# Общие признаки живости (любая платформа):
pgrep -a ds4drv
ls -la /dev/input/event* | grep -i "wireless\|sony\|dualshock"
ls -la /dev/hidraw*                 # OrangePi / uhid-путь
ss -ulpn | grep 26760               # RepkaPi: DSU-сервер тача слушает
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

## Подключение джойстика по Bluetooth (wireless)

Для беспроводного DS4 на роботе есть отдельные **хост-скрипты** (вне контейнера), которые готовят `/dev/input/js0` до запуска launch-файла:

- `ros_packages/scripts/ps4_bt_reconnect.sh [MAC]` — сопряжение/переподключение. Сам определяет режим:
  - **classic** — ядро с рабочим HIDP (OrangePi 5 Pro и большинство SBC): штатный bluez, HID цепляет ядро;
  - **ds4drv** — ядро без HIDP-сокетов (RepkaPi/Allwinner H6, где `socket(AF_BLUETOOTH,HIDP)` → `ESOCKTNOSUPPORT`): HID ведёт userspace-демон `ds4drv` (L2CAP + uinput → js0).
  - Запуск: на хосте от root; на надписи «Сканируем» зажать **PS+Share** до быстрых двойных вспышек. Успех = живой поток на `/dev/input/js0`.
- `ros_packages/scripts/ps4_ds4drv_setup.sh` — **одноразовая** установка ds4drv-стека на ядрах без HIDP (PyBluez + ds4drv-cemuhook + патчи `fn→fd`/fast-path/`connect`-retry/чтение обоих L2CAP-сокетов + авто-перевод геймпада в поток 0x11 + bluez drop-in `-P input` (выключение input-плагина!) + `AutoEnable=true` + systemd-юнит с `--udp`). Идемпотентен.
- `docker/host/ds4drv.service` — systemd-юнит ds4drv; список MAC лежит в `/etc/default/ds4drv` (`DS4_MACS=...`), `ps4_bt_reconnect.sh` дописывает туда MAC автоматически.

Скрипты пригодны для запуска из программы: не читают stdin, root без интерактива (`sudo -n`), вывод дублируется в `/var/log/ps4_bt_reconnect.log`, все внешние вызовы под `timeout`, `flock` против параллельных запусков. Коды возврата: `0` успех (живой js0) / `1` не поднялось / `2` окружение (не root, нет bluez/адаптера) / `3` уже запущен другой экземпляр.

**Важно про надёжность:** DS4 (VID `054C` PID `09CC`) после disconnect/ребута **сам стабильно не переподключается** — это известный баг bluez ([bluez#488](https://github.com/bluez/bluez/issues/488): «Connection refused - security block» → «Authentication Failure (0x05)»). Поэтому рабочий ритуал — запуск `ps4_bt_reconnect.sh` + PS+Share (полная перепара со снятием старого сопряжения), а не ожидание авто-реконнекта. Config-воркараунды (`FastConnectable`, `JustWorksRepairing`) на этом геймпаде нестабильны — не полагаемся на них.

На ядрах без HIDP (режим `ds4drv`) беспроводной **тачпад работает через DSU-поток**:
`ds4drv` запускается с `--udp` (127.0.0.1:26760), а `ps4_touchpad_node.py` читает
тач оттуда fallback-режимом (`use_udp=true`) — `/dev/hidraw` для этого не нужен.

Про docker-развёртывание робота — см. `docker/README.md`, секция «Wireless PS4 джойстик (Bluetooth)».

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

