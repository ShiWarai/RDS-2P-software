# paroli_ros2

ROS 2 узел **Paroli** на **RK3588** (ONNX + RKNN, Piper‑совместимые голоса): обёртка вокруг **`paroli-cli`**, публикация **`audio_common_msgs/AudioStamped`** (например для `audio_common` / `rds_2p_audio`).

## Зависимости в дереве исходников

| Путь | Назначение |
|------|------------|
| **`vendor/paroli-cli`**, **`vendor/lib/*.so`** | Из сборки **paroli-tts**; без **paroli-cli** CMake не соберёт пакет. |
| **`models/`** | Не хранится в git (см. **`models/README.md`** и **`.gitignore`**). После `colcon` кладётся в **`share/paroli_ros2/models/`**. |

Голос по умолчанию: **`models/ruslan/`** — только **`encoder.onnx`**, **`decoder.rknn`**, **`ru_RU-ruslan-medium.onnx.json`**, плюс **`models/espeak-ng-data/`**. Остальное из полного `rsync` (`decoder.onnx`, `*.onnx` вес, старые копии в корне `models/`) для этой ноды не нужно — см. **`models/README.md`**.

Другой голос: параметры **`encoder_path`**, **`decoder_path`**, **`model_config_path`**; **`espeak_data_path`** обычно общий.

**Сервис `paroli_ros2/speak`** → **`paroli_ros2/srv/Speak`**: **`text`**, **`volume`** — множитель амплитуды PCM после ресемплинга (`0` — тишина, `1` — без изменений, `>1` — усиление с клипом int16). Поле **`volume` в запросе нужно задавать явно**; если в YAML оно опущено, часто приходит `0` → тишина.

**Параметр ноды `tts_volume`** используется только для топика **`~/speak_text`** (там нет поля громкости); задать: `ros2 run paroli_ros2 tts_node.py --ros-args -p tts_volume:=1.5`.

**Сервис `paroli_ros2/stop_speech`** → **`std_srvs/Trigger`**: аварийно глушит **`paroli-cli`** (обрывает синтез и выдачу в `audio_player`). Вызывается парсером команд при фразах из **`panda_dialog_interrupt`** (`rds_2p_commands`).

**Топик (опция):** **`~/speak_text`** (`std_msgs/String`) → **`/paroli_ros2/speak_text`** — тот же синтез, что и сервис; если в этот момент уже идёт вызов `/speak`, сообщение отбрасывается (см. WARN в логе).

**Зависимости runtime:** `python3-numpy`, `python3-scipy` (ресемплинг WAV от `paroli-cli` под `output_sample_rate`) — см. **`package.xml`**.

## Модели

```bash
rsync -a ~/paroli-tts/models/ruslan/           src/paroli_ros2/models/ruslan/
rsync -a ~/paroli-tts/models/espeak-ng-data/   src/paroli_ros2/models/espeak-ng-data/
colcon build --packages-select paroli_ros2
```

## Запуск

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash

# опционально плеер:
ros2 launch rds_2p_audio audio.launch.py enable_capturer:=false

ros2 launch paroli_ros2 tts.launch.py

ros2 service call /paroli_ros2/speak paroli_ros2/srv/Speak "{text: 'Привет.', volume: 1.0}"

