# rds_2p_dance - ROS2 Action сервер для проигрывания танцев

Пакет для проигрывания анимаций танцев робота RDS-2P через ROS2 Action интерфейс.

## Запуск Action сервера

### Способ 1: Используя launch файл (рекомендуется)

```bash
# Активируйте окружение ROS2
source /opt/ros/humble/setup.bash
source ~/mujoco_playground/RDS-2P-simulator/ros_packages/install/setup.bash

# Запустите Action сервер с параметрами по умолчанию
ros2 launch rds_2p_dance dance_action_server.launch.py

# Запустите с интерполяцией
ros2 launch rds_2p_dance dance_action_server.launch.py interpolate:=true

# Запустите с увеличенной скоростью и интерполяцией
ros2 launch rds_2p_dance dance_action_server.launch.py interpolate:=true speed_multiplier:=2.0

# Запустите с увеличенной частотой публикации
ros2 launch rds_2p_dance dance_action_server.launch.py base_rate:=100.0

# Запустите с отладочным уровнем логирования
ros2 launch rds_2p_dance dance_action_server.launch.py log_level:=debug
```

### Способ 2: Используя ros2 run

```bash
# Активируйте окружение ROS2
source /opt/ros/humble/setup.bash
source ~/mujoco_playground/RDS-2P-simulator/ros_packages/install/setup.bash

# Запустите Action сервер
ros2 run rds_2p_dance dance_action_server

# Запустите с параметрами
ros2 run rds_2p_dance dance_action_server --ros-args -p interpolate:=true -p speed_multiplier:=2.0
```

## Отправка goal через консоль

### Способ 1: Используя ros2 action send_goal

```bash
# Отправить goal с номером танца (например, танец #1)
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 1}"

# Отправить goal с номером танца #2
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 2}"

# Отправить goal с feedback (показывает прогресс)
ros2 action send_goal --feedback /dance/play rds_2p_dance/action/PlayDance "{dance_number: 3}"

# Отправить goal с интерполяцией и скоростью (как в play_animation.py)
ros2 action send_goal --feedback /dance/play rds_2p_dance/action/PlayDance "{dance_number: 5, interpolate: true, speed_multiplier: 1.0}"

# Отправить goal с увеличенной скоростью (в 2 раза быстрее)
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 1, speed_multiplier: 2.0}"

# Отправить goal с интерполяцией и обычной скоростью
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 3, interpolate: true, speed_multiplier: 1.0}"
```

### Способ 2: Используя Python скрипт

Создайте файл `send_dance_goal.py`:

```python
#!/usr/bin/env python3
import rclpy
from rclpy.action import ActionClient
from rds_2p_dance.action import PlayDance

def main():
    rclpy.init()
    node = rclpy.create_node('dance_client')
    action_client = ActionClient(node, PlayDance, '/dance/play')
    
    # Ждем сервер
    if not action_client.wait_for_server(timeout_sec=5.0):
        print('Action server не найден!')
        return
    
    # Создаем goal
    goal_msg = PlayDance.Goal()
    goal_msg.dance_number = 1  # Номер танца
    
    # Отправляем goal
    send_goal_future = action_client.send_goal_async(goal_msg)
    rclpy.spin_until_future_complete(node, send_goal_future)
    goal_handle = send_goal_future.result()
    
    if not goal_handle.accepted:
        print('Goal отклонен!')
        return
    
    print('Goal принят, ожидаем результат...')
    
    # Ждем результат
    result_future = goal_handle.get_result_async()
    rclpy.spin_until_future_complete(node, result_future)
    result = result_future.result().result
    
    print(f'Результат: success={result.success}, message={result.message}')
    
    rclpy.shutdown()

if __name__ == '__main__':
    main()
```

## Просмотр информации об Action

```bash
# Список всех Action серверов
ros2 action list

# Информация об Action
ros2 action info /dance/play

# Тип Action
ros2 action list -t
```

## Параметры узла

Action сервер поддерживает следующие ROS2 параметры:

### Параметры узла (используются, если не заданы в goal)

