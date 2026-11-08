# audio_filters

Пакет **фильтрации аудио** для ROS 2 на `audio_common_msgs/AudioStamped`:

| Узел | Назначение |
|------|------------|
| **`audio_rnnoise_node`** | Шумоподавление через **[RNNoise](https://github.com/xiph/rnnoise)** (48 kHz, моно на выходе по текущей логике ноды). |
| **`audio_gain_node`** | Линейное усиление: топик А → топик Б, без SoXR/RNNoise; сохраняет формат PCM и число каналов. |

- RNNoise по умолчанию: **`/audio/input`** → **`/audio/input/clean`**.
- Усиление по умолчанию: **`/audio/input`** → **`/audio/input/boosted`** (`gain_linear`).

## Зависимости

- **`audio_common_msgs`**, **`rclcpp`**
- **`libsoxr`** — только для **`audio_rnnoise_node`** (ресемплинг ↔ 48 kHz)
- Инструменты сборки rnnoise из исходников: **autoconf**, **automake**, **libtool**, **make**, доступ в интернет для `autogen.sh` / `download_model.sh` при **первой** сборке (скачивается весовой архив модели).

## RNNoise и лицензии

- Код узла распространяется под **MIT** (этот репозиторий).
- **RNNoise**: [BSD-3-Clause](https://github.com/xiph/rnnoise/blob/main/COPYING). Выпускайте упоминание в документации продукта при необходимости.

## Сборка

**RNNoise** не собирается из CMake этого пакета. Его нужно один раз установить в префикс **`deps/rnnoise_install`** (от корня `ros_packages`): скриптами **`scripts/build_for_robot.sh`** или **`scripts/build_for_desktop.sh`** они клонируют **xiph/rnnoise v0.2**, подставляют заглушку `third_party/rnnoise/rnnoise_os_support_stub.h` как `src/os_support.h` в дереве rnnoise, выполняют autotools **`make install`**. Содержимое `deps/*` не коммитится (`.gitignore`); в репозитории есть **`deps/COLCON_IGNORE`**, чтобы **colcon** не заходила внутрь клона и не пыталась распознавать там пакеты.

Затем из корня workspace:

```bash
source /opt/ros/$ROS_DISTRO/setup.bash
colcon build --packages-select audio_filters
```

Если `librnnoise.a` или `rnnoise.h` не найдены, CMake сообщит ошибку и попросит сначала прогнать указанный build-скрипт.

## Запуск

Рядом с захватом микрофона (например `rds_2p_audio/audio.launch.py`):

```bash
source install/setup.bash
ros2 launch audio_filters rnnoise_filter.launch.py
```

Опционально переопределить топики и QoS см. аргументы в `launch/rnnoise_filter.launch.py`.

### Усиление (`audio_gain_node`)

Разные имена топиков задаются параметрами `input_topic` и `output_topic` (или через launch):

```bash
ros2 launch audio_filters audio_gain.launch.py
```

Пример явных топиков и коэффициента:

```bash
ros2 launch audio_filters audio_gain.launch.py \
  input_topic:=/audio/input/clean \
  output_topic:=/audio/input/boosted_clean \
  gain_linear:=3.0
```

Параметр **`gain_linear`** можно менять на лету: `ros2 param set /audio_gain gain_linear 1.5`.

**Замечание:** для форматов **int16**/int32/8-бит усилённые сэмплы **режутся по диапазону** формата; **float32** уходит без жёсткого клипа (осторожно с перегрузом дальше по цепочке).

### Vosk / STT

По умолчанию Vosk подписан на **`/audio/input`**. Чтобы использовать очищенный поток:

```bash
ros2 launch vosk_ros2 vosk.launch.py audio_topic:=/audio/input/clean
```

(или передайте тот же аргумент в ваш объединённый launch.)

## Замечания

- В DDS топики **`/audio/input`** и **`/audio/input/clean` не связаны иерархией** — это только соглашение имён.
- Задержка и нагрузка CPU: два прохода SoXR + кадры RNNoise; для встраиваемых плат допустимо снизить `output_chunk_frames`, если нужно меньше паковать сообщения.