# громче на этом вызове
ros2 service call /paroli_ros2/speak paroli_ros2/srv/Speak "{text: 'Привет.', volume: 1.5}"
```

В **bash** с **`!`** в тексте не используйте внешние двойные кавычки (история подставок). Надёжно:

```bash
ros2 service call /paroli_ros2/speak paroli_ros2/srv/Speak '{text: "Привет, как дела!", volume: 1.0}'
```

### Параметры ноды (`tts_node.py`)

| Параметр | По умолчанию | Заметка |
|----------|----------------|---------|
| `output_topic` | `/audio/output` | Совпадение rate с `audio_player`. |
| `frame_id` | `tts.paroli` | Непустой `frame_id` обязателен для микшера. |
| `output_sample_rate` | `44100` | |
| `chunk_frames` | `4096` | Размер куска AudioStamped (mono кадров). |
| `force_stereo` | `false` | `true` — дублирование mono в L=R (как у сценариев с `audio_output_force_stereo`). |
| `use_stdbuf` | `true` | `stdbuf -o0 -i0` для `paroli-cli`. |
| `qos_depth` | `50` | QoS publisher. |
| `speaker_id` | `-1` | `>=0` — уходит в JSON в stdin. |
| `wav_extra_wait_after_segment_sec` | `0` | Редкий случай нескольких WAV в одном ответе. |
| `split_sentences_for_synthesis` | **`false`** | **`true`** — обход без пересобранного `paroli-cli` (см. ниже). |
| `between_sentence_silence_sec` | `0.12` | Пауза между частями при split. |
| `paroli_cli_path`, `paroli_ld_library_path` | из префикса пакета | |
| `encoder_path`, `decoder_path`, `model_config_path`, `espeak_data_path` | `models/ruslan/…`, `models/espeak-ng-data` | |
| `accelerator` | `''` | Опционально для ONNX (`--accelerator`). |
| `length_scale` | **`-1`** | **`≥0`** → `--length-scale` (Piper: меньше 1 — быстрее, больше 1 — медленнее). **`-1`** — не задавать (дефолт из конфига модели). |
| `noise_scale` | **`-1`** | **`≥0`** → `--noise-scale`; **`-1`** — не задавать. |
| `noise_w` | **`-1`** | **`≥0`** → `--noise-w`; **`-1`** — не задавать. |
| `tts_volume` | **`1.0`** | Громкость только для топика **`speak_text`**; для **`/speak`** задаётся полем **`volume`**. |

Смена **`length_scale` / `noise_*` / путей модели** вызывает **перезапуск `paroli-cli`** перед следующим синтезом.

Пример быстрой речи: `ros2 launch paroli_ros2 tts.launch.py length_scale:=0.88`

**`tts.launch.py`** пробрасывает: `output_topic`, `frame_id`, `output_sample_rate`, `chunk_frames`, `force_stereo`, `use_stdbuf`, **`length_scale`**, **`noise_scale`**, **`noise_w`**. Громкость **`/speak`** — только поле **`volume`** в **`Speak`**; **`tts_volume`** и прочее — через `ros2 run … --ros-args -p …`.

### Несколько предложений / «пропало начало или конец текста»

**Причина в движке Piper (у тебя это `paroli-tts/piper/piper.cpp`):** в ветке «короткого» выхода энкодера выполнялось `audioBuffer = decoder->infer(...)`, то есть **буфер целиком перезаписывался на каждом фрагменте** (второе предложение стирает первое). В `main.cpp` один вызов `textToWavFile` на строку — проблема не в разборе JSON, а в этом присваивании.

**Исправление в C++:** пересобрать `paroli-cli` с патчем `audioBuffer.insert(..., decoded.begin(), decoded.end())` (см. репозиторий `~/paroli-tts`) и скопировать бинарник в `paroli_ros2/vendor/`.

**Обход без пересборки:** параметр **`split_sentences_for_synthesis`** (по умолчанию **false**) — при **true** в stdin уходит **несколько JSON-строк** по предложениям; нужно только со **старым** `paroli-cli` до патча `piper.cpp`. **`between_sentence_silence_sec`** (по умолчанию **0.12**) — пауза между частями при split.

Раньше мы читали несколько RIFF из одного ответа — у `paroli-cli` за одну строку на stdout приходит **один** WAV; «несколько WAV» было следствием других сценариев, не корневая причина «только последнее предложение».

Параметр **`wav_extra_wait_after_segment_sec`**: если second WAV приходит вторым `write` с задержкой — можно поднять до `0.05`…`0.15`.

Скрипт **`scripts/tts_node.py`** в репозитории должен быть исполняемым (`chmod +x`), иначе при **`colcon build --symlink-install`** launch не увидит executable.

**`.so`:** нода добавляет в **`LD_LIBRARY_PATH`** каталог **`lib/paroli_ros2/vendor/lib`**. При желании можно пропатчить **`RUNPATH`** у **`paroli-cli`** через **`patchelf`**.

Если **`ros2 service` / `ros2 topic`** падают с **`!rclpy.ok()`**, попробуйте **`ros2 daemon stop`** и повторите команду.

### Сборка: `Could not create symlink` / `File exists` в `models/espeak-ng-data`

Типично при **`colcon build --symlink-install`**: в **`install/`** уже лежат обычные файлы, а CMake хочет заменить их симлинками на **`src/`**. Удалите установленные модели и пересоберите:

```bash
rm -rf install/paroli_ros2/share/paroli_ros2/models
colcon build --packages-select paroli_ros2
```

Либо один раз соберите этот пакет **без** symlink-install; либо очистите весь префикс **`install/paroli_ros2`**.
