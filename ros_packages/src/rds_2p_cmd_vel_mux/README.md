# rds_2p_cmd_vel_mux

Мультиплексор команд скорости RDS-2P. Подписан на несколько источников
`geometry_msgs/msg/Twist` (любой `/cmd_vel/<имя>`) и публикует в `/cmd_vel`
только команды активного источника. Не зависит от пакета джойстика.

**По умолчанию — auto-follow:** без явного выбора mux сам пропускает тот
источник, который сейчас шлёт не-нулевую команду (`|twist| > zero_epsilon`
и свежий). Если таких несколько — самый свежий; привязки к определённому
`/cmd_vel/*` нет.

При этом `/cmd_vel_mux/active` остаётся `true`, пока есть **любой свежий**
источник, даже если он шлёт нулевую `Twist` (джойстик в центре). Это важно:
`inference_node` по `active` держит управление и IMU-позу (R1+tilt), а не
блокируется. `active=false` — только когда все источники замолчали
(контроллер отключён) дольше таймаута.

## Запуск

```bash
ros2 launch rds_2p_cmd_vel_mux cmd_vel_mux.launch.py
```

## Выбор источника (опциональный override)

Явный выбор **перекрывает** auto-follow: пока выбран источник, mux пропускает
только его (даже если он молчит — публикуется нулевая `Twist`). Пустая
строка/`none` снимает выбор и возвращает к auto-follow.

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

Имя и полный топик эквивалентны: `keyboard` и `/cmd_vel/keyboard` — один и тот же источник.

## Авто-обнаружение источников

В YAML включён `auto_discover: true` (префикс `/cmd_vel/`): любой топик
`/cmd_vel/<имя>` типа `Twist` сам добавляется как источник с именем `<имя>`
(таймаут `auto_source_timeout`, по умолчанию 0.5 с). Прописанные в YAML
`joy`/`keyboard`/`voice`/`ball_follow` — просто заранее известные имена; новое
устройство подключается **без правки конфига**.

Пример: teleop на новое имя `teleop` (mux подхватит `/cmd_vel/teleop` в течение ~1 с):

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args \
    -r cmd_vel:=/cmd_vel/teleop
ros2 topic pub --once /cmd_vel_mux/select std_msgs/msg/String "{data: teleop}"
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
| `ball_follow` | `/cmd_vel/ball_follow` | 0.5 с |

Плюс любые `/cmd_vel/<имя>` через `auto_discover` (см. выше).

Другие параметры: `auto_follow` (true — auto-follow по умолчанию),
`default_source` (пусто = без привязки; имя = явный выбор при старте),
`auto_discover`, `auto_discover_prefix` (`/cmd_vel/`), `auto_source_timeout`
(0.5 с для авто-источников), `publish_rate` (20 Гц), `zero_epsilon`.

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