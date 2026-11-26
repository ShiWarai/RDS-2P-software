# rds_2p_commands

ROS 2 пакет для текстовых/голосовых команд из нескольких источников (топики, Telegram, расширяемо под Алису/Сбер и др.) и универсального Action сервера. Реализованы **`PandaCommand`**: звук из `share/.../data/sounds/`, морда через топик **`/face/image`** под ноду `rds_2p_face/display_face`. **Нормализованные позы** задаются в [`config/panda_poses.yaml`](src/rds_2p_commands/config/panda_poses.yaml); **позы** пересчитываются через `calibrate.json` (параметр `motor_calibrate_path`) и публикуются в **`/motors/commands`** (`no_limit` через `MotorCommand.ignore_limits`), а `norm`/`pos` дублируются в лог.

Зависимости Python декларируются в `package.xml` / `rosdep`; отдельный `requirements.txt` не используется.

## Ассеты

- После сборки: `share/rds_2p_commands/data/faces/`, `.../data/sounds/`.
- В репозитории добавлены **минимальные placeholder’ы**; замените их реальными файлами из `rtulab_feetech/sound/` и `/home/orangepi/face/image/` — см. `data/README.md`.

## Быстрый старт

### 1. Сборка

```bash
cd ~/RDS-2P-software/ros_packages
source install/setup.bash

colcon build --packages-select rds_2p_commands
```

### 2. Запуск без Telegram

Нужны **`unified_action_server`** + **`command_parser`**, отдельно **`rds_2p_audio/audio.launch.py`** (**`audio_player`** на `/audio/output` микширует по `frame_id`, по умолчанию **44100 Hz** — договор с PortAudio ALSA «default»/ES8323; WAV ресемпится в обработчике `PandaCommand` под `audio_output_rate`; по умолчанию пайп сценариев шлёт **стерео L=R**, как `test_speaker.py --force-stereo` — так надёжнее с `output_channels:=1`). Для морды — нода **`display_face`** из `rds_2p_face` на **`/face/image`** (часто через `sudo`; см. README `rds_2p_face`).

```bash
source install/setup.bash

ros2 launch rds_2p_commands command_parser.launch.py
ros2 launch rds_2p_commands unified_action_server.launch.py
```

#### Аудио: `rds_2p_audio` (микрофон + динамик на роботе)

Пример для Orange Pi / робота (микрофон часто **mono** → `capturer_channels:=1`, иначе PortAudio может дать «Invalid number of channels»; индексы устройств подставь свои):

```bash
ros2 launch rds_2p_audio audio.launch.py \
  output_device:=-1 output_channels:=1 \
  capturer_device:=8 capturer_rate:=16000 capturer_channels:=1 capturer_chunk:=1024
```

На практике могут понадобиться донастройка воспроизведения и качество картинки на морде. **Диагностика звука:** в логах ноды **`unified_action_server`** ищи строки **`Аудио:`** (есть файл, число сообщений AudioStamped, подписчики на `/audio/output`). Если тишина — проверь, что сообщения содержат **непустой** `header.frame_id`, а `audio.info.rate` совпадает с `audio_player`. В **`command_parser`** при той же команде будут строки **`PandaCommand … [сервер]: sound: …`** из feedback действия — если их нет, обработчик сценария не дошёл до звука. QoS воспроизведения как у `audio_player` (**BEST_EFFORT**) и у паблишеров должны быть согласованы.

### 3. Проверка сценария панды через транскрипт

Пример («лежать»):

```bash
ros2 topic pub --once /audio/input/transcription rds_2p_audio/msg/Transcription \
  "{text: 'лежать', audio_time: 0.0, transcription_time: 0.0}"
```

### 4. Прямой вызов Action (опционально)

Просмотр полей цели и результата:

```bash
ros2 interface show rds_2p_commands/action/PandaCommand
```

Пример отправки цели:

```bash
ros2 action send_goal /robot/panda_command rds_2p_commands/action/PandaCommand \
  "{routine_id: lie_down, source: cli}"
```

### 5. Полная связка через `commands_system.launch.py`

```bash
ros2 launch rds_2p_commands commands_system.launch.py
```

Запускает только **`unified_action_server`** + **`command_parser`** (regex/keywords из
`commands.yaml`). LLM, диалог и TTS теперь в **`mirea_rag`**; `rkllm_ros`/Paroli
из этого пакета не вызываются.

### 6. Компактный пресет «Команды Панды» (`panda_commands`)

