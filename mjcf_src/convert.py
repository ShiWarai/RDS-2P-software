#!/usr/bin/env python3
"""
Простой скрипт для конвертации URDF в MJCF.
Использует новую объектно-ориентированную архитектуру.
"""

import sys
import os

# Добавляем текущую директорию в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.urdf_to_mjcf_converter import URDFToMJCFConverter


def main():
    """Основная функция."""
    try:
        print("🤖 URDF to MJCF Converter")
        print("=" * 40)
        
        # Создаем конвертер
        converter = URDFToMJCFConverter()
        
        # Выполняем конвертацию
        mjcf_path = converter.convert()
        
        print(f"\n✅ Конвертация завершена!")
        print(f"📄 Результат: {os.path.abspath(mjcf_path)}")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n⚠ Прерывание пользователем")
        return 130
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
