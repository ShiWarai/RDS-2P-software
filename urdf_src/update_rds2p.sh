#!/bin/bash

# Скрипт для обновления пакета rds_2p из экспортированных данных Blender
# Автоматизирует процесс: "отредактировал .blend -> экспортировал -> обновил пакет"

set -e  # Остановиться при ошибке

echo "🚀 Запуск обновления пакета rds_2p..."
echo "=================================="

# Проверяем, что мы в папке urdf
if [ ! -f "update_rds2p_package.py" ]; then
    echo "❌ Ошибка: Скрипт должен запускаться из папки urdf"
    echo "   Текущая директория: $(pwd)"
    exit 1
fi

# Проверяем наличие Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Ошибка: Python3 не найден"
    exit 1
fi

# Запускаем Python скрипт
echo "📝 Запускаю Python скрипт обновления..."
python3 update_rds2p_package.py

# Проверяем результат
if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 Обновление завершено успешно!"
    echo ""
    echo "📋 Что было сделано:"
    echo "   ✓ Скопированы меши из export/meshes в пакет"
    echo "   ✓ Обновлен базовый URDF файл"
    echo "   ✓ Создан ROS URDF с ROS2 control конфигурацией"
    echo "   ✓ Обновлены wrapper файлы"
    echo ""
    echo "🔨 Теперь можно собрать пакет:"
    echo "   colcon build --packages-select rds_2p"
    echo ""
    echo "📁 Проверить изменения можно в:"
    echo "   ros_packages/src/rds_2p/urdf/"
    echo "   ros_packages/src/rds_2p/meshes/"
else
    echo ""
    echo "❌ Обновление завершилось с ошибкой"
    exit 1
fi
