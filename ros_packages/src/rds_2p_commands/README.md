# rds_2p_commands

ROS2 пакет для обработки текстовых/голосовых команд (из топиков, в том числе от внешних источников вроде Telegram‑бота) с поддержкой CVC классификатора и универсального Action сервера.

## Быстрый старт

### 1. Получите токен Telegram бота

Откройте Telegram, найдите [@BotFather](https://t.me/BotFather), отправьте `/newbot` и следуйте инструкциям.

### 2. Запуск системы (без Telegram)

```bash
cd ~/RDS-2P-simulator/ros_packages
source install/setup.bash

ros2 launch rds_2p_commands command_parser.launch.py cvc_enabled:=false
ros2 launch rds_2p_commands unified_action_server.launch.py
```

### 3. Тестирование через топик (имитация голосовой команды):
```bash
ros2 topic pub /audio/transcription vosk_ros2/msg/Transcription \
  "{text: 'dance 1', audio_time: 1.5, transcription_time: 0.2}"
```

### 4. Запуск полной системы команд:
```bash
ros2 launch rds_2p_commands commands_system.launch.py cvc_enabled:=false
```

## Параметры launch файла

### Обязательные параметры

- `telegram_token` - токен Telegram бота от BotFather (обязательный, если используется Telegram)

### Опциональные параметры

**CVC классификатор:**
- `cvc_enabled` (default: `false`) - включить CVC классификатор
- `cvc_url` (default: `http://localhost:8000`) - URL CVC сервера
- `cvc_confidence_threshold` (default: `0.7`) - минимальный порог уверенности

**Telegram:**
- Авторизация обрабатывается в пакете `rds_2p_telegram_bot`, код генерируется там же

**Система:**
- `log_level` (default: `info`) - уровень логирования
- `allow_parallel_same_class` (default: `false`) - разрешить параллельное выполнение команд одного класса
- `transcription_topics` (default: `['/audio/transcription', '/telegram/audio/transcription']`) - список топиков транскрипции для подписки

## Примеры запуска

### Запуск Telegram бота (отдельный пакет `rds_2p_telegram_bot`)
```bash
ros2 launch rds_2p_telegram_bot telegram_bot.launch.py \
    telegram_token:='ВАШ_ТОКЕН' \
    commands_topic:='/commands' \
    code_timeout:=60.0 \
    menu_refresh_interval:=5.0 \
    audio_topic:='/telegram/audio' \
    audio_sample_rate:=16000 \
    auth_enabled:=false \
    log_level:=info
```

### Запуск с несколькими топиками транскрипции:
```bash
ros2 launch rds_2p_commands commands_system.launch.py \
    cvc_enabled:=false \
    transcription_topics:="['/audio/transcription', '/telegram/audio/transcription', '/my/custom/transcription']"
```

## ROS2 Топики

### Подписка:
- `/telegram/message` (`std_msgs/String`) — текстовые команды из Telegram
- `/audio/transcription` (`vosk_ros2/Transcription`) — транскрипции из микрофона (по умолчанию)
- `/telegram/audio/transcription` (`vosk_ros2/Transcription`) — транскрипции из Telegram (по умолчанию)
- Дополнительные топики транскрипции настраиваются через параметр `transcription_topics`

## Конфигурация команд

Команды настраиваются в `config/command_mappings.yaml`. Настройки CVC передаются через параметры launch файла, а не в YAML.

## Безопасность

- **Токен Telegram** передается через параметр launch файла, а не хранится в файлах конфигурации
- Используйте переменные окружения для токенов в production:
  ```bash
  export TELEGRAM_TOKEN='ваш_токен'
  ros2 launch rds_2p_telegram_bot telegram_bot.launch.py \
      telegram_token:=$(echo $TELEGRAM_TOKEN)
  ```

## Документация

- `COMMAND_CLASSES.md` - система классов команд для управления параллельным выполнением
- `config/command_mappings.yaml` - конфигурация команд
- `config/action_classes.yaml` - свойства классов команд (приоритет, таймаут, поведение)
