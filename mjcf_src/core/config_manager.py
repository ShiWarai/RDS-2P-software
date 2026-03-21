#!/usr/bin/env python3
"""
Менеджер конфигураций для конвертации URDF в MJCF.
Отвечает за загрузку и валидацию всех конфигурационных файлов.
"""

import os
import yaml
from typing import Dict, Any, Optional, Tuple
from urdf2mjcf.model import JointMetadata, ActuatorMetadata, ConversionMetadata


class ConfigurationManager:
    """Класс для управления всеми конфигурационными файлами."""
    
    def __init__(self, config_dir: str = "configs"):
        """
        Инициализация менеджера конфигураций.
        
        Args:
            config_dir: Путь к директории с конфигурационными файлами
        """
        self.config_dir = config_dir
        self._metadata = None
        self._joint_metadata = None
        self._actuator_metadata = None
        self._default_actuator = None
        self._mjcf_extension_config = None
        self._keyframes_config = None
        self._joint_limits = None
        self._export_config = None
        
        # Пути к конфигурационным файлам
        self.metadata_path = os.path.join(config_dir, "metadata.yml")
        self.joint_metadata_path = os.path.join(config_dir, "joint_metadata.yml")
        self.actuator_metadata_path = os.path.join(config_dir, "actuator_metadata.yml")
        self.mjcf_extension_path = os.path.join(config_dir, "mjcf_extention.yml")
        self.keyframes_path = os.path.join(config_dir, "keyframes.yml")
        self.export_config_path = os.path.join(config_dir, "export_config.yml")
    
    def load_all_configs(self, urdf_home: str = None) -> Dict[str, Any]:
        """
        Загружает все конфигурационные файлы.
        
        Args:
            urdf_home: Путь к директории с URDF файлами
            
        Returns:
            Словарь с загруженными конфигурациями
        """
        print("Загрузка всех конфигурационных файлов...")
        
        # Загружаем основные конфигурации
        self._load_metadata()
        self._load_joint_metadata()
        self._load_actuator_metadata()
        self._load_mjcf_extension_config()
        self._load_keyframes_config()
        self._load_export_config()
        
        # Загружаем угловые ограничения если указан путь к URDF
        if urdf_home:
            self._load_joint_limits(urdf_home)
        
        return {
            'metadata': self._metadata,
            'joint_metadata': self._joint_metadata,
            'actuator_metadata': self._actuator_metadata,
            'default_actuator': self._default_actuator,
            'mjcf_extension': self._mjcf_extension_config,
            'keyframes': self._keyframes_config,
            'joint_limits': self._joint_limits,
            'export_config': self._export_config
        }
    
    def _load_metadata(self) -> None:
        """Загружает основные метаданные."""
        if os.path.exists(self.metadata_path):
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                self._metadata = yaml.safe_load(f)
            print(f"Загружены метаданные из {self.metadata_path}")
        else:
            print(f"Предупреждение: Файл метаданных {self.metadata_path} не найден")
            self._metadata = None
    
    def _load_joint_metadata(self) -> None:
        """Загружает метаданные суставов."""
        if os.path.exists(self.joint_metadata_path):
            with open(self.joint_metadata_path, 'r', encoding='utf-8') as f:
                joint_data = yaml.safe_load(f)
                self._joint_metadata = {}
                for key, value in joint_data["joint_name_to_metadata"].items():
                    self._joint_metadata[key] = JointMetadata.from_dict(value)
            print(f"Загружены метаданные суставов из {self.joint_metadata_path}")
        else:
            print(f"Предупреждение: Файл метаданных суставов {self.joint_metadata_path} не найден")
            self._joint_metadata = None
    
    def _load_actuator_metadata(self) -> None:
        """Загружает метаданные актуаторов."""
        if os.path.exists(self.actuator_metadata_path):
            with open(self.actuator_metadata_path, 'r', encoding='utf-8') as f:
                actuator_data = yaml.safe_load(f)
                actuator_type = actuator_data["actuator_type"]
                # Создаем объект ActuatorMetadata для библиотеки urdf2mjcf
                self._actuator_metadata = {actuator_type: ActuatorMetadata.from_dict(actuator_data)}
                # Создаем обычный словарь для внутреннего использования
                self._default_actuator = {actuator_type: actuator_data}
            print(f"Загружены метаданные приводов из {self.actuator_metadata_path}")
        else:
            print(f"Предупреждение: Файл метаданных приводов {self.actuator_metadata_path} не найден")
            self._actuator_metadata = None
            self._default_actuator = None
    
    def _load_mjcf_extension_config(self) -> None:
        """Загружает конфигурацию расширений MJCF."""
        if os.path.exists(self.mjcf_extension_path):
            with open(self.mjcf_extension_path, 'r', encoding='utf-8') as f:
                self._mjcf_extension_config = yaml.safe_load(f)
            print(f"Загружена конфигурация MJCF расширений из {self.mjcf_extension_path}")
        else:
            print(f"Предупреждение: Файл конфигурации MJCF {self.mjcf_extension_path} не найден")
            self._mjcf_extension_config = {}
    
    def _load_keyframes_config(self) -> None:
        """Загружает конфигурацию keyframes."""
        if os.path.exists(self.keyframes_path):
            with open(self.keyframes_path, 'r', encoding='utf-8') as f:
                keyframes_data = yaml.safe_load(f)
                self._keyframes_config = keyframes_data.get('keyframes', {})
            print(f"Загружены keyframes из {self.keyframes_path}")
        else:
            print(f"Предупреждение: Файл keyframes {self.keyframes_path} не найден")
            self._keyframes_config = {}
    
    def _load_export_config(self) -> None:
        """Загружает конфигурацию экспорта."""
        if os.path.exists(self.export_config_path):
            with open(self.export_config_path, 'r', encoding='utf-8') as f:
                self._export_config = yaml.safe_load(f)
            print(f"Загружена конфигурация экспорта из {self.export_config_path}")
        else:
            print(f"Предупреждение: Файл конфигурации экспорта {self.export_config_path} не найден")
            self._export_config = {}
    
    def _load_joint_limits(self, urdf_home: str) -> None:
        """Загружает угловые ограничения суставов."""
        joint_limits_path = os.path.join(urdf_home, "joint_limits.yml")
        
        if os.path.exists(joint_limits_path):
            try:
                with open(joint_limits_path, 'r', encoding='utf-8') as f:
                    self._joint_limits = yaml.safe_load(f)
                print(f"Загружены угловые ограничения из {joint_limits_path}")
            except Exception as e:
                print(f"Ошибка загрузки угловых ограничений: {e}")
                self._joint_limits = None
        else:
            print(f"Предупреждение: Файл угловых ограничений {joint_limits_path} не найден")
            self._joint_limits = None
    
    def get_paths(self) -> Dict[str, str]:
        """
        Извлекает пути из конфигурации.
        
        Returns:
            Словарь с путями
        """
        # Сначала пытаемся загрузить из export_config.yml
        if self._export_config and 'paths' in self._export_config:
            paths_config = self._export_config['paths']
            urdf_home = paths_config.get('urdf_source', "../urdf_src/export/rds-2p")
            output_path = paths_config.get('output_mjcf', "export/rds-2p/rds-2p.mjcf")
        # Если нет, пытаемся загрузить из старого места в mjcf_extension_config
        elif self._mjcf_extension_config and 'paths' in self._mjcf_extension_config:
            paths_config = self._mjcf_extension_config['paths']
            urdf_home = paths_config.get('urdf_source', "../urdf_src/export/rds-2p")
            output_path = paths_config.get('output_mjcf', paths_config.get('output_path', "export/rds-2p/rds-2p.mjcf"))
        else:
            return self._get_default_paths()
        
        # Извлекаем имя робота из пути URDF
        robot_name = os.path.basename(urdf_home)
        local_urdf_dir = robot_name
        local_urdf_file = os.path.join(local_urdf_dir, "urdf", f"{robot_name}.urdf")
        
        result = {
            'urdf_home': urdf_home,
            'output_path': output_path,
            'local_urdf_dir': local_urdf_dir,
            'local_urdf_file': local_urdf_file
        }
        
        # Добавляем все дополнительные пути из конфигурации
        if self._export_config and 'paths' in self._export_config:
            result.update(self._export_config['paths'])
        elif self._mjcf_extension_config and 'paths' in self._mjcf_extension_config:
            result.update(self._mjcf_extension_config['paths'])
        
        return result
    
    def _get_default_paths(self) -> Dict[str, str]:
        """Возвращает пути по умолчанию."""
        return {
            'urdf_home': "../urdf_src/export/rds-2p",
            'output_path': "export/rds-2p/rds-2p.mjcf",
            'local_urdf_dir': "rds-2p",
            'local_urdf_file': "rds-2p/urdf/rds-2p.urdf"
        }
    
    def get_conversion_metadata(self) -> Optional[ConversionMetadata]:
        """
        Создает объект ConversionMetadata для библиотеки urdf2mjcf.
        
        Returns:
            Объект ConversionMetadata или None
        """
        if self._metadata is not None:
            try:
                return ConversionMetadata.model_validate(self._metadata)
            except Exception as e:
                print(f"Предупреждение: Не удалось создать ConversionMetadata: {e}")
                return None
        return None
    
    @property
    def metadata(self) -> Optional[Dict[str, Any]]:
        """Возвращает основные метаданные."""
        return self._metadata
    
    @property
    def joint_metadata(self) -> Optional[Dict[str, JointMetadata]]:
        """Возвращает метаданные суставов."""
        return self._joint_metadata
    
    @property
    def actuator_metadata(self) -> Optional[Dict[str, ActuatorMetadata]]:
        """Возвращает метаданные актуаторов."""
        return self._actuator_metadata
    
    @property
    def default_actuator(self) -> Optional[Dict[str, Any]]:
        """Возвращает метаданные актуаторов в виде словаря."""
        return self._default_actuator
    
    @property
    def mjcf_extension_config(self) -> Optional[Dict[str, Any]]:
        """Возвращает конфигурацию MJCF расширений."""
        return self._mjcf_extension_config
    
    @property
    def keyframes_config(self) -> Optional[Dict[str, Any]]:
        """Возвращает конфигурацию keyframes."""
        return self._keyframes_config
    
    @property
    def joint_limits(self) -> Optional[Dict[str, Any]]:
        """Возвращает угловые ограничения суставов."""
        return self._joint_limits
    
    @property
    def export_config(self) -> Optional[Dict[str, Any]]:
        """Возвращает конфигурацию экспорта."""
        return self._export_config
