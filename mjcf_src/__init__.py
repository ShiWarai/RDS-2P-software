"""
Пакет для конвертации URDF в MJCF с использованием объектно-ориентированного подхода.

Основные компоненты:
- URDFToMJCFConverter: Главный класс-координатор
- ConfigurationManager: Управление конфигурациями
- URDFPreprocessor: Препроцессинг URDF файлов
- MJCFPostprocessor: Постобработка MJCF файлов
- Вспомогательные классы в mjcf_utils.py

Использование:
    from mjcf_src import URDFToMJCFConverter
    
    converter = URDFToMJCFConverter()
    mjcf_path = converter.convert()
"""

from .core import URDFToMJCFConverter, ConfigurationManager
from .processors import URDFPreprocessor, MJCFPostprocessor
from .utils import CameraProcessor, ActuatorProcessor, SensorManager, XMLFormatter

__version__ = "2.0.0"
__author__ = "RDS-2P Simulator Team"

__all__ = [
    'URDFToMJCFConverter',
    'ConfigurationManager', 
    'URDFPreprocessor',
    'MJCFPostprocessor',
    'CameraProcessor',
    'ActuatorProcessor',
    'SensorManager',
    'XMLFormatter'
]
