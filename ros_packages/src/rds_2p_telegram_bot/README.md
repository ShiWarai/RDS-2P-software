# rds_2p_telegram_bot

ROS2 пакет с Telegram‑ботом, который служит прослойкой между Telegram и ROS2 топиками.

## Возможности

- Авторизация через 4-значный код (код генерируется в боте и логируется)
- Динамическое меню команд с inline кнопками
- Обработка текстовых команд
- Обработка голосовых сообщений с автоматической расшифровкой
- Отправка транскрипций пользователю в реальном времени

## Запуск
```bash
cd ~/RDS-2P-simulator/ros_packages
source install/setup.bash

ros2 launch rds_2p_telegram_bot telegram_bot.launch.py \
  telegram_token:='ВАШ_ТОКЕН' \
  commands_topic:='/commands' \
  code_timeout:=60.0 \
  menu_refresh_interval:=5.0 \
  audio_topic:='/telegram/audio' \
  audio_sample_rate:=16000 \
  auth_enabled:=true \
  log_level:=info
```

Параметры:
- `telegram_token` — обязательный токен BotFather.
- `commands_topic` — топик, где action‑серверы публикуют доступные команды (по умолчанию `/commands`).
- `telegram_whitelist` — список разрешённых chat_id через запятую (по умолчанию пусто, требует авторизацию кодом).
- `code_timeout` — время жизни 4‑значного кода (сек, по умолчанию 60.0).
- `menu_refresh_interval` — интервал обновления меню (сек, по умолчанию 5.0).
- `audio_topic` — топик для публикации голосовых сообщений (по умолчанию `/telegram/audio`).
- `audio_sample_rate` — частота дискретизации аудио (по умолчанию 16000 Hz).
- `auth_enabled` — включить авторизацию (по умолчанию `true`, установите `false` для тестирования).
- `log_level` — уровень логов (`debug`, `info`, `warn`, `error`).

## ROS2 Топики

### Публикация:
- `/telegram/message` (`std_msgs/String`) — текстовые команды от пользователей
- `/telegram/audio` (`audio_common_msgs/AudioStamped`) — голосовые сообщения в формате аудио

### Подписка:
- `/commands` (`std_msgs/String`) — список доступных команд от action серверов
- `/telegram/audio/transcription` (`vosk_ros2/Transcription`) — транскрипции голосовых сообщений от vosk

## Работа с голосовыми сообщениями

1. Пользователь отправляет голосовое сообщение в Telegram
2. Бот конвертирует OGG Opus в формат ROS2 и публикует в `/telegram/audio`
3. Vosk распознает речь и публикует транскрипцию в `/telegram/audio/transcription`
4. Бот автоматически отправляет расшифровку пользователю, заменяя сообщение "Обрабатываю..."

**Требования:**
- Запущен `vosk_ros2` с подпиской на `/telegram/audio`:
  ```bash
  ros2 launch vosk_ros2 vosk_telegram.launch.py
  ```

## Зависимости (Python)
Установлены через пакет:
- aiogram>=3.0.0
- soundfile
- numpy>=1.20.0
- scipy>=1.7.0

## Авторизация

Бот поддерживает два режима авторизации:

1. **Через whitelist** — если указан `telegram_whitelist`, пользователи из списка имеют доступ без кода
2. **Через код** — если whitelist пуст, пользователь должен ввести 4-значный код

**Процесс авторизации через код:**
1. Пользователь отправляет `/start`
2. Бот генерирует случайный 4-значный код
3. Код логируется в логах бота: `КОД АВТОРИЗАЦИИ ДЛЯ TELEGRAM (chat_id: XXX): XXXX`
4. Пользователь вводит код в боте
5. Бот проверяет код и авторизует пользователя

**Отключение авторизации:**
Для тестирования можно отключить авторизацию:
```bash
ros2 launch rds_2p_telegram_bot telegram_bot.launch.py \
  telegram_token:='ВАШ_ТОКЕН' \
  auth_enabled:=false
```

## Примечание
Обработка команд и action‑сервера находятся в отдельном пакете `rds_2p_commands`. Этот бот только принимает/авторизует пользователей, показывает меню и публикует команды/аудио в топики ROS2.

