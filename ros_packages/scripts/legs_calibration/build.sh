#!/bin/bash

# Скрипт сборки калибратора сервоприводов

set -e  # Выход при ошибке

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "   Сборка калибратора сервоприводов"
echo "=========================================="
echo ""

# Проверяем наличие FTServoLibrary
if [ ! -d "lib/FTServoLibrary" ]; then
    echo "⚠️  FTServoLibrary не найдена!"
    echo "📦 Клонирование FTServoLibrary..."
    mkdir -p lib
    cd lib
    git clone https://github.com/ShiWarai/FTServoLibrary.git
    cd ..
fi

# Создаём директорию для сборки
if [ -d "build" ]; then
    echo "🧹 Очистка старой сборки..."
    rm -rf build
fi

mkdir -p build
cd build

# Запускаем CMake
echo ""
echo "⚙️  Конфигурация проекта с помощью CMake..."
cmake -DCMAKE_BUILD_TYPE=Release ..

# Собираем проект
echo ""
echo "🔨 Сборка проекта..."
make -j$(nproc)

echo ""
echo "=========================================="
echo "   ✅ Сборка завершена успешно!"
echo "=========================================="
echo ""
echo "📍 Исполняемый файл: $SCRIPT_DIR/build/servo_calibration"
echo ""
echo "📖 Использование:"
echo "   Калибровка начальных позиций:"
echo "     ./build/servo_calibration initial --servos 1,2,3"
echo ""
echo "   Калибровка пределов (умный режим):"
echo "     ./build/servo_calibration limits --servos 1,2,3"
echo ""
echo "   Для другой ноги (сервоприводы 4,5,6):"
echo "     ./build/servo_calibration initial --servos 4,5,6"
echo "     ./build/servo_calibration limits --servos 4,5,6"
echo ""
