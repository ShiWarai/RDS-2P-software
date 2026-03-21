#!/usr/bin/env python3
"""
Вспомогательные классы и утилиты для работы с MJCF.
Содержит специализированные классы для различных аспектов постобработки MJCF.
"""

import os
import re
import math
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional, List, Tuple


class CameraProcessor:
    """Класс для обработки камер из URDF файлов."""
    
    @staticmethod
    def extract_cameras_from_urdf(urdf_file_path: str) -> List[Dict[str, Any]]:
        """
        Извлекает информацию о всех камерах из URDF файла.
        
        Args:
            urdf_file_path: Путь к URDF файлу
            
        Returns:
            Список словарей с информацией о камерах
        """
        cameras_info = []
        
        try:
            with open(urdf_file_path, 'r', encoding='utf-8') as f:
                urdf_content = f.read()
            
            # Паттерн для поиска камер в URDF
            camera_pattern = (
                r'<sensor name="([^"]+)" type="camera">\s*'
                r'<origin rpy="([^"]+)" xyz="([^"]+)"/>\s*'
                r'<parent link="([^"]+)"/>\s*'
                r'<camera>\s*'
                r'<image>\s*'
                r'<width>(\d+)</width>\s*'
                r'<height>(\d+)</height>\s*'
                r'<hfov>([^<]+)</hfov>\s*'
                r'</image>\s*'
                r'</camera>\s*'
                r'</sensor>'
            )
            
            camera_matches = re.findall(camera_pattern, urdf_content, re.DOTALL)
            
            for camera_match in camera_matches:
                name, rpy, xyz, parent_link, width, height, hfov = camera_match
                
                # Парсим параметры
                rpy_parts = [float(x) for x in rpy.split()]
                xyz_parts = [float(x) for x in xyz.split()]
                
                # Конвертируем RPY в кватернион
                quat = CameraProcessor._rpy_to_quaternion(rpy_parts)
                
                camera_info = {
                    'name': name,
                    'pos': xyz_parts,
                    'quat': quat,
                    'width': int(width),
                    'height': int(height),
                    'hfov': float(hfov),
                    'parent_link': parent_link
                }
                
                cameras_info.append(camera_info)
            
            if cameras_info:
                print(f"Извлечена информация о {len(cameras_info)} камерах: {[cam['name'] for cam in cameras_info]}")
            else:
                print("Предупреждение: Сенсоры камер не найдены в URDF")
                
        except Exception as e:
            print(f"Ошибка извлечения камер из URDF: {e}")
        
        return cameras_info
    
    @staticmethod
    def _rpy_to_quaternion(rpy_parts: List[float]) -> List[float]:
        """
        Конвертирует RPY (Roll, Pitch, Yaw) в кватернион.
        
        Args:
            rpy_parts: Список [roll, pitch, yaw] в радианах
            
        Returns:
            Кватернион [w, x, y, z]
        """
        roll, pitch, yaw = rpy_parts
        
        # Инвертируем направление камеры для MuJoCo
        yaw = yaw + math.pi
        
        # Простая конвертация в кватернион
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)
        
        return [
            cr * cp * cy + sr * sp * sy,  # w
            sr * cp * cy - cr * sp * sy,  # x
            cr * sp * cy + sr * cp * sy,  # y
            cr * cp * sy - sr * sp * cy   # z
        ]
    
    @staticmethod
    def add_cameras_to_mjcf(root: ET.Element, urdf_path: str) -> None:
        """
        Добавляет камеры из URDF в MJCF файл.
        
        Args:
            root: Корневой элемент MJCF
            urdf_path: Путь к URDF файлу
        """
        if not urdf_path or not os.path.exists(urdf_path):
            return
        
        cameras_info = CameraProcessor.extract_cameras_from_urdf(urdf_path)
        if not cameras_info:
            return
        
        # Ищем base_link
        base_link = root.find('.//body[@name="base_link"]')
        if base_link is not None:
            for camera_info in cameras_info:
                camera_elem = ET.Element('camera')
                camera_elem.set('name', camera_info['name'])
                camera_elem.set('mode', 'fixed')
                camera_elem.set('fovy', f"{camera_info['hfov'] * 180 / math.pi:.1f}")
                camera_elem.set('quat', f"{camera_info['quat'][0]:.6f} {camera_info['quat'][1]:.6f} {camera_info['quat'][2]:.6f} {camera_info['quat'][3]:.6f}")
                camera_elem.set('pos', f"{camera_info['pos'][0]:.6f} {camera_info['pos'][1]:.6f} {camera_info['pos'][2]:.6f}")
                camera_elem.set('resolution', f"{camera_info['width']} {camera_info['height']}")
                
                base_link.append(camera_elem)
        else:
            print("Предупреждение: base_link не найден для камер")