Нода **`panda_commands`** (launch: **`rds_2p_commands/panda_commands.launch.py`**) реализует компактный пресет: один choice-вопрос `q_commands` из [`config/panda_commands.yaml`](src/rds_2p_commands/config/panda_commands.yaml) — 7 реально исполняемых `routine_id` из [`config/commands.yaml`](src/rds_2p_commands/config/commands.yaml) (`give_paw`, `stand_at_attention`, `dismiss`, `lie_down`, `rotate`, `pray`, `reconnect_joystick`) плюс метка **`Не команда`** с пустой веткой. Классификатор всегда выбирает один из вариантов; «ничего не делать» — это выбор `no_command`, а не отсутствие ответа. При заданном `min_confidence` ветка не выполняется, если уверенность ниже порога. Классификация — через нативный **`system_one_ros`** (`llm_msgs_ros/srv/Ask`, сервис **`/system_one/ask`**), без `command_parser` и regex.

В общем стеке `rds_2p/launch/panda.launch.py` режим выбирается аргументом **`commands_mode`**: `osm` (по умолчанию, `panda_commands` + system-one) или `regex` (старый `command_parser` + `commands.yaml`).

```bash
ros2 launch rds_2p_commands panda_commands.launch.py

# в общем стеке (OSM по умолчанию):
ros2 launch rds_2p panda.launch.py motion_mode:=pose stt:=gigaam commands_mode:=osm

# если system_one client и unified_action_server уже запущены отдельно:
ros2 launch rds_2p_commands panda_commands.launch.py \
  include_system_one:=false include_action_server:=false
```

Что запускает launch:

- `system_one_ros/system_one.launch.py` — нативный Kev `/system_one/ask`;
- `unified_action_server` — исполнитель `PandaCommand`;
- `panda_commands` — подписка на `/audio/input/transcription`, классификация и выполнение `command` / `wait` / `say`.

`command` с `routine_id` уходит в `/robot/panda_command`; `say` — в `/audio/output/speak`. Ответ классификатора публикуется в `/panda_commands/decision` (JSON). В логе решение видно строкой `q_commands: <метка> → <option id> (conf ..., ... ms)`. `dry_run:=true` — только классификация без действий. Механизм `motion_commands` (шаги через `/cmd_vel/voice`) поддерживается нодой, но в компактный пресет не включён: шаги выполнимы только при запущенном `rds_2p_inference` (`motion_mode:=walk`).

Проверка без микрофона:

```bash
ros2 topic pub --once /audio/input/transcription rds_2p_audio/msg/Transcription "{text: 'дай лапу'}"
ros2 topic echo /panda_commands/decision --qos-durability transient_local --once
```

`dry_run:=true` не отключает классификацию: запрос в system_one_rknn выполняется, решение публикуется в `/panda_commands/decision`, но `command`/`wait`/`say` не исполняются.

Ключевые аргументы: `config_file`, `input_topic`, `system_one_service`, `model`, `min_confidence`, `dry_run`, `include_system_one`, `include_action_server`, `say_enabled`, `publish_cmd_vel`, `interrupt_keywords`.

---

## Конфигурация

| Место | Назначение |
|------|------------|
| [config/commands.yaml](src/rds_2p_commands/config/commands.yaml) | **`commands`**: ключ = `routine_id`, **`keywords`**, звук/морда. |
| [config/panda_commands.yaml](src/rds_2p_commands/config/panda_commands.yaml) | Дерево пресета «Команды Панды»: question/choice, options/examples/then, motion_commands. |
| [config/panda_poses.yaml](src/rds_2p_commands/config/panda_poses.yaml) | Позы: секция **`poses`**, каждая — список из **12** нормализованных долей (как `voice_control.py`). |
| [rds_2p_commands/servo_constants.py](src/rds_2p_commands/rds_2p_commands/servo_constants.py) | Только константа **`SERVO_IDS`** (1..12). |
| [rds_2p_commands/unified_action_server.py](src/rds_2p_commands/rds_2p_commands/unified_action_server.py) | Сервер `PandaCommand`; при `allow_parallel_same_class:=false` новая цель отменяет предыдущую в слоте `motors`. |

### Параметры `RobotRoutineHandler` (у `unified_action_server`)

Через `ros2 param` на ноду `unified_action_server`:

- `commands_config` (default **`commands.yaml`**) — имя файла команд в `share/rds_2p_commands/config/`
- `panda_poses_config` (default **`panda_poses.yaml`**) — имя файла поз (секция `poses`) в том же каталоге