- `interpolate` (bool, по умолчанию: `false`) - включить линейную интерполяцию между позами
- `base_rate` (float, по умолчанию: `50.0`) - базовая частота публикации команд суставов в Hz
- `speed_multiplier` (float, по умолчанию: `1.0`) - множитель скорости воспроизведения

### Примеры использования параметров

**Через launch файл (рекомендуется):**
```bash
# Запуск с интерполяцией
ros2 launch rds_2p_dance dance_action_server.launch.py interpolate:=true

# Изменение базовой частоты публикации (по умолчанию 50 Hz)
ros2 launch rds_2p_dance dance_action_server.launch.py base_rate:=100.0

# Изменение множителя скорости (по умолчанию 1.0)
ros2 launch rds_2p_dance dance_action_server.launch.py speed_multiplier:=1.5

# Комбинация параметров
ros2 launch rds_2p_dance dance_action_server.launch.py interpolate:=true speed_multiplier:=2.0 base_rate:=100.0
```

**Через ros2 run:**
```bash
# Запуск с интерполяцией
ros2 run rds_2p_dance dance_action_server --ros-args -p interpolate:=true

# Изменение базовой частоты публикации (по умолчанию 50 Hz)
ros2 run rds_2p_dance dance_action_server --ros-args -p base_rate:=100.0

# Изменение множителя скорости (по умолчанию 1.0)
ros2 run rds_2p_dance dance_action_server --ros-args -p speed_multiplier:=1.5
```

**Примечание:** Параметры узла используются как значения по умолчанию, если соответствующие параметры не заданы в goal action. Параметры в goal имеют приоритет.

## Доступные анимации

Пакет содержит следующие анимации:
- `animation1.csv` - танец #1
- `animation2.csv` - танец #2
- `animation3.csv` - танец #3
- `animation4.csv` - танец #4
- `animation5.csv` - танец #5

## Примеры использования

### Проиграть танец #1
```bash
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 1}"
```

### Проиграть танец #4 с просмотром прогресса
```bash
ros2 action send_goal --feedback /dance/play rds_2p_dance/action/PlayDance "{dance_number: 4}"
```

### Проиграть танец с интерполяцией и заданной скоростью (как в play_animation.py)
```bash
# Эквивалент: python3 play_animation.py --interpolate -s 1.0 -f animation5.csv
ros2 action send_goal --feedback /dance/play rds_2p_dance/action/PlayDance "{dance_number: 5, interpolate: true, speed_multiplier: 1.0}"
```

### Проиграть танец в 2 раза быстрее
```bash
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 1, speed_multiplier: 2.0}"
```

### Проиграть танец медленнее (в 0.5 раза)
```bash
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 2, speed_multiplier: 0.5}"
```

### Проиграть танец с интерполяцией и заданной скоростью (как в play_animation.py)
```bash
# Эквивалент: python3 play_animation.py --interpolate -s 1.0 -f animation5.csv
ros2 action send_goal --feedback /dance/play rds_2p_dance/action/PlayDance "{dance_number: 5, interpolate: true, speed_multiplier: 1.0}"
```

### Проиграть танец в 2 раза быстрее
```bash
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 1, speed_multiplier: 2.0}"
```

### Проиграть танец медленнее (в 0.5 раза)
```bash
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 2, speed_multiplier: 0.5}"
```

### Отменить текущее воспроизведение
```bash
# В другом терминале, пока Action выполняется
ros2 action send_goal --cancel /dance/play rds_2p_dance/action/PlayDance "{dance_number: 1}"
```

## Параметры Goal

При отправке goal можно задать следующие параметры:

- `dance_number` (int32, обязательный) - номер танца (1-5)
- `interpolate` (bool, опциональный) - включить линейную интерполяцию между позами. Если `false` или не задан, используется параметр узла `interpolate`
- `speed_multiplier` (float32, опциональный) - множитель скорости воспроизведения. Если `<= 0.0` или не задан, используется параметр узла `speed_multiplier`. Например:
  - `1.0` - нормальная скорость
  - `2.0` - в 2 раза быстрее
  - `0.5` - в 2 раза медленнее

## Тестирование

### Быстрый тест (минимальная проверка)

