# ROS2 Performance Test Bench

Тестовый стенд для измерения производительности передачи данных через ROS2.

## Описание

Пакет содержит два узла для тестирования задержки передачи данных:
- **ping_node**: отправляет команды моторов (`MotorCommands`) на топик `/ping`
- **pong_node**: получает команды, обрабатывает их и отправляет состояния моторов (`MotorStates`) на топик `/pong`

ping_node измеряет полную задержку от отправки команды до получения ответа и выводит статистику.

## Сборка

```bash
cd /path/to/ros_packages
colcon build --packages-select ros2_perf_test --symlink-install
source install/setup.bash
```

## Использование

### Базовый запуск

1. Запустите pong_node в первом терминале:
```bash
ros2 run ros2_perf_test pong_node
```

2. Запустите ping_node во втором терминале:
```bash
ros2 run ros2_perf_test ping_node
```

ping_node автоматически завершится после выполнения всех измерений и выведет статистику.

## Параметры узлов

### ping_node

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `publish_rate` | double | 50.0 | Частота отправки сообщений (Гц) |
| `max_measurements` | int | 100 | Максимальное количество измерений |

**Пример:**
```bash
ros2 run ros2_perf_test ping_node --ros-args \
  -p publish_rate:=100.0 \
  -p max_measurements:=50
```

### pong_node

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `processing_delay_us` | int | 100 | Задержка обработки одной команды (микросекунды) |
| `publish_rate` | double | 50.0 | Частота публикации состояний (Гц) - используется только в режиме таймера |
| `use_timer_publish` | bool | true | Режим публикации: `true` - по таймеру, `false` - сразу в callback |

**Примеры:**

Режим таймера (публикация по расписанию):
```bash
ros2 run ros2_perf_test pong_node --ros-args \
  -p processing_delay_us:=200 \
  -p publish_rate:=50.0 \
  -p use_timer_publish:=true
```

Режим callback (публикация сразу после обработки):
```bash
ros2 run ros2_perf_test pong_node --ros-args \
  -p processing_delay_us:=200 \
  -p use_timer_publish:=false
```

## Архитектура

### ping_node
- Публикует `MotorCommands` с 12 моторами на топик `/ping`
- Подписывается на топик `/ping` для получения ответов
- Использует счетчик sequence в `header.frame_id` для идентификации сообщений
- Измеряет задержку с помощью `std::chrono::steady_clock`
- Выводит статистику: минимум, максимум, среднее, медиана, стандартное отклонение

### pong_node
- Подписывается на топик `/ping` для получения команд
- Обрабатывает команды через функцию `processCommand()` (с конфигурируемой задержкой)
- Публикует `MotorStates` на топик `/pong`
- Поддерживает два режима публикации:
  - **Timer mode** (`use_timer_publish=true`): публикация по расписанию (как в реальных системах)
  - **Callback mode** (`use_timer_publish=false`): публикация сразу после обработки

## Формат статистики

После завершения измерений ping_node выводит:

```
==========================================
Latency Statistics:
  Total measurements: 100
  Min latency:       1.313 ms
  Max latency:       2.329 ms
  Average latency:   1.770 ms
  Median latency:    1.782 ms
  Std deviation:     0.117 ms
==========================================
```

## Топики

- `/ping` (MotorCommands): команды от ping_node к pong_node
- `/pong` (MotorStates): состояния от pong_node к ping_node

## QoS

Оба узла используют `SensorDataQoS` для низкой задержки передачи данных.

## Зависимости

- `rclcpp`: ROS2 C++ клиентская библиотека
- `std_msgs`: стандартные сообщения ROS2
- `ftservo_ros`: сообщения для управления моторами (MotorCommands, MotorStates)

