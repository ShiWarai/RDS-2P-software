#!/usr/bin/env python3
"""
Скрипт для автоматического обновления пакета rds_2p из экспортированных данных Blender.
Выполняет следующие действия:
1. Копирует меши из export/meshes в пакет
2. Обновляет базовый URDF файл
3. Создает модифицированный ROS URDF с ROS2 control конфигурацией
4. Обновляет wrapper файлы
"""

import os
import shutil
import re
from pathlib import Path

# Получаем абсолютный путь к корневой директории проекта
# (находимся в папке urdf, поэтому поднимаемся на уровень выше)
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent

# Пути относительно корня проекта
EXPORT_DIR = PROJECT_ROOT / "urdf_src" / "export" / "rds-2p"
PACKAGE_DIR = PROJECT_ROOT / "ros_packages" / "src" / "rds_2p"

# ROS2 control конфигурация для вставки
ROS2_CONTROL_CONFIG = '''  <!-- ros2_control configuration -->
  <ros2_control name="GazeboSystem" type="system">
    <hardware>
      <plugin>mock_components/GenericSystem</plugin>
    </hardware>
    
    <!-- Joint interfaces -->
    <joint name="leg_block_bl_joint">
      <command_interface name="position">
        <param name="min">-1.74533</param>
        <param name="max">0.95993</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="hip_bl_joint">
      <command_interface name="position">
        <param name="min">-1.04720</param>
        <param name="max">1.04720</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="shin_bl_joint">
      <command_interface name="position">
        <param name="min">-1.13446</param>
        <param name="max">0.52360</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="leg_block_br_joint">
      <command_interface name="position">
        <param name="min">-1.74533</param>
        <param name="max">0.95993</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="hip_br_joint">
      <command_interface name="position">
        <param name="min">-1.04720</param>
        <param name="max">1.04720</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="shin_br_joint">
      <command_interface name="position">
        <param name="min">-0.52360</param>
        <param name="max">1.13446</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="leg_block_fl_joint">
      <command_interface name="position">
        <param name="min">-1.74533</param>
        <param name="max">0.95993</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="hip_fl_joint">
      <command_interface name="position">
        <param name="min">-1.04720</param>
        <param name="max">1.04720</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="shin_fl_joint">
      <command_interface name="position">
        <param name="min">-1.13446</param>
        <param name="max">0.52360</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="leg_block_fr_joint">
      <command_interface name="position">
        <param name="min">-1.74533</param>
        <param name="max">0.95993</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="hip_fr_joint">
      <command_interface name="position">
        <param name="min">-1.04720</param>
        <param name="max">1.04720</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
    
    <joint name="shin_fr_joint">
      <command_interface name="position">
        <param name="min">-0.52360</param>
        <param name="max">1.13446</param>
      </command_interface>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
  </ros2_control>'''

def check_directories():
    """Проверяет существование необходимых директорий"""
    if not EXPORT_DIR.exists():
        raise FileNotFoundError(f"Директория экспорта не найдена: {EXPORT_DIR}")
    
    if not PACKAGE_DIR.exists():
        raise FileNotFoundError(f"Директория пакета не найдена: {PACKAGE_DIR}")
    
    print("✓ Директории найдены")

def copy_meshes():
    """Копирует меши из export в пакет (только dae формат для ROS)"""
    export_meshes_dae = EXPORT_DIR / "meshes" / "dae"
    package_meshes = PACKAGE_DIR / "meshes"
    package_meshes_dae = package_meshes / "dae"
    
    if not export_meshes_dae.exists():
        raise FileNotFoundError(f"Директория dae мешей экспорта не найдена: {export_meshes_dae}")
    
    # Создаем директорию meshes в пакете (если не существует)
    package_meshes.mkdir(parents=True, exist_ok=True)
    
    # Очищаем целевую директорию dae, если она существует
    if package_meshes_dae.exists():
        shutil.rmtree(package_meshes_dae)
    
    # Копируем только dae меши
    shutil.copytree(export_meshes_dae, package_meshes_dae)
    print("✓ Dae меши скопированы")