1. **Запустите Action сервер** (в первом терминале):
```bash
source /opt/ros/humble/setup.bash
source ~/mujoco_playground/RDS-2P-simulator/ros_packages/install/setup.bash
ros2 run rds_2p_dance dance_action_server
```

2. **Проверьте, что сервер запущен** (во втором терминале):
```bash
source /opt/ros/humble/setup.bash
source ~/mujoco_playground/RDS-2P-simulator/ros_packages/install/setup.bash

# Проверка наличия action сервера
ros2 action list
# Должен показать: /dance/play

# Проверка типа action
ros2 action info /dance/play
# Должен показать тип: rds_2p_dance/action/PlayDance
```

3. **Отправьте тестовый goal**:
```bash
# Проиграть танец #1 с просмотром feedback
ros2 action send_goal --feedback /dance/play rds_2p_dance/action/PlayDance "{dance_number: 1}"
```

**Ожидаемый результат:**
- Goal принят сервером
- Выводится feedback с прогрессом (current_pose, total_poses, progress)
- В конце выводится результат с success=true и сообщением об успешном завершении

### Полное тестирование

#### Тест 1: Проверка всех доступных анимаций

```bash
# В терминале с запущенным сервером проверьте логи
# В другом терминале запустите последовательно:

for i in {1..5}; do
  echo "=== Тестирование танца #$i ==="
  ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: $i}"
  sleep 2
done
```

#### Тест 2: Проверка feedback (прогресса)

```bash
# Запустите с просмотром feedback
ros2 action send_goal --feedback /dance/play rds_2p_dance/action/PlayDance "{dance_number: 3}"

# Ожидаемый вывод:
# Feedback:
#   current_pose: 1
#   total_poses: 28
#   progress: 0.035714...
# ...
```

#### Тест 3: Проверка отмены (cancel)

```bash
# Запустите длинный танец
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 5}" &

# Сразу отмените его (в другом терминале или через Ctrl+C и новую команду)
ros2 action send_goal --cancel /dance/play rds_2p_dance/action/PlayDance "{dance_number: 5}"
```

**Ожидаемый результат:** Goal отменен, сервер выводит сообщение "Воспроизведение отменено"

#### Тест 4: Проверка обработки ошибок

```bash
# Попытка проиграть несуществующий танец
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 99}"

# Ожидаемый результат: Goal отклонен или завершен с success=false и сообщением об ошибке
```

#### Тест 5: Мониторинг публикуемых команд

```bash
# В отдельном терминале мониторьте топик /joint_commands
ros2 topic echo /joint_commands

# В другом терминале запустите танец
ros2 action send_goal /dance/play rds_2p_dance/action/PlayDance "{dance_number: 1}"

# Ожидаемый результат: Видны сообщения JointState с позициями суставов
```

#### Тест 6: Проверка параметров узла

```bash
# Запуск с интерполяцией
ros2 run rds_2p_dance dance_action_server --ros-args -p interpolate:=true

# Запуск с увеличенной скоростью (в 2 раза быстрее)
ros2 run rds_2p_dance dance_action_server --ros-args -p speed_multiplier:=2.0

# Запуск с увеличенной частотой публикации
ros2 run rds_2p_dance dance_action_server --ros-args -p base_rate:=100.0
```

### Проверка логов сервера

При запуске сервера проверьте логи на наличие:
- Сообщения о успешном запуске: "Dance Action Server запущен"
- Путь к папке анимаций
- Сообщения о загрузке анимаций: "Загружено X поз из ..."
- Сообщения о завершении: "Воспроизведение завершено"

### Устранение проблем

**Проблема:** Action сервер не найден
```bash
# Решение: Проверьте, что сервер запущен
ros2 node list
ros2 action list
```

**Проблема:** Ошибка "Не удалось загрузить файл"
```bash
# Решение: Проверьте наличие файлов анимаций
ros2 pkg prefix rds_2p_dance
ls $(ros2 pkg prefix rds_2p_dance)/share/rds_2p_dance/animations/
```

**Проблема:** Импорт не работает
```bash
# Решение: Пересоберите пакет
cd ~/mujoco_playground/RDS-2P-simulator/ros_packages
colcon build --packages-select rds_2p_dance
source install/setup.bash
```

