# rds_2p_commands

ROS 2 пакет для текстовых/голосовых команд из нескольких источников (топики, Telegram, расширяемо под Алису/Сбер и др.) и универсального Action сервера. Реализованы **`PandaCommand`**: звук из `share/.../data/sounds/`, морда через топик **`/face/image`** под ноду `rds_2p_face/display_face`. **Нормализованные позы** задаются в [`config/panda_poses.yaml`](src/rds_2p_commands/config/panda_poses.yaml); в лог выводятся **доли** (`norm`) и **pos** из `calibrate.json` (параметр `motor_calibrate_path`; без файла — только `norm`).

Зависимости Python декларируются в `package.xml` / `rosdep`; отдельный `requirements.txt` не используется.

## Ассеты

- После сборки: `share/rds_2p_commands/data/faces/`, `.../data/sounds/`.
- В репозитории добавлены **минимальные placeholder’ы**; замените их реальными файлами из `rtulab_feetech/sound/` и `/home/orangepi/face/image/` — см. `data/README.md`.

## Быстрый старт

### 1. Сборка

```bash
cd ~/RDS-2P-simulator/ros_packages
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
ros2 topic pub --once /audio/transcription vosk_ros2/msg/Transcription \
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

Нужны отдельно **`ros2 launch rkllm_ros2 rkllm.launch.py …`** (модель уже у вас) и **`ros2 launch paroli_ros2 tts.launch.py`** плюс **`rds_2p_audio`** для `/audio/output`, если озвучка должна идти в динамик.

### 6. Слово «панда» → сценарий + ответ LLM (rkllm) и Paroli

Если в **распознанном** тексте есть подстрока **`панда`** (без учёта регистра) **и** либо команда сопоставлена с рутиной из `commands.yaml`, либо **рутина не найдена** по ключевым словам в YAML, то всё равно:

1. Если рутина **есть** — как обычно отправляется **`PandaCommand`** (звук, моторы, морда).
2. Если рутины **нет** — **`PandaCommand` не шлётся**, только диалог.
3. В обоих случаях тот же текст уходит в **`rkllm_ros2`** (`ChatCompletion`, `user_message` = фраза пользователя).
4. Поле **`result.text`** озвучивается через **`/paroli_ros2/speak`**.

**Блокировка:** с момента старта запроса к LLM до опустошения очереди озвучки новые фразы **не** обрабатываются (ни рутины по YAML, ни второй LLM). Это **не** однопоточность executor: узел по-прежнему получает транскрипты, но в лог пишется **`Пропуск … занят диалог LLM/озвучка`**. Пока играет динамик, Vosk часто выдаёт **обрывки своей же речи** (как в вашем логе) — это акустическое эхо. После последней фразы Paroli смотрите **`LLM+Paroli: озвучка завершена, приём команд возобновлён`** — до этой строки парсер сознательно «молчит» по командам. Прервать: ключи **`panda_dialog_interrupt`** (см. ниже); в железе — тише динамик, микрофон дальше от динамика, AEC при наличии.

**«Хватит»:** фразы из **`panda_dialog_interrupt.keywords`** проверяются **первыми** и **вне** блокировки: отменяется goal rkllm (если был), вызывается **`/paroli_ros2/stop_speech`**, снимается блокировка. Отдельного **`PandaCommand`** нет.

Раньше пункты 3–4 срабатывали только при успешно распознанной рутине; для фраз вроде «панда, ты меня слышишь» без ключевых слов теперь вызывается только LLM+Paroli.

Параметры узла **`command_parser`** (и одноимённые аргументы в `command_parser.launch.py` / `commands_system.launch.py`):

| Параметр | Смысл |
|----------|--------|
| `panda_llm_tts_enabled` | Включить цепочку (по умолчанию `true`). |
| `panda_llm_trigger_substring` | Подстрока-триггер (по умолчанию `панда`). |
| `rkllm_complete_action` | Action, по умолчанию `/rkllm_ros2/complete`. |
| `rkllm_clear_kv_service` | `std_srvs/Trigger`, по умолчанию `/rkllm_ros2/clear_kv_cache`; пустая строка — клиент не создаётся. |
| `paroli_speak_service` | По умолчанию `/paroli_ros2/speak`; пустая строка — без озвучки. |
| `paroli_stop_speech_service` | `std_srvs/Trigger`, по умолчанию `/paroli_ros2/stop_speech` — прерывание TTS (команда «хватит»). |
| `rkllm_clear_kv_before_query` | Перед запросом сбросить KV (см. README `rkllm_ros2` / `persist_session_kv`). |
| `rkllm_keep_history`, `rkllm_max_new_tokens`, таймауты | Как в declare в коде. |
| `llm_stream_tts_by_punctuation` | `true` (по умолчанию): по **feedback** rkllm копится текст; на `. , ; : ! ? …` фрагменты ставятся в очередь `/speak` — раньше старт озвучки. |
| `llm_sanitize_user_and_reply` | `true`: в LLM и в TTS только буквы (Unicode), цифры, пробелы, пунктуация; эмодзи убираются; **markdown-символы `*` `_` `` ` `` `#` `|`** выкидываются отдельным шагом (иначе `*` остаётся как знак препинания Unicode). |
| `llm_stream_min_chunk_chars` | Мин. длина фрагмента для разбиения по запятой/точке с запятой (не считая `! ? …`). |
| `llm_reply_log_max_chars` | Длина сводки ответа LLM в INFO (0 — без обрезки сводки). |
| `paroli_speak_log_max_chars` | Длина строки «Paroli /speak фр.» в логе (0 — весь текст фрагмента). |

