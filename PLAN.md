# План работ RDS-2P

## Новые задачи

### 1. Motion mode manager — режимы механики робота

**Статус:** не начато

**Проблема.** Несколько узлов одновременно пишут команды в одну моторику, арбитража нет:

- `inference_node` → `joint_to_motor_bridge` публикует `/joint_commands` → `/motors/commands` на 50 Гц;
- `dance_action_server` публикует `/joint_commands`;
- `unified_action_server` / `robot_routine_handler` публикует статические позы прямо в `/motors/commands`;
- `motor_controller` принимает `/motors/params` (torque on/off).

Кто последний записал в `/motors/commands`, тот и победил. Поэтому `give_paw`, `stand_at_attention` и другие routine затираются ходьбой/стойкой, а танец может конфликтовать с inference. `cmd_vel_mux` арбитрирует только скорости (`/cmd_vel`), но не позы суставов. Старый `voice_control.py` работал потому, что писал в сервы напрямую по serial, минуя ROS.

**Цель.** Один менеджер режимов, который определяет, кто сейчас владеет механикой, и не даёт источникам затирать друг друга.

**Режимы (минимум):**

- `estop` — аварийный стоп, наивысший приоритет, момент снят;
- `torque_off` / `idle` — безопасное состояние без активного владельца;
- `pose` / `stand` — статические позы routine (`give_paw`, `stand_at_attention`, `dismiss`, `lie_down`);
- `walk` — `inference_node` + `joint_to_motor_bridge`, внутри работает `cmd_vel_mux` (joy/keyboard/voice);
- `dance` — `dance_action_server`;
- в будущем: `ball_follow`, `patrol` и другие.

**Требования:**

- сервис/топик `/motion/set_mode` (режим, владелец, таймаут, приоритет);
- bridge/inference/dance/routine проверяют активный режим перед публикацией команд;
- routine handler на время `/robot/panda_command` переключает `pose`, после завершения возвращает предыдущий режим;
- `estop` перекрывает всё, включая танец и routine;
- watchdog: если владелец не продлил режим или узел умер — возврат в `idle`/`torque_off`;
- `cmd_vel_mux` остаётся арбитром скоростей внутри `walk`;
- обратная совместимость: без менеджера поведение не должно ломаться (поэтапное включение).

**Критерии готовности:**

- при активном `walk` команда «равняйся» переводит робота в `pose`, поза удерживается, затем режим возвращается в `walk`;
- «дай лапу» выполняется при включённом inference/bridge, поза не затирается;
- танец и routine не конфликтуют; `estop` мгновенно снимает момент;
- в логах видно текущий режим, владельца и причину переключения.

**Затрагиваемые пакеты:** `rds_2p` (`joint_to_motor_bridge`), `rds_2p_inference`, `rds_2p_commands` (`robot_routine_handler`), `rds_2p_dance`, `rds_2p_cmd_vel_mux`, запуск `rds_2p/launch/panda.launch.py`.

**Текущий обходной путь:** вручную останавливать `inference_node` и `joint_to_motor_bridge` перед позами — не является решением.