# rds_2p_audio

Пакет с launch файлами для работы с аудио в RDS-2P.

## Launch файлы

### audio_nodes.launch.py
Запускает узлы захвата и воспроизведения аудио (`audio_capturer_node` и `audio_player_node`).

**Использование:**
```bash
ros2 launch rds_2p_audio audio_nodes.launch.py
```

**Параметры:**
- `capturer_device` - индекс устройства для захвата (по умолчанию: 7 для робота, для desktop/WSL2 используйте 0)
- `capturer_rate` - частота дискретизации (по умолчанию: 48000, для desktop можно использовать 44100)
- `capturer_channels` - количество каналов (по умолчанию: 1, **для WSL2 рекомендуется 2**)
- `capturer_format` - формат аудио (по умолчанию: 8 = paInt16)
- `capturer_chunk` - размер буфера (по умолчанию: 512, **для WSL2 рекомендуется 4096**)
- `capturer_topic` - топик для публикации аудио (по умолчанию: `/audio/input`)
- `player_device` - индекс устройства для воспроизведения (по умолчанию: 2)
- `player_topic` - топик для подписки на аудио (по умолчанию: `/audio/output`)

**Пример для desktop/WSL2:**
```bash
ros2 launch rds_2p_audio audio_nodes.launch.py \
    capturer_device:=0 \
    capturer_rate:=44100 \
    capturer_channels:=2 \
    capturer_chunk:=4096
```

## Работа в WSL2

### ⚠️ Важно: Патчинг пакета audio_common

Пакет `audio_common` требует патчинга для корректной работы в WSL2. Без этих изменений микрофон не будет захватывать звук.

#### Необходимые изменения в `audio_common`

Файл: `ros_packages/src/audio_common/audio_common/src/audio_common/audio_capturer_node.cpp`

**1. Изменить задержку (строка ~24):**
```cpp
// Было:
inputParameters.suggestedLatency = Pa_GetDeviceInfo(inputParameters.device)->defaultLowInputLatency;

// Должно быть:
inputParameters.suggestedLatency = 0.1; // Стабильная задержка для WSL2
```

**2. Принудительно использовать paFloat32 (строка ~23):**
```cpp
// Было:
inputParameters.sampleFormat = this->format_;

// Должно быть:
inputParameters.sampleFormat = paFloat32; // Принудительно для WSL2
```

**3. Увеличить размер чанка по умолчанию (строка ~9):**
```cpp
// Было:
this->declare_parameter<int>("chunk", 512);

// Должно быть:
this->declare_parameter<int>("chunk", 4096); // Для WSL2
```

**4. Обновить callback для использования paFloat32 (строки ~46-63):**

В функции `paCallback` заменить switch-case на принудительное использование `float32_data`:

```cpp
int AudioCapturerNode::paCallback(const void *inputBuffer, void *outputBuffer,
                                  unsigned long framesPerBuffer,
                                  const PaStreamCallbackTimeInfo *timeInfo,
                                  PaStreamCallbackFlags statusFlags, void *userData) {
  AudioCapturerNode *node = static_cast<AudioCapturerNode *>(userData);
  (void)outputBuffer; (void)timeInfo; (void)statusFlags;

  audio_common_msgs::msg::AudioStamped msg;
  msg.header.stamp = node->now();
  msg.audio.audio_data.float32_data.assign((const float*)inputBuffer, (const float*)inputBuffer + framesPerBuffer * node->get_channels());
  msg.audio.info.format = 1; // paFloat32
  msg.audio.info.channels = node->get_channels();
  msg.audio.info.chunk = framesPerBuffer;
  msg.audio.info.rate = node->get_rate();

  node->publish_audio(msg);
  return paContinue;
}
```

**5. Добавить геттеры в заголовочный файл:**

Файл: `ros_packages/src/audio_common/audio_common/include/audio_common/audio_capturer_node.hpp`

Добавить в публичную секцию класса:
```cpp
int get_channels() const { return channels_; }
int get_format() const { return format_; }
```

#### После внесения изменений

Пересоберите пакет:
```bash
cd ros_packages
colcon build --packages-select audio_common
source install/setup.bash
```

#### Использование после патчинга

1. Установите PulseAudio в WSL2 и Windows (инструкции внутри `scripts/test_microphone_desktop.py`).
2. Используйте устройство `1` (стандартное для PulseAudio в WSL2).
3. Используйте формат `1` (`paFloat32`).

Пример запуска:
```bash
ros2 launch rds_2p_audio audio_nodes.launch.py \
    capturer_device:=1 \
    capturer_rate:=44100 \
    capturer_format:=1 \
    capturer_chunk:=4096
```

#### Почему нужны эти изменения?

- **Задержка 0.1с**: В WSL2 через PulseAudio требуется большая задержка для стабильного наполнения буфера. При чанке 4096 и частоте 44100 Гц один пакет собирается ~92мс, поэтому 100мс — минимальное стабильное значение.
- **paFloat32**: PulseAudio в WSL2 лучше работает с форматом float32, чем с int16.
- **Чанк 4096**: Увеличенный размер буфера снижает риск переполнения при работе через сетевой мост PulseAudio.

## Использование с vosk_ros2

Для распознавания речи запустите vosk_ros2 отдельно после запуска audio_nodes:

```bash
# Терминал 1: Запуск захвата аудио
ros2 launch rds_2p_audio audio_nodes.launch.py capturer_device:=0 capturer_rate:=44100

# Терминал 2: Запуск распознавания речи
ros2 launch vosk_ros2 vosk.launch.py

# Терминал 3: Просмотр результатов
ros2 topic echo /audio/transcription
```

## Топики

### Входные топики
- `/audio/input` (`audio_common_msgs/msg/AudioStamped`) - аудио данные от микрофона

### Выходные топики
- `/audio/output` (`audio_common_msgs/msg/AudioStamped`) - аудио данные для воспроизведения

## Настройка для WSL2

Для работы микрофона в WSL2 необходимо настроить аудио. Подробные инструкции см. в комментариях в файле `test_microphone_desktop.py`.

Кратко:
1. Установите PulseAudio в WSL2: `sudo apt-get install pulseaudio pulseaudio-utils`
2. Настройте конфигурацию PulseAudio
3. Установите PulseAudio в Windows или используйте WSL Audio
4. Перезапустите WSL2

## Проверка устройств

Для проверки доступных аудио устройств используйте:

```bash
python3 ros_packages/scripts/test_microphone_desktop.py --list-devices
```

