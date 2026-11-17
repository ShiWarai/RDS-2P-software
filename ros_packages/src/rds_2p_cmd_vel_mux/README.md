# rds_2p_cmd_vel_mux

Мультиплексор команд скорости RDS-2P. Подписан на несколько источников
`geometry_msgs/msg/Twist`, но публикует в `/cmd_vel` только команды
выбранного источника. Не зависит от пакета джойстика.

## Запуск

```bash
ros2 launch rds_2p_cmd_vel_mux cmd_vel_mux.launch.py
```

## Выбор источника

```bash
# Джойстик
ros2 topic pub --once /cmd_vel_mux/select std_msgs/msg/String "{data: joy}"

# Клавиатура
ros2 topic pub --once /cmd_vel_mux/select std_msgs/msg/String "{data: keyboard}"

# Голосовые команды
ros2 topic pub --once /cmd_vel_mux/select std_msgs/msg/String "{data: voice}"

# Остановить передачу команд (в /cmd_vel пойдёт нулевая Twist)
ros2 topic pub --once /cmd_vel_mux/select std_msgs/msg/String "{data: none}"
```

## Правила

- выбранный источник пропускается в `/cmd_vel` без смешивания с остальными;
- источник считается **свежим**, пока от него приходят сообщения (таймаут
  задаётся отдельно для каждого источника);
- если выбранный источник молчит дольше таймаута, публикуется нулевая
  `Twist`, а `/cmd_vel_mux/active = false`;
- при смене источника его прошлая команда сбрасывается: нужно новое
  сообщение от источника;
- неизвестное имя игнорируется с warning;
- при старте выбирается `default_source` из YAML (`joy` по умолчанию).

## Конфигурация

`config/cmd_vel_mux.yaml`:

| Источник | Топик | Таймаут |
|----------|-------|---------|
| `joy` | `/cmd_vel/joy` | 0.5 с |
| `keyboard` | `/cmd_vel/keyboard` | 0.5 с |
| `voice` | `/cmd_vel/voice` | 2.5 с |

Клавиатура подключается remap'ом:

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args \
    -r cmd_vel:=/cmd_vel/keyboard
```

Проверка состояния:

```bash
ros2 topic echo /cmd_vel_mux/state --once
ros2 topic echo /cmd_vel_mux/active --once
```