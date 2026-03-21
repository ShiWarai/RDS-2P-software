#!/usr/bin/env python3
"""
Основной класс для конвертации URDF в MJCF.
Координирует работу всех компонентов системы конвертации.
"""

import os
from typing import Dict, Any, Optional
from urdf2mjcf.convert import convert_urdf_to_mjcf

from .config_manager import ConfigurationManager
from processors.urdf_preprocessor import URDFPreprocessor
from processors.mjcf_postprocessor import MJCFPostprocessor


class URDFToMJCFConverter:
    """Основной класс для конвертации URDF в MJCF."""
    
    def __init__(self, config_dir: str = "configs"):
        """
        Инициализация конвертера.
        
        Args:
            config_dir: Путь к директории с конфигурационными файлами
        """
        self.config_dir = config_dir
        self.config_manager = ConfigurationManager(config_dir)
        self.urdf_preprocessor = None
        self.mjcf_postprocessor = None
        self.paths = None
        self.configs = None
        
        print("URDFToMJCFConverter инициализирован")
        print(f"Директория конфигураций: {os.path.abspath(config_dir)}")
    
    def convert(self, urdf_home: str = None) -> str:
        """
        Выполняет полную конвертацию URDF в MJCF.
        
        Args:
            urdf_home: Путь к директории с URDF файлами (опционально)
            
        Returns:
            Путь к созданному MJCF файлу
        """
        print("=== НАЧАЛО КОНВЕРТАЦИИ URDF → MJCF ===")
        
        try:
            # Этап 1: Загрузка конфигураций
            self._load_configurations(urdf_home)
            
            # Этап 2: Препроцессинг URDF
            urdf_file_path = self._preprocess_urdf()
            
            # Этап 3: Базовая конвертация
            mjcf_path = self._convert_urdf_to_mjcf(urdf_file_path)
            
            # Этап 4: Постобработка MJCF
            self._postprocess_mjcf(mjcf_path, urdf_file_path)
            
            print("=== КОНВЕРТАЦИЯ ЗАВЕРШЕНА УСПЕШНО ===")
            print(f"Результат: {os.path.abspath(mjcf_path)}")
            
            return mjcf_path
            
        except Exception as e:
            print(f"Ошибка конвертации: {e}")
            raise
        finally:
            # Этап 5: Очистка
            self._cleanup()
    
    def _load_configurations(self, urdf_home: str = None) -> None:
        """Загружает все конфигурации."""
        print("Этап 1: Загрузка конфигураций...")
        
        # Получаем пути сначала
        self.paths = self.config_manager.get_paths()
        
        # Если передан urdf_home, используем его, иначе берем из конфигурации
        if urdf_home:
            self.paths['urdf_home'] = urdf_home
        
        # Загружаем все конфигурации с правильным urdf_home
        self.configs = self.config_manager.load_all_configs(self.paths['urdf_home'])
        
        print("Конфигурации загружены")
        print(f"  URDF_HOME: {os.path.abspath(self.paths['urdf_home'])}")
        print(f"  OUTPUT_PATH: {os.path.abspath(self.paths['output_path'])}")
        print(f"  URDF_HOME существует: {os.path.exists(self.paths['urdf_home'])}")
    
    def _preprocess_urdf(self) -> str:
        """Выполняет препроцессинг URDF файла."""
        print("Этап 2: Препроцессинг URDF...")
        
        # Инициализируем препроцессор
        self.urdf_preprocessor = URDFPreprocessor(self.paths)
        
        # Выполняем препроцессинг
        urdf_file_path = self.urdf_preprocessor.prepare_urdf()
        
        print(f"Препроцессинг URDF завершен: {urdf_file_path}")
        return urdf_file_path
    
    def _convert_urdf_to_mjcf(self, urdf_file_path: str) -> str:
        """Выполняет базовую конвертацию URDF в MJCF."""
        print("Этап 3: Базовая конвертация URDF → MJCF...")
        
        mjcf_path = self.paths['output_path']
        print(f"Запуск конвертации с метаданными в {mjcf_path}...")
        
        # Создаем объект ConversionMetadata если есть метаданные
        conversion_metadata = self.config_manager.get_conversion_metadata()
        
        # Запускаем конвертацию с использованием библиотеки urdf2mjcf
        convert_urdf_to_mjcf(
            urdf_path=urdf_file_path,
            mjcf_path=mjcf_path,
            copy_meshes=True,
            metadata=conversion_metadata,
            joint_metadata=self.configs['joint_metadata'],
            actuator_metadata=self.configs['actuator_metadata'],
        )
        
        print(f"Базовая конвертация завершена: {mjcf_path}")
        return mjcf_path
    
    def _postprocess_mjcf(self, mjcf_path: str, urdf_file_path: str) -> None:
        """Выполняет постобработку MJCF файла."""
        print("Этап 4: Постобработка MJCF...")
        
        # Инициализируем постпроцессор с keyframes
        mjcf_config = self.configs['mjcf_extension'].copy()
        mjcf_config['keyframes'] = self.configs['keyframes']
        self.mjcf_postprocessor = MJCFPostprocessor(mjcf_config)
        
        # Выполняем постобработку
        self.mjcf_postprocessor.postprocess_mjcf(
            mjcf_path=mjcf_path,
            urdf_path=urdf_file_path,
            joint_limits=self.configs['joint_limits'],
            actuator_metadata=self.configs['default_actuator']
        )
        
        print("Постобработка MJCF завершена")
    
    def _cleanup(self) -> None:
        """Очищает временные файлы."""
        print("Этап 5: Очистка...")
        
        if self.urdf_preprocessor:
            self.urdf_preprocessor.cleanup()
        
        print("Очистка завершена")
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """
        Возвращает краткую сводку о загруженных конфигурациях.
        
        Returns:
            Словарь с информацией о конфигурациях
        """
        if not self.configs:
            return {"error": "Конфигурации не загружены"}
        
        summary = {
            "paths": self.paths,
            "metadata_loaded": self.configs['metadata'] is not None,
            "joint_metadata_count": len(self.configs['joint_metadata']) if self.configs['joint_metadata'] else 0,
            "actuator_metadata_loaded": self.configs['actuator_metadata'] is not None,
            "mjcf_extension_loaded": self.configs['mjcf_extension'] is not None,
            "keyframes_count": len(self.configs['keyframes']) if self.configs['keyframes'] else 0,
            "joint_limits_loaded": self.configs['joint_limits'] is not None
        }
        
        return summary
    
    def validate_configurations(self) -> Dict[str, bool]:
        """
        Валидирует загруженные конфигурации.
        
        Returns:
            Словарь с результатами валидации
        """
        validation_results = {}
        
        # Проверяем основные конфигурации
        validation_results['metadata'] = self.configs['metadata'] is not None
        validation_results['joint_metadata'] = self.configs['joint_metadata'] is not None
        validation_results['actuator_metadata'] = self.configs['actuator_metadata'] is not None
        validation_results['mjcf_extension'] = self.configs['mjcf_extension'] is not None
        
        # Проверяем пути
        if self.paths:
            validation_results['urdf_home_exists'] = os.path.exists(self.paths['urdf_home'])
            validation_results['output_dir_writable'] = os.path.exists(os.path.dirname(self.paths['output_path']))
        
        # Проверяем ключевые параметры в конфигурациях
        if self.configs['mjcf_extension']:
            mjcf_config = self.configs['mjcf_extension']
            validation_results['base_link_position'] = 'base_link_position' in mjcf_config
            validation_results['body_inertials'] = 'body_inertials' in mjcf_config
            validation_results['sensors_config'] = 'sensors' in mjcf_config
        
        return validation_results
    
    def print_status(self) -> None:
        """Выводит текущий статус конвертера."""
        print("\n=== СТАТУС URDFToMJCFConverter ===")
        
        if not self.configs:
            print("Конфигурации не загружены")
            return
        
        # Сводка конфигураций
        summary = self.get_configuration_summary()
        print("📋 Конфигурации:")
        print(f"  Метаданные: {'загружены' if summary['metadata_loaded'] else 'не загружены'}")
        print(f"  Метаданные суставов: {summary['joint_metadata_count']} суставов")
        print(f"  Метаданные актуаторов: {'загружены' if summary['actuator_metadata_loaded'] else 'не загружены'}")
        print(f"  Конфигурация MJCF: {'загружена' if summary['mjcf_extension_loaded'] else 'не загружена'}")
        print(f"  Keyframes: {summary['keyframes_count']} поз")
        print(f"  Ограничения суставов: {'загружены' if summary['joint_limits_loaded'] else 'не загружены'}")
        
        # Пути
        if self.paths:
            print("\n📁 Пути:")
            print(f"  URDF_HOME: {os.path.abspath(self.paths['urdf_home'])}")
            print(f"  OUTPUT_PATH: {os.path.abspath(self.paths['output_path'])}")
            print(f"  URDF_HOME существует: {'да' if os.path.exists(self.paths['urdf_home']) else 'нет'}")
        
        # Валидация
        validation = self.validate_configurations()
        print("\nВалидация:")
        for key, value in validation.items():
            status = "да" if value else "нет"
            print(f"  {status} {key}")
        
        print("=" * 40)
