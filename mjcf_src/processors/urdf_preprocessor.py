#!/usr/bin/env python3
"""
Препроцессор URDF файлов.
Отвечает за подготовку URDF файлов к конвертации в MJCF.
"""

import os
import shutil
import re
from typing import Dict, Any, Optional


class URDFPreprocessor:
    """Класс для препроцессинга URDF файлов перед конвертацией."""
    
    def __init__(self, paths: Dict[str, str]):
        """
        Инициализация препроцессора.
        
        Args:
            paths: Словарь с путями к файлам
        """
        self.urdf_home = paths['urdf_home']
        self.local_urdf_dir = paths['local_urdf_dir']
        self.local_urdf_file = paths['local_urdf_file']
        
        print(f"URDFPreprocessor инициализирован:")
        print(f"  URDF_HOME: {os.path.abspath(self.urdf_home)}")
        print(f"  URDF_HOME существует: {os.path.exists(self.urdf_home)}")
    
    def prepare_urdf(self) -> str:
        """
        Выполняет полную подготовку URDF файла.
        
        Returns:
            Путь к подготовленному URDF файлу
        """
        print("=== НАЧАЛО ПРЕПРОЦЕССА URDF ===")
        
        # Этап 1: Подготовка рабочей директории
        self._prepare_working_directory()
        
        # Этап 2: Очистка и реорганизация файлов мешей
        self._cleanup_mesh_files()
        
        # Этап 3: Подготовка URDF файла
        urdf_file_path = self._prepare_urdf_file()
        
        # Этап 4: Обновление путей к мешам в URDF
        self._update_urdf_mesh_paths(urdf_file_path)
        
        # Этап 5: Очистка атрибутов scale в URDF
        self._clean_urdf_scale_attributes(urdf_file_path)
        
        print("=== ПРЕПРОЦЕСС URDF ЗАВЕРШЕН ===\n")
        
        return urdf_file_path
    
    def _prepare_working_directory(self) -> None:
        """Подготавливает рабочую директорию, копируя URDF файлы."""
        # Удаляем существующую локальную директорию
        if os.path.exists(self.local_urdf_dir):
            print(f"Удаление существующей директории {self.local_urdf_dir}")
            shutil.rmtree(self.local_urdf_dir)
        
        # Копируем всю URDF директорию
        print(f"Копирование {self.urdf_home} в {self.local_urdf_dir}")
        shutil.copytree(self.urdf_home, self.local_urdf_dir)
    
    def _cleanup_mesh_files(self) -> None:
        """Очищает и реорганизует файлы мешей для совместимости с MuJoCo."""
        print("Очистка и реорганизация файлов мешей...")
        
        # Удаляем dae меши
        dae_meshes_path = os.path.join(self.local_urdf_dir, "meshes", "dae")
        if os.path.exists(dae_meshes_path):
            print(f"Удаление dae мешей: {dae_meshes_path}")
            shutil.rmtree(dae_meshes_path)
        
        # Перемещаем obj меши из подпапки obj в основную папку meshes
        obj_meshes_path = os.path.join(self.local_urdf_dir, "meshes", "obj")
        meshes_main_path = os.path.join(self.local_urdf_dir, "meshes")
        
        if os.path.exists(obj_meshes_path):
            print(f"Перемещение obj мешей из {obj_meshes_path} в {meshes_main_path}")
            
            # Перемещаем все obj файлы
            for obj_file in os.listdir(obj_meshes_path):
                if obj_file.endswith('.obj'):
                    src_path = os.path.join(obj_meshes_path, obj_file)
                    dst_path = os.path.join(meshes_main_path, obj_file)
                    shutil.move(src_path, dst_path)
                    print(f"  Перемещен {obj_file}")
            
            # Удаляем пустую подпапку obj
            shutil.rmtree(obj_meshes_path)
            print("Удалена пустая подпапка obj")
    
    def _prepare_urdf_file(self) -> str:
        """
        Подготавливает URDF файл для конвертации.
        
        Returns:
            Путь к подготовленному URDF файлу
        """
        print(f"Подготовка URDF файла: {self.local_urdf_file}")
        print(f"Локальный URDF файл существует: {os.path.exists(self.local_urdf_file)}")
        
        # Перемещаем URDF файл в корень скопированной директории
        # для правильного разрешения относительных путей
        urdf_root_path = os.path.join(self.local_urdf_dir, "rds-2p.urdf")
        shutil.move(self.local_urdf_file, urdf_root_path)
        
        print(f"URDF файл перемещен в: {urdf_root_path}")
        return urdf_root_path
    
    def _update_urdf_mesh_paths(self, urdf_file_path: str) -> None:
        """
        Обновляет пути к мешам в URDF файле.
        
        Args:
            urdf_file_path: Путь к URDF файлу
        """
        print("Обновление путей к мешам в URDF файле...")
        
        # Читаем URDF файл
        with open(urdf_file_path, 'r') as f:
            urdf_content = f.read()
        
        # Заменяем пути к мешам
        # ../meshes/dae/ -> meshes/
        urdf_content = re.sub(r'\.\./meshes/dae/', 'meshes/', urdf_content)
        
        # Заменяем расширения .dae на .obj
        urdf_content = re.sub(r'\.dae', '.obj', urdf_content)
        
        # Записываем обновленное содержимое
        with open(urdf_file_path, 'w') as f:
            f.write(urdf_content)
        
        print("Пути к мешам обновлены")
    
    def _clean_urdf_scale_attributes(self, urdf_file_path: str) -> None:
        """
        Очищает URDF файл от атрибутов scale в блоках mesh.
        
        Args:
            urdf_file_path: Путь к URDF файлу
        """
        print("Очистка атрибутов scale из блоков mesh...")
        
        # Читаем URDF файл
        with open(urdf_file_path, 'r') as f:
            urdf_content = f.read()
        
        # Убираем атрибут scale из блоков mesh
        urdf_content = re.sub(
            r'(<mesh filename="[^"]*")[^>]*scale="[^"]*"([^>]*/>)',
            r'\1\2',
            urdf_content
        )
        
        # Записываем обновленное содержимое
        with open(urdf_file_path, 'w') as f:
            f.write(urdf_content)
        
        print("Атрибуты scale удалены")
    
    def cleanup(self) -> None:
        """Очищает рабочую директорию после завершения."""
        print("Очистка рабочей директории...")
        if os.path.exists(self.local_urdf_dir):
            shutil.rmtree(self.local_urdf_dir)
            print(f"Директория {self.local_urdf_dir} удалена")