class ActuatorProcessor:
    """Класс для обработки актуаторов в MJCF."""
    
    @staticmethod
    def replace_motor_tags_with_position(root: ET.Element, actuator_metadata: Optional[Dict[str, Any]]) -> None:
        """
        Заменяет теги <motor> на <position> в XML-дереве MJCF.
        
        Args:
            root: Корневой элемент MJCF
            actuator_metadata: Метаданные актуаторов
        """
        try:
            # Обрабатываем секцию actuator
            actuator = root.find('.//actuator')
            if actuator is not None:
                motor_elements = actuator.findall('motor')
                
                if motor_elements:
                    for motor_elem in motor_elements:
                        position_elem = ET.Element('position')
                        
                        # Копируем все атрибуты
                        for key, value in motor_elem.attrib.items():
                            position_elem.set(key, value)
                        
                        # Заменяем элемент
                        index = list(actuator).index(motor_elem)
                        actuator.remove(motor_elem)
                        actuator.insert(index, position_elem)
                    
                    print(f"Заменено {len(motor_elements)} актуаторов: <motor> → <position>")
                else:
                    print("Актуаторы <motor> не найдены для замены")
            
            # Обрабатываем секции default
            ActuatorProcessor._process_default_sections(root, actuator_metadata)
            
        except Exception as e:
            print(f"Ошибка замены тегов <motor> на <position>: {e}")
    
    @staticmethod
    def _process_default_sections(root: ET.Element, actuator_metadata: Optional[Dict[str, Any]]) -> None:
        """Обрабатывает секции default."""
        default_sections = root.findall('.//default')
        for default_section in default_sections:
            motor_elements = default_section.findall('motor')
            
            if motor_elements:
                for motor_elem in motor_elements:
                    position_elem = ET.Element('position')
                    
                    # Копируем атрибуты
                    for key, value in motor_elem.attrib.items():
                        position_elem.set(key, value)
                    
                    # Добавляем параметры из actuator_metadata
                    if actuator_metadata:
                        actuator_data = list(actuator_metadata.values())[0]
                        
                        if 'kp' in actuator_data and actuator_data['kp']:
                            position_elem.set('kp', str(actuator_data['kp']))
                        
                        if 'kv' in actuator_data and actuator_data['kv']:
                            position_elem.set('kv', str(actuator_data['kv']))
                        
                        if 'max_torque' in actuator_data and actuator_data['max_torque']:
                            position_elem.set('forcerange', f"-{actuator_data['max_torque']} {actuator_data['max_torque']}")
                    
                    # Заменяем элемент
                    index = list(default_section).index(motor_elem)
                    default_section.remove(motor_elem)
                    default_section.insert(index, position_elem)
                
                print(f"Заменено {len(motor_elements)} элементов <motor> → <position> в секции default")
    
    @staticmethod
    def apply_joint_limits_to_actuators(root: ET.Element, joint_limits: Dict[str, Any]) -> None:
        """
        Применяет угловые ограничения к актуаторам position.
        
        Args:
            root: Корневой элемент MJCF
            joint_limits: Словарь с угловыми ограничениями
        """
        try:
            print(f"Применение угловых ограничений. Доступные ограничения: {list(joint_limits.keys()) if joint_limits else 'None'}")
            
            if joint_limits and 'limits' in joint_limits:
                limits_data = joint_limits['limits']
                elements = limits_data.get('elements', [])
                names = limits_data.get('names', [])
                
                print(f"Найдены ограничения для {len(elements)} суставов: {names}")
            else:
                print("Структура joint_limits не содержит ключ 'limits'")
                return
            
            # Создаем словарь для быстрого поиска
            joint_limits_dict = {}
            for i, name in enumerate(names):
                if i < len(elements):
                    joint_limits_dict[name] = elements[i]
            
            print(f"Создан словарь ограничений для суставов: {list(joint_limits_dict.keys())}")
            
            # Применяем ограничения к актуаторам
            actuator = root.find('.//actuator')
            if actuator is not None:
                position_actuators = actuator.findall('position')
                print(f"Найдено {len(position_actuators)} актуаторов position")
                
                updated_count = 0
                for pos_actuator in position_actuators:
                    joint_name = pos_actuator.get('joint')
                    
                    if joint_name and joint_name in joint_limits_dict:
                        limits = joint_limits_dict[joint_name]
                        min_angle_rad = limits['min']['position']
                        max_angle_rad = limits['max']['position']
                        
                        ctrlrange_str = f"{min_angle_rad:.6f} {max_angle_rad:.6f}"
                        pos_actuator.set('ctrlrange', ctrlrange_str)
                        
                        print(f"Установлен ctrlrange для {joint_name}: {ctrlrange_str}")
                        updated_count += 1
                    elif joint_name:
                        print(f"Ограничения для сустава {joint_name} не найдены")
                
                print(f"Обновлено {updated_count} актуаторов с угловыми ограничениями")
            else:
                print("Секция <actuator> не найдена")
                
        except Exception as e:
            print(f"Ошибка применения угловых ограничений: {e}")


