# gigaam_ros
Пакет ROS 2 для запуска STT-ноды на основе **GigaAM CTC** (RKNN, RK3588 NPU).

## Описание
Зеркалит `vosk_ros`: та же структура, те же интерфейсы (`Transcription.msg`,
`GrammarConfig.msg`, `STT.action`), те же топики и способ загрузки модели
(параметр `model_path`). Движок — модель
[ShiWarai/gigaam-ctc-rknn](https://huggingface.co/ShiWarai/gigaam-ctc-rknn)
(Conformer CTC, ru/kk/ky/uz/en) поверх `librknnrt` 2.3.2 через ctypes (dlopen).

### Отличия от Vosk
- **NPU**: инференс идёт на NPU RK3588 (large int8 ≈ 157 мс/окно), не на CPU.
- **Не потоковый**: статичное окно 500 log-mel фреймов (≈5.02 с @16 кГц). Длинная
  фраза режется на окна ≤500 фреймов, каждое — по NPU, схлопнутые CTC-id склеиваются.
- **Нет грамматики/endpointing'а модели**: сегментацию речи делает `vad_node`.

## Зависимости
- Python: `numpy<=1.26.4` (совместимость с rknn-toolkit2 2.3.2), `torch==2.2.0`, `torchaudio==2.2.0`
  (лог-мел фронтенд, **CPU-колёса**; CPU-индекс прописан в `requirements.txt`,
  CUDA/nvidia-* не скачиваются), `sherpa-onnx` (VAD backend=cpu).
- Системно: `librknnrt.so` 2.3.2 — **уже стоит в системе** (`/usr/lib/librknnrt.so`, тот же,
  что вендорит `rkllm_ros`). Нода грузит его по имени (`rknn_lib` пусто → `librknnrt.so`);
  альтернативу задают параметром `rknn_lib` или `RKNN_LIB`.
- ROS 2: `rclpy`, `std_msgs`, `audio_common_msgs`, `rosidl_default_generators`, `vosk_ros`
  (общий топик `/audio/transcription` несёт `vosk_ros/msg/Transcription`).

### Тип на общем топике
В стеке `/audio/transcription` — это `vosk_ros/msg/Transcription` (его слушают `llm_layer`,
`command_parser`, `telegram_bot`). `gigaam_node` по умолчанию публикует **тот же тип** (auto-detect;
fallback на собственный `gigaam_ros/msg/Transcription`, если `vosk_ros` нет). Поэтому gigaam
вставляется на место vosk без правок в downstream.

## Установка
```bash
cd ~/ros2_ws/src
# пакет лежит в ros_packages/src/gigaam_ros
pip3 install -r src/gigaam_ros/requirements.txt
colcon build --packages-select gigaam_ros
source install/setup.bash
```

## Модели (не в репозитории)
```bash
cd src/gigaam_ros/models
wget -O gigaam-ctc-large-int8-seq500.rknn \
  "https://huggingface.co/ShiWarai/gigaam-ctc-rknn/resolve/main/gigaam-ctc-large-int8-seq500.rknn"
wget -O multilingual_vocab.txt \
  "https://huggingface.co/ShiWarai/gigaam-ctc-rknn/resolve/main/multilingual_vocab.txt"
wget -O silero_vad.onnx \
  "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
```
md5 large int8 (сверка): `e798642469f9c5aa09944077f98023a9`.
Либо путь через `model_path` (каталог с `.rknn` + `multilingual_vocab.txt` или сам `.rknn`).

## Запуск
```bash
# Терминал 1: захват аудио (audio_capturer → /audio/input)
ros2 launch rds_2p audio_nodes.launch.py

# Терминал 2: VAD (только речь)
ros2 launch gigaam_ros vad.launch.py

# Терминал 3: распознавание (слушает выход VAD)
ros2 launch gigaam_ros gigaam.launch.py audio_topic:=/audio/vad
```

### В общем голосовом контуре RDS-2P
```bash
# STT=GigaAM вместо Vosk (микрофон напрямую, reliable_audio=false)
ros2 launch rds_2p voice_system.launch.py stt:=gigaam

# В llm_layer; для VAD дополнительно включите gigaam_reliable_audio
ros2 launch rds_2p llm_layer.launch.py stt:=gigaam
ros2 launch rds_2p llm_layer.launch.py stt:=gigaam vad_enabled:=true \
  vosk_audio_topic:=/audio/vad gigaam_reliable_audio:=true
```

## Проверено (RK3588, ROS 2 Humble, domain 1)
Живой тракт `audio_capturer(/audio/input) → vad_node → gigaam_node → /audio/transcription`
при параллельно работающем `paroli_ros`. `ros2 topic pub --once /speak_text std_msgs/msg/String
"{data: 'привет как дела'}"` → робот произносит → микрофон слышит самоэхо →
распознано (`…как дело`, вторая фраза «ты меня слышишь» — точно). `librknnrt` из `/usr/lib`.
Начало фразы иногда срезано порогом VAD — при необходимости поднимите `preroll_sec`
(`vad.launch.py preroll_sec:=0.5`).

## Параметры gigaam_node
| Параметр | Смысл |
|---|---|
| `model_path` | каталог модели (`.rknn` + vocab) или путь к `.rknn` (по умолчанию `share/gigaam_ros/models`) |
| `model_file` | имя `.rknn` внутри каталога (пусто — первая найденная) |
| `vocab_path` | `multilingual_vocab.txt` (пусто — рядом с `.rknn`) |
| `rknn_lib` | путь к `librknnrt.so` (пусто — `RKNN_LIB` или системная) |
| `audio_topic` | вход аудио (по умолчанию `/audio/input`; с VAD — `/audio/vad`) |
| `transcription_topic` | топик результатов (по умолчанию `/audio/transcription`) |
| `max_audio_time` | макс. длительность фразы, с (30.0) |

## VAD (`vad_node`)
Пропускает в распознавание только речь (Silero VAD v4). Отдаёт **фразу целиком**
одним сообщением (+ хвост тишины). Бэкенд `backend`:

| backend | модель | статус |
|---|---|---|
| `cpu` (default) | `silero_vad.onnx` через `sherpa-onnx` | проверен, out-of-box |
| `npu` | `silero_vad*.rknn` через `librknnrt` (rknn_engine.SileroVadRknn) | экспериментально: нужен ваш статичный экспорт Silero в .rknn |

```bash
ros2 launch gigaam_ros vad.launch.py backend:=cpu
ros2 launch gigaam_ros vad.launch.py backend:=npu vad_rknn_path:=/path/silero_vad.rknn
```
При `backend=npu` нода логирует имена/формы входных/выходных тензоров — по ним
подгоняется соответствие экспорт-контракту Silero (окно `[1,512]`@16кГц + h/c →
вероятность речи + состояния).

## Сообщения / действия
- `gigaam_ros/msg/Transcription` — `text`, `audio_time`, `transcription_time`
- `gigaam_ros/msg/GrammarConfig` — заглушка совместимости (CTC её игнорирует)
- `gigaam_ros/action/STT` — действие `listen` (для совместимого интерфейса)

## Фразы длиннее окна модели (>5 с)
GigaAM — оконный CTC (500 mel-фреймов ≈ 5.02 с). `gigaam_node` сам режет длинную
фразу на окна ≤500 фреймов и склеивает CTC-id (офлайн-проверка: 8 с → 2 окна,
13 с → 3). Чтобы фраза вообще доходила целиком, `vad_node` отдаёт её **одним**
склеенным `AudioStamped` — это сотни КБ / сотни UDP-фрагментов. Поэтому приватный
топик `vad → gigaam` (`/audio/vad`) по умолчанию **RELIABLE**: на best-effort потеря
любого фрагмента роняла сообщение целиком, и фразы >5 с «не определялись». Вход с
микрофона (`/audio/input`) остаётся best-effort. Переключатели: `output_reliable`
(vad) и `reliable_audio` (gigaam). Для прямого подключения gigaam к микрофону
(без VAD) поставь `reliable_audio:=false`.

## Лицензия
MIT. Веса GigaAM — MIT (salute-developers/GigaAM); фронтенд/раннер портированы из
ShiWarai/gigaam-ctc-rknn (MIT).
