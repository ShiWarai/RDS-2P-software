# rds_2p_audio

Пакет воспроизведения на роботе: нода **`audio_player`** принимает `audio_common_msgs/AudioStamped` на шине воспроизведения (**по умолчанию `/audio/output`**), разделяет поток по **`header.frame_id`**, **суммирует** источники и отдаёт **один** PortAudio-поток (драйвер через `sounddevice`).

Отдельно на запуск добавляется `audio_common/audio_capturer_node` через единственный файл **`launch/audio.launch.py`**.

---

## Контракт `AudioStamped` на воспроизведение

| Поле | Правило |
|------|---------|
| `header.frame_id` | **Обязательно** непустая строка, рекомендуемый вид `домен.ид`: `routine.lie_down`, `test_speaker`, `tts.paroli` (paroli_ros2) и т.д. Одна строка однозначно относится к «источнику» для микшера. Пустое значение — сообщение отбрасывается. |
| `audio.info.rate` | Должно быть **строго равно** параметру узла **`output_sample_rate`** (launch `output_sample_rate`, для Orange Pi RK/ES8323 обычно **44100**). Иначе чанк отбрасывается. |

Ресемплинг под целевую Fs делают **издатели** (наш `RobotRoutineHandler`, `test_speaker.py` и т.д.).

Известные источники в дереве RDS-2P:

- `routine.<routine_id>` — сценарии панды из `RobotRoutineHandler`.
- `test_speaker` (или свой `--source-id`) — утилита `scripts/test_speaker.py`.

---

## Запуск робота (`audio.launch.py`)

```bash
source install/setup.bash

ros2 launch rds_2p_audio audio.launch.py \
  output_device:=-1 \
  pulse_sink:=alsa_output.platform-es8388-sound.stereo-fallback \
  output_channels:=1 \
  output_sample_rate:=44100 \
  capturer_device:=-1 \
  capturer_rate:=44100 \
  capturer_channels:=1 \
  capturer_chunk:=1024
```

Дефолт захвата в launch сделан максимально безопасным для большинства устройств: `capturer_device:=-1` (default input PortAudio) и `capturer_channels:=1` (mono). Если у вашего входа stereo, явно задайте `capturer_channels:=2`.

Только динамик (без микрофона):

```bash
ros2 launch rds_2p_audio audio.launch.py enable_capturer:=false
```
### Параметры launch (минимально нужные аргументы)

**Воспроизведение:** `output_topic`, `output_device` (−1 = default ALSA), **`pulse_sink`** (имя sink Pulse для `PULSE_SINK` у `audio_player`; пустая строка — не менять окружение), `output_channels`, `output_sample_rate`, плюс внутренние микшера `mix_period_ms`, `source_evict_sec`, `qos_depth`.

**Захват:** при `enable_capturer:=true` — `capturer_device`, `capturer_rate`, `capturer_channels`, `capturer_chunk`, необязательно `capturer_format` (чаще **8** = int16 как в `audio_common`), `capturer_topic`, `capturer_respawn`.

---

## Параметры ноды `audio_player`

| Parameter | По умолчанию | Описание |
|-----------|---------------|----------|
| `topic` | `/audio/output` | Подписка на шину |
| `device` | `−1` | Индекс PortAudio для выхода |
| `pulse_sink` | `""` | Если непустая строка — перед открытием потока выставить `PULSE_SINK` (маршрутизация default через Pulse); в `audio.launch.py` по умолчанию задан sink ES8388 для Orange Pi RDS |
| `channels` | `1` | Каналы динамика |
| `output_sample_rate` | `44100` | Договорная Fs |
| `mix_period_ms` | `20.0` | Длительность блока смешения (мс) |
| `source_evict_sec` | `5.0` | Эвикт источника без новых сообщений (с) |
| `qos_depth` | `50` | HISTORY depth BEST_EFFORT |

---

## Проверка

Микрофон (нужны запущенные `ros2 launch rds_2p_audio audio.launch.py` и `source install/setup.bash` из воркспейса):

```bash
python3 ~/RDS-2P-simulator/ros_packages/scripts/test_microphone.py --output record_mic.wav --duration 5
```

Утилита плеера (`audio_player` и `test_speaker` на `/audio/output` по умолчанию **BEST_EFFORT**):

```bash
python3 ~/RDS-2P-simulator/ros_packages/scripts/test_speaker.py --file ~/path/to/sample.wav \
  --sample-rate 44100 --source-id test_speaker
```

---

## Топики

- **`/audio/output`** — вход воспроизведения для `audio_player` (много издателей с разными `frame_id`).
- **`/audio/input`** — захват из `audio_capturer_node` при запуске с `enable_capturer:=true`.
- Очистка шума (**RNNoise**) в отдельном пакете [`audio_filters`](../audio_filters/README.md): топик **`/audio/input/clean`** (запуск `ros2 launch audio_filters rnnoise_filter.launch.py`; для Vosk: `audio_topic:=/audio/input/clean`).

---

## WSL2 / патчинг `audio_common`

Для некоторых окружений (WSL2 + PulseAudio) может понадобиться патч описанный у вас в истории README (задержка, float32 и т.д.). После патча пересборка:

```bash
colcon build --packages-select audio_common
```

Подставьте в `audio.launch.py` свои аргументы (`capturer_device`, `capturer_format`, больший `capturer_chunk`).

---

## Список устройств PortAudio

```bash
python3 -m sounddevice
```