class SensorManager:
    """Класс для управления сенсорами в MJCF."""
    
    @staticmethod
    def add_base_sensors(root: ET.Element, config: Dict[str, Any]) -> None:
        """
        Добавляет базовые сенсоры для робота.
        
        Args:
            root: Корневой элемент MJCF
            config: Конфигурация сенсоров
        """
        try:
            print("Добавление базовых сенсоров...")
            
            # Находим или создаем секцию sensor
            sensor_section = root.find('.//sensor')
            if sensor_section is None:
                sensor_section = SensorManager._create_sensor_section(root)
            
            # Получаем конфигурацию сенсоров
            sensors_config = config.get('sensors', {})
            base_sensors = sensors_config.get('base_sensors', [])
            
            if not base_sensors:
                base_sensors = SensorManager._get_default_base_sensors()
                print("Используются базовые сенсоры по умолчанию")
            
            # Добавляем сенсоры
            missing_sensors_comment = ET.Comment(" Недостающие базовые сенсоры ")
            sensor_section.append(missing_sensors_comment)
            
            for sensor_config in base_sensors:
                SensorManager._add_sensor_if_not_exists(sensor_section, sensor_config)
            
            print("Добавление базовых сенсоров завершено")
            
        except Exception as e:
            print(f"Ошибка добавления базовых сенсоров: {e}")
    
    @staticmethod
    def _create_sensor_section(root: ET.Element) -> ET.Element:
        """Создает секцию sensor если её нет."""
        print("Секция <sensor> не найдена, создаем новую")
        mujoco = root.find('.//mujoco')
        if mujoco is not None:
            return ET.SubElement(mujoco, 'sensor')
        else:
            raise ValueError("Секция <mujoco> не найдена")
    
    @staticmethod
    def _get_default_base_sensors() -> List[Dict[str, str]]:
        """Возвращает список базовых сенсоров по умолчанию."""
        return [
            {'name': 'base_link_site_upvector', 'type': 'framezaxis', 'objtype': 'site', 'objname': 'base_link_site'},
            {'name': 'base_link_site_forwardvector', 'type': 'framexaxis', 'objtype': 'site', 'objname': 'base_link_site'},
            {'name': 'base_link_site_global_linvel', 'type': 'framelinvel', 'objtype': 'site', 'objname': 'base_link_site'},
            {'name': 'base_link_site_global_angvel', 'type': 'frameangvel', 'objtype': 'site', 'objname': 'base_link_site'}
        ]
    
    @staticmethod
    def _add_sensor_if_not_exists(sensor_section: ET.Element, sensor_config: Dict[str, str]) -> None:
        """Добавляет сенсор если его еще нет."""
        sensor_name = sensor_config['name']
        sensor_type = sensor_config['type']
        objtype = sensor_config['objtype']
        objname = sensor_config['objname']
        
        existing_sensor = sensor_section.find(f'.//{sensor_type}[@name="{sensor_name}"]')
        if existing_sensor is None:
            sensor_elem = ET.Element(sensor_type)
            sensor_elem.set('name', sensor_name)
            sensor_elem.set('objtype', objtype)
            sensor_elem.set('objname', objname)
            sensor_section.append(sensor_elem)
            print(f"Добавлен базовый сенсор: {sensor_name}")
        else:
            print(f"Сенсор {sensor_name} уже существует")
    
    @staticmethod
    def add_foot_sensors(root: ET.Element, config: Dict[str, Any]) -> None:
        """
        Добавляет сенсоры для ног.
        
        Args:
            root: Корневой элемент MJCF
            config: Конфигурация сенсоров
        """
        try:
            print("Добавление сенсоров для ног...")
            
            # Находим или создаем секцию sensor
            sensor_section = root.find('.//sensor')
            if sensor_section is None:
                sensor_section = SensorManager._create_sensor_section(root)
            
            # Находим все тела ног
            foot_bodies = SensorManager._find_foot_bodies(root)
            if not foot_bodies:
                print("Предупреждение: Тела ног не найдены")
                return
            
            # Получаем конфигурацию сенсоров для ног
            sensors_config = config.get('sensors', {})
            foot_sensors_config = sensors_config.get('foot_sensors', [])
            
            # Добавляем сенсоры для каждой ноги
            foot_comment = ET.Comment(" Сенсоры для каждой ноги ")
            sensor_section.append(foot_comment)
            
            for foot_body in foot_bodies:
                SensorManager._add_sensors_for_foot(sensor_section, foot_body, foot_sensors_config)
            
            # Добавляем сенсоры позиции и контакта
            SensorManager._add_foot_position_sensors(sensor_section, foot_bodies)
            SensorManager._add_foot_contact_sensors(sensor_section, foot_bodies)
            
            print("Добавление сенсоров для ног завершено")
            
        except Exception as e:
            print(f"Ошибка добавления сенсоров для ног: {e}")
    
    @staticmethod
    def _find_foot_bodies(root: ET.Element) -> List[ET.Element]:
        """Находит все тела ног."""
        all_bodies = root.findall('.//body')
        return [body for body in all_bodies 
                if body.get('name', '').startswith('foot_') and body.get('name', '').endswith('_link')]
    
    @staticmethod
    def _add_sensors_for_foot(sensor_section: ET.Element, foot_body: ET.Element, foot_sensors_config: List[Dict[str, str]]) -> None:
        """Добавляет сенсоры для конкретной ноги."""
        foot_body_name = foot_body.get('name')
        foot_prefix = foot_body_name.replace('_link', '')
        
        for sensor_config in foot_sensors_config:
            sensor_name = sensor_config['name_pattern'].format(foot_prefix=foot_prefix)
            sensor_type = sensor_config['type']
            objtype = sensor_config['objtype']
            objname = sensor_config['objname'].format(foot_prefix=foot_prefix)
            
            existing_sensor = sensor_section.find(f'.//{sensor_type}[@name="{sensor_name}"]')
            if existing_sensor is None:
                sensor_elem = ET.Element(sensor_type)
                sensor_elem.set('name', sensor_name)
                sensor_elem.set('objtype', objtype)
                sensor_elem.set('objname', objname)
                sensor_section.append(sensor_elem)
                print(f"Добавлен сенсор {sensor_name} для {foot_prefix}")
    
    @staticmethod
    def _add_foot_position_sensors(sensor_section: ET.Element, foot_bodies: List[ET.Element]) -> None:
        """Добавляет сенсоры позиции ног."""
        foot_pos_comment = ET.Comment(" Позиция ног относительно base_link_site ")
        sensor_section.append(foot_pos_comment)
        
        for foot_body in foot_bodies:
            foot_body_name = foot_body.get('name')
            foot_prefix = foot_body_name.replace('_link', '')
            site_name = f"{foot_prefix}_site"
            
            pos_sensor = ET.Element('framepos')
            pos_sensor.set('objtype', 'site')
            pos_sensor.set('objname', site_name)
            pos_sensor.set('name', f"{site_name}_pos")
            pos_sensor.set('reftype', 'site')
            pos_sensor.set('refname', 'base_link_site')
            sensor_section.append(pos_sensor)
            
            print(f"Добавлен сенсор позиции для {foot_prefix}")
    
    @staticmethod
    def _add_foot_contact_sensors(sensor_section: ET.Element, foot_bodies: List[ET.Element]) -> None:
        """Добавляет сенсоры контакта ног."""
        foot_contact_comment = ET.Comment(" Контакт ног с полом ")
        sensor_section.append(foot_contact_comment)
        
        for foot_body in foot_bodies:
            foot_body_name = foot_body.get('name')
            foot_prefix = foot_body_name.replace('_link', '')
            
            contact_sensor = ET.Element('contact')
            contact_sensor.set('name', f"{foot_prefix}_link_collision_floor_found")
            contact_sensor.set('geom1', f"{foot_prefix}_link_collision")
            contact_sensor.set('geom2', 'floor')
            contact_sensor.set('reduce', 'mindist')
            contact_sensor.set('num', '1')
            contact_sensor.set('data', 'found')
            sensor_section.append(contact_sensor)
            
            print(f"Добавлен сенсор контакта для {foot_prefix}")
    
    @staticmethod
    def remove_duplicate_sensors(root: ET.Element) -> None:
        """
        Удаляет дублирующиеся сенсоры по атрибуту name.
        
        Args:
            root: Корневой элемент MJCF
        """
        try:
            sensor = root.find('.//sensor')
            
            if sensor is not None:
                seen_names = {}
                sensors_to_remove = []
                
                # Проходим по всем сенсорам
                for sensor_elem in sensor.findall('*'):
                    sensor_name = sensor_elem.get('name')
                    
                    if sensor_name is None:
                        continue
                    
                    if sensor_name in seen_names:
                        sensors_to_remove.append(sensor_elem)
                        print(f"Найден дубликат сенсора: {sensor_name}")
                    else:
                        seen_names[sensor_name] = sensor_elem
                
                # Удаляем дубликаты
                if sensors_to_remove:
                    for duplicate_sensor in sensors_to_remove:
                        sensor.remove(duplicate_sensor)
                    print(f"Удалено {len(sensors_to_remove)} дубликатов сенсоров")
                else:
                    print("Дубликаты сенсоров не найдены")
            else:
                print("Секция <sensor> не найдена")
                
        except Exception as e:
            print(f"Ошибка удаления дубликатов сенсоров: {e}")


