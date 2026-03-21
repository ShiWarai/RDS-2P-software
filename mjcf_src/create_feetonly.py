#!/usr/bin/env python3
"""
Скрипт для создания MJCF файла только со стопами.
Берет готовый MJCF файл и удаляет все коллизии, кроме стоп.
"""

import sys
import os
import xml.etree.ElementTree as ET
from typing import List, Set

# Добавляем текущую директорию в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config_manager import ConfigurationManager


class FeetOnlyProcessor:
    """Класс для обработки MJCF файла и создания версии только со стопами."""
    
    def __init__(self, config_dir: str = "configs"):
        """
        Инициализация процессора.
        
        Args:
            config_dir: Путь к директории с конфигурационными файлами
        """
        self.config_manager = ConfigurationManager(config_dir)
        self.config = None
        self.paths = None
        self.feet_bodies = set()
        
    def process(self) -> str:
        """
        Выполняет обработку MJCF файла.
        
        Returns:
            Путь к созданному MJCF файлу только со стопами
        """
        print("=== СОЗДАНИЕ MJCF ФАЙЛА ТОЛЬКО СО СТОПАМИ ===")
        
        try:
            # Загружаем конфигурацию
            self._load_config()
            
            # Загружаем исходный MJCF файл
            root = self._load_mjcf_file()
            
            # Находим тела стоп
            self._find_feet_bodies(root)
            
            # Удаляем все коллизии кроме стоп
            self._remove_non_feet_collisions(root)
            
            # Сохраняем результат
            output_path = self._save_processed_mjcf(root)
            
            print(f"\nОбработка завершена!")
            print(f"Результат: {os.path.abspath(output_path)}")
            
            return output_path
            
        except Exception as e:
            print(f"\nОшибка: {e}")
            raise
    
    def _load_config(self) -> None:
        """Загружает конфигурацию."""
        print("Загрузка конфигурации...")
        
        # Загружаем конфигурацию экспорта
        self.config_manager._load_export_config()
        self.config = self.config_manager.export_config
        
        if not self.config or 'paths' not in self.config or 'output_mjcf_feet_only' not in self.config['paths']:
            raise ValueError("Конфигурация output_mjcf_feet_only не найдена в export_config.yml")
        
        # Получаем пути из основной конфигурации
        self.paths = self.config_manager.get_paths()
        
        print("Конфигурация загружена")
    
    def _load_mjcf_file(self) -> ET.Element:
        """Загружает исходный MJCF файл."""
        input_path = self.paths['output_mjcf']  # Используем путь из основной конфигурации
        
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Исходный MJCF файл не найден: {input_path}")
        
        print(f"Загрузка MJCF файла: {input_path}")
        
        tree = ET.parse(input_path)
        root = tree.getroot()
        
        if root.tag != 'mujoco':
            raise ValueError(f"Некорректный MJCF файл. Ожидается корневой элемент 'mujoco', получен '{root.tag}'")
        
        print("MJCF файл загружен успешно")
        return root
    
    def _find_feet_bodies(self, root: ET.Element) -> None:
        """Находит коллизионные геометрии стоп в MJCF файле."""
        print("Поиск коллизионных геометрий стоп...")
        
        # Ищем все коллизионные геометрии, которые могут быть стопами
        # Обычно стопы имеют названия содержащие 'foot', 'toe', 'heel' и т.д.
        foot_keywords = ['foot', 'toe', 'heel', 'sole', 'pad']
        
        # Ищем коллизионные геометрии во всех телах
        for body in root.findall('.//body'):
            for geom in body.findall('geom'):
                if geom.get('class') == 'collision':  # Это коллизионная геометрия
                    geom_name = geom.get('name', '')
                    if any(keyword in geom_name.lower() for keyword in foot_keywords):
                        self.feet_bodies.add(geom_name)
                        print(f"  Найдена коллизия стопы: {geom_name}")
        
        if not self.feet_bodies:
            print("Предупреждение: Коллизионные геометрии стоп не найдены")
        else:
            print(f"Найдено {len(self.feet_bodies)} коллизионных геометрий стоп")
    
    def _remove_non_feet_collisions(self, root: ET.Element) -> None:
        """Удаляет все коллизии кроме стоп."""
        print("Удаление коллизий кроме стоп...")
        
        removed_count = 0
        
        # Проходим по всем телам и удаляем коллизионные geom элементы, которые не являются стопами
        for body in root.findall('.//body'):
            geoms = body.findall('geom')
            for geom in geoms:
                # Удаляем только коллизионные геометрии (class == 'collision')
                if geom.get('class') == 'collision':
                    geom_name = geom.get('name', '')
                    # Если это не коллизия стопы, удаляем её
                    if geom_name not in self.feet_bodies:
                        body.remove(geom)
                        removed_count += 1
        
        # Также удаляем geom элементы из default секций, которые не относятся к стопам
        for default in root.findall('.//default'):
            geoms = default.findall('geom')
            for geom in geoms:
                if geom.get('class') == 'collision':
                    default.remove(geom)
                    removed_count += 1
        
        print(f"Удалено {removed_count} коллизионных геометрий")
    
    def _save_processed_mjcf(self, root: ET.Element) -> str:
        """Сохраняет обработанный MJCF файл."""
        output_path = self.paths['output_mjcf_feet_only']
        
        # Создаем выходную директорию
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        print(f"Сохранение результата: {output_path}")
        
        # Форматируем и сохраняем XML
        self._format_xml(root)
        tree = ET.ElementTree(root)
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        
        return output_path
    
    def _format_xml(self, root: ET.Element) -> None:
        """Форматирует XML для лучшей читаемости."""
        # Простое форматирование - добавляем отступы
        def indent(elem, level=0):
            i = "\n" + level * "  "
            if len(elem):
                if not elem.text or not elem.text.strip():
                    elem.text = i + "  "
                if not elem.tail or not elem.tail.strip():
                    elem.tail = i
                for child in elem:
                    indent(child, level + 1)
                if not child.tail or not child.tail.strip():
                    child.tail = i
            else:
                if level and (not elem.tail or not elem.tail.strip()):
                    elem.tail = i
        
        indent(root)


def main():
    """Основная функция."""
    try:
        print("MJCF Feet Only Processor")
        print("=" * 40)
        
        # Создаем процессор
        processor = FeetOnlyProcessor()
        
        # Выполняем обработку
        output_path = processor.process()
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\nПрерывание пользователем")
        return 130
    except Exception as e:
        print(f"\nОшибка: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
