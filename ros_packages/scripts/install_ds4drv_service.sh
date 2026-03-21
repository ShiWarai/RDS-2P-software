#!/bin/bash
# Скрипт для установки systemd сервиса ds4drv

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/ds4drv.service"
SYSTEMD_DIR="/etc/systemd/system"
TARGET_SERVICE="$SYSTEMD_DIR/ds4drv.service"

echo "Установка systemd сервиса для ds4drv..."

# Проверка прав root
if [ "$EUID" -ne 0 ]; then 
    echo "Ошибка: этот скрипт должен быть запущен с правами root (sudo)"
    exit 1
fi

# Проверка существования ds4drv
if ! command -v ds4drv &> /dev/null; then
    echo "Предупреждение: ds4drv не найден в PATH"
    echo "Убедитесь, что ds4drv установлен и доступен по пути /usr/local/bin/ds4drv"
    echo "Или отредактируйте путь в файле сервиса после установки"
fi

# Копирование файла сервиса
if [ -f "$SERVICE_FILE" ]; then
    cp "$SERVICE_FILE" "$TARGET_SERVICE"
    echo "Файл сервиса скопирован в $TARGET_SERVICE"
else
    echo "Ошибка: файл сервиса не найден: $SERVICE_FILE"
    exit 1
fi

# Перезагрузка systemd
systemctl daemon-reload
echo "Конфигурация systemd перезагружена"

# Включение автозапуска
systemctl enable ds4drv.service
echo "Сервис включен для автозапуска"

# Запуск сервиса
read -p "Запустить сервис сейчас? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    systemctl start ds4drv.service
    echo "Сервис запущен"
    
    # Проверка статуса
    sleep 2
    systemctl status ds4drv.service --no-pager
fi

echo ""
echo "Установка завершена!"
echo ""
echo "Полезные команды:"
echo "  sudo systemctl start ds4drv    - Запустить сервис"
echo "  sudo systemctl stop ds4drv     - Остановить сервис"
echo "  sudo systemctl status ds4drv   - Проверить статус"
echo "  sudo systemctl enable ds4drv   - Включить автозапуск"
echo "  sudo systemctl disable ds4drv  - Выключить автозапуск"
echo "  sudo journalctl -u ds4drv -f   - Просмотр логов в реальном времени"