class XMLFormatter:
    """Класс для форматирования XML."""
    
    @staticmethod
    def pretty_print_xml(xml_content: str) -> str:
        """
        Форматирует XML для красивого вывода с правильными отступами.
        
        Args:
            xml_content: Исходное XML содержимое
            
        Returns:
            Отформатированное XML содержимое
        """
        try:
            # Парсим XML
            root = ET.fromstring(xml_content)
            
            # Создаем красивый XML с отступами
            pretty_xml = ET.tostring(root, encoding='unicode', method='xml')
            
            # Добавляем переносы строк и отступы
            pretty_xml = re.sub(r'>', '>\n', pretty_xml)
            
            lines = pretty_xml.split('\n')
            formatted_lines = []
            indent_level = 0
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Уменьшаем отступ для закрывающих тегов
                if line.startswith('</'):
                    indent_level = max(0, indent_level - 1)
                
                # Добавляем отступ
                formatted_lines.append('  ' * indent_level + line)
                
                # Увеличиваем отступ для открывающих тегов
                if line.startswith('<') and not line.startswith('</') and not line.endswith('/>'):
                    indent_level += 1
            
            return '\n'.join(formatted_lines)
            
        except Exception as e:
            print(f"Предупреждение: Не удалось отформатировать XML: {e}")
            return xml_content