- `audio_output_topic` (default `/audio/output`)
- `audio_output_rate` (default **44100**, синхрон с `output_sample_rate` плеера; WAV при другой Fs ресемпится)
- `audio_playback_chunk_size` (default **2048**, как у `scripts/test_speaker.py`; меньше DDS/CPU jitter, чем старые 512)
- `audio_output_qos_depth` (default **50**, глубина QoS для publisher `/audio/output`, как `test_speaker`)
- `audio_wait_for_subscribers_sec` (default **2.0**, ожидание `audio_player` перед проигрыванием; если **0** — не ждать)
- `audio_output_force_stereo` (default **true**, как `--force-stereo` у `test_speaker.py`; **`false`** если у вас уже играет моно)
- `wav_peak_normalize` (default **true**) — перед `playback_volume_percent` нормализует mono по пику до ±1, чтобы тихо сведённые WAV не проигрывались заметно тише TTS/других источников (**`false`**, если мастер уже «в ноль» и не нужен автогейн)
- `playback_volume_percent` (default **100**, допускается до **200**) — множитель после нормализации; в `unified_action_server.launch.py`: аргументы **`playback_volume_percent`**, **`wav_peak_normalize`**
- `face_image_topic` (default **`/face/image`**)
- `publish_motor_positions` (default **`true`**) — публиковать позы в `/motors/commands`
- `motor_commands_topic` (default **`/motors/commands`**)
- `motor_states_topic` (default **`/motors/states`**) — подтверждение `enabled` и позиция лапы для `give_paw`
- `motor_config_file` (пусто — `ftservo_ros/config/config_example.yaml`) — `zero_offset_units`, `reversed`, `motor_units_per_radian` для пересчёта units→rad
- `allow_real_joystick_script` (default **`false`**)
- `joystick_script_path` — путь к `reconnect_joystick.sh`
- `motor_calibrate_path` (default **`/home/orangepi/rtulab_feetech/calibrate.json`**) — калибровка для перевода долей в **pos** (как `leg/utils.calculate_position`). Если файл недоступен, логируются только доли.

Для траектории **`pray`** кейфреймы подхватываются из `/home/orangepi/rtulab_feetech/leg/pray_snippet_motion_embedded.py`, если каталог доступен на машине.

### Command parser

- **`config_file`** — имя YAML в `share/rds_2p_commands/config/` (по умолчанию **`commands.yaml`**). Встроенного дубля команд в Python нет: при отсутствии файла или ошибке чтения **`commands`** пусты.
- **`transcription_topics`** — список топиков `vosk_ros/Transcription`; новые мосты публикуют сюда или в `/telegram/message` (`std_msgs/String`).
- **`command_debounce_sec`** (default **3.0**) — дребезг по паре **`(источник, имя команды в YAML)`**.

---

## Контракт много источников

1. Новый канал должен давать **сырой текст** в ROS; разбор по ключевым словам — в **`commands.yaml`**.
2. Расширение: добавить топик в **`transcription_topics`** или использовать `/telegram/message`.
3. Поле **`source`** в goal `PandaCommand` пробрасывается парсером (`voice`, `telegram`, …) для логов и будущих квот/ACL.

---

## Telegram

### Токен Telegram

Откройте Telegram → [@BotFather](https://t.me/BotFather) → `/newbot`; запуск отдельного моста: пакет `rds_2p_telegram_bot`.

### Запуск с несколькими топиками транскрипции

```bash
ros2 launch rds_2p_commands commands_system.launch.py \
    transcription_topics:="['/audio/input/transcription', '/telegram/audio/transcription', '/custom/transcription']" \
    command_debounce_sec:=3.0
```

### Telegram бота (пример из `rds_2p_telegram_bot`)

```bash
ros2 launch rds_2p_telegram_bot telegram_bot.launch.py \
    telegram_token:='ВАШ_ТОКЕН' \
    commands_topic:='/commands' \
    audio_topic:='/telegram/audio' \
    audio_sample_rate:=16000 \
    auth_enabled:=false
```

---

## ROS 2 топики

- `/telegram/message` (`std_msgs/String`)
- транскрипции: топики из `transcription_topics` (`vosk_ros/Transcription`)
- воспроизведение звука: публикует `unified_action_server` → см. параметр **`audio_output_topic`**
- изображение морды: топик см. **`face_image_topic`** (подписчик `display_face` в **`rds_2p_face`**)

## Параметры launch (`command_parser` / `commands_system`)

Дополнительно к уже описанному:

**Дребезг:** `command_debounce_sec` — минимальный интервал между одинаковыми командами одного источника.

## Конфигурация команд и безопасность

Команды задаются в **`config/commands.yaml`**. У парсера и `unified_action_server` один слот класса целей **`motors`** (см. `PANDA_GOAL_CLASS` / `PANDA_ACTION_SLOT` в коде). Токены не хранить в репозитории:

```bash
export TELEGRAM_TOKEN='ваш_токен'
ros2 launch rds_2p_telegram_bot telegram_bot.launch.py telegram_token:=$(echo $TELEGRAM_TOKEN)
```