def update_base_urdf():
    """Обновляет базовый URDF файл"""
    export_urdf = EXPORT_DIR / "urdf" / "rds-2p.urdf"
    package_urdf = PACKAGE_DIR / "urdf" / "rds-2p.urdf"
    
    if not export_urdf.exists():
        raise FileNotFoundError(f"Базовый URDF экспорта не найден: {export_urdf}")
    
    # Создаем директорию, если её нет
    package_urdf.parent.mkdir(parents=True, exist_ok=True)
    
    # Читаем экспортированный файл
    with open(export_urdf, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Исправляем пути к мешам: заменяем package://meshes на package://rds_2p/meshes
    content = content.replace('package://meshes/', 'package://rds_2p/meshes/')
    
    # Записываем исправленный файл
    with open(package_urdf, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✓ Базовый URDF обновлен с исправленными путями к мешам")

def create_ros_urdf():
    """Создает модифицированный ROS URDF с ROS2 control конфигурацией"""
    export_ros_urdf = EXPORT_DIR / "urdf" / "rds-2p_ros.urdf"
    package_ros_urdf = PACKAGE_DIR / "urdf" / "rds-2p_ros.urdf"
    
    if not export_ros_urdf.exists():
        raise FileNotFoundError(f"ROS URDF экспорта не найден: {export_ros_urdf}")
    
    # Создаем директорию, если её нет
    package_ros_urdf.parent.mkdir(parents=True, exist_ok=True)
    
    # Читаем экспортированный файл
    with open(export_ros_urdf, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Исправляем пути к мешам: заменяем package://meshes на package://rds_2p/meshes
    content = content.replace('package://meshes/', 'package://rds_2p/meshes/')
    
    # Находим место для вставки ROS2 control (после последнего joint)
    # Ищем последний joint и вставляем ROS2 control после него
    joint_pattern = r'(<joint name="shin_fr_joint".*?</joint>\s*)'
    match = re.search(joint_pattern, content, re.DOTALL)
    
    if match:
        # Вставляем ROS2 control после последнего joint
        modified_content = re.sub(
            joint_pattern,
            r'\1\n' + ROS2_CONTROL_CONFIG + '\n\n  ',
            content,
            flags=re.DOTALL
        )
        
        # Записываем модифицированный файл
        with open(package_ros_urdf, 'w', encoding='utf-8') as f:
            f.write(modified_content)
        
        print("✓ ROS URDF создан с ROS2 control конфигурацией и исправленными путями к мешам")
    else:
        print("⚠ Не удалось найти место для вставки ROS2 control")
        # Просто копируем файл с исправленными путями
        with open(package_ros_urdf, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✓ ROS URDF скопирован с исправленными путями к мешам")

def update_wrapper_files():
    """Обновляет wrapper файлы"""
    # Создаем директорию urdf, если её нет
    urdf_dir = PACKAGE_DIR / "urdf"
    urdf_dir.mkdir(parents=True, exist_ok=True)
    
    # Обновляем основной wrapper
    wrapper_content = '''<?xml version="1.0" encoding="utf-8"?>
<robot xmlns:xacro="http://www.ros.org/wiki/xacro" name="rds-2p_description">
    <xacro:include filename="rds-2p_ros.urdf"/>
</robot>'''
    
    wrapper_file = urdf_dir / "rds-2p_description_wrapper.urdf.xacro"
    with open(wrapper_file, 'w', encoding='utf-8') as f:
        f.write(wrapper_content)
    
    # Обновляем sensors wrapper
    sensors_content = '''<?xml version="1.0"?>
<robot xmlns:xacro="http://www.ros.org/wiki/xacro">
    <!-- Sensor configurations can be added here -->
</robot>'''
    
    sensors_file = urdf_dir / "rds-2p_description_sensors.urdf.xacro"
    with open(sensors_file, 'w', encoding='utf-8') as f:
        f.write(sensors_content)
    
    print("✓ Wrapper файлы обновлены")

def main():
    """Основная функция"""
    print("🔄 Начинаю обновление пакета rds_2p...")
    print(f"📁 Экспорт: {EXPORT_DIR}")
    print(f"📦 Пакет: {PACKAGE_DIR}")
    print()
    
    try:
        check_directories()
        copy_meshes()
        update_base_urdf()
        create_ros_urdf()
        update_wrapper_files()
        
        print()
        print("✅ Обновление пакета rds_2p завершено успешно!")
        print("📝 Теперь можно собирать пакет: colcon build --packages-select rds_2p")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