Отключить поведение: `panda_llm_tts_enabled:=false` или сменить/очистить триггер. Потоковую нарезку: `llm_stream_tts_by_punctuation:=false`.

**Логи:** транскрипт — **INFO**; фрагменты в Paroli — **`Paroli /speak фр.N`**; сводка ответа после rkllm — **INFO**.

---

## Конфигурация

| Место | Назначение |
|------|------------|
| [config/commands.yaml](src/rds_2p_commands/config/commands.yaml) | **`commands`**: ключ = `routine_id`, **`keywords`**, звук/морда. Вне **`commands`**: **`panda_dialog_interrupt`** — **`keywords`** фраз прерывания диалога LLM («хватит» и др.), всегда обрабатываются первыми. |
| [config/panda_poses.yaml](src/rds_2p_commands/config/panda_poses.yaml) | Позы: секция **`poses`**, каждая — список из **12** нормализованных долей (как `voice_control.py`). |
| [rds_2p_commands/servo_constants.py](src/rds_2p_commands/rds_2p_commands/servo_constants.py) | Только константа **`SERVO_IDS`** (1..12). |
| [rds_2p_commands/llm_commands.py](src/rds_2p_commands/rds_2p_commands/llm_commands.py) | rkllm + очередь `/speak` Paroli, прерывание диалога. |
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
- `allow_real_systemd` (default **false**) — включать **только осознанно** (`systemctl` для inference)
- `allow_real_joystick_script` (default **false**)
- `joystick_script_path` — путь к `reconnect_joystick.sh`
- `motor_calibrate_path` (default **`/home/orangepi/rtulab_feetech/calibrate.json`**) — калибровка для перевода долей в **pos** (как `leg/utils.calculate_position`). Если файл недоступен, логируются только доли.

Для траектории **`pray`** кейфреймы подхватываются из `/home/orangepi/rtulab_feetech/leg/pray_snippet_motion_embedded.py`, если каталог доступен на машине.

### Command parser

- **`config_file`** — имя YAML в `share/rds_2p_commands/config/` (по умолчанию **`commands.yaml`**). Встроенного дубля команд в Python нет: при отсутствии файла или ошибке чтения **`commands`** и **`panda_dialog_interrupt`** пусты.
- **`panda_dialog_interrupt`** — в **`commands.yaml`**: список **`keywords`**. Одно слово — совпадение по **токенам** (не срабатывает на фразу **«не хватит»** при ключе `хватит`). Несколько слов через пробел — вхождение подстроки в текст. Не отправляют `PandaCommand`, только прерывают rkllm+Paroli и снимают блокировку.
- **`transcription_topics`** — список топиков `vosk_ros2/Transcription`; новые мосты публикуют сюда или в `/telegram/message` (`std_msgs/String`).
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
    transcription_topics:="['/audio/transcription', '/telegram/audio/transcription', '/custom/transcription']" \
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
- транскрипции: топики из `transcription_topics` (`vosk_ros2/Transcription`)
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
