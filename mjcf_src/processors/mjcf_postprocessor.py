#!/usr/bin/env python3
"""
Постпроцессор MJCF файлов.
Отвечает за постобработку MJCF файлов после базовой конвертации.
"""

import os
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional

from utils.mjcf_utils import CameraProcessor, ActuatorProcessor, SensorManager, XMLFormatter


class MJCFPostprocessor:
    """Класс для постобработки MJCF файлов."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Инициализация постпроцессора.
        
        Args:
            config: Конфигурация постобработки
        """
        self.config = config
    
    def postprocess_mjcf(self, mjcf_path: str, urdf_path: str = None, 
                        joint_limits: Optional[Dict[str, Any]] = None,
                        actuator_metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Выполняет полную постобработку MJCF файла.
        
        Args:
            mjcf_path: Путь к MJCF файлу
            urdf_path: Путь к исходному URDF файлу
            joint_limits: Угловые ограничения суставов
            actuator_metadata: Метаданные актуаторов
        """
        print("=== НАЧАЛО ПОСТОБРАБОТКИ MJCF ===")
        
        # Читаем MJCF файл
        with open(mjcf_path, 'r', encoding='utf-8') as f:
            mjcf_content = f.read()
        
        try:
            # Парсим XML
            root = ET.fromstring(mjcf_content)
            print(f"XML успешно распарсен. Корневой элемент: {root.tag}")
            
            # Выполняем все этапы постобработки
            self._process_cameras(root, urdf_path)
            self._process_global_mjcf_elements(root)
            self._process_base_link_configuration(root)
            self._process_body_inertials(root)
            self._process_contact_and_physics(root)
            self._process_actuators_and_keyframes(root, joint_limits, actuator_metadata)
            self._process_ordering_and_sensors(root)
            
            # Сохраняем результат
            self._save_processed_mjcf(root, mjcf_path)
            
            print("=== ПОСТОБРАБОТКА MJCF ЗАВЕРШЕНА ===\n")
            
        except ET.ParseError as e:
            print(f"Ошибка парсинга XML во время постобработки: {e}")
        except Exception as e:
            print(f"Ошибка во время постобработки MJCF: {e}")
    
    def _process_cameras(self, root: ET.Element, urdf_path: str) -> None:
        """Обрабатывает камеры из URDF файла."""
        print("Этап 1: Обработка камер из URDF...")
        CameraProcessor.add_cameras_to_mjcf(root, urdf_path)
    
    def _process_global_mjcf_elements(self, root: ET.Element) -> None:
        """Обрабатывает глобальные элементы MJCF."""
        print("Этап 2: Обработка глобальных элементов MJCF...")
        global_config = self.config.get('global_mjcf', {})
        if not global_config:
            print("Глобальная конфигурация MJCF не найдена")
            return
        
        # Обрабатываем каждый глобальный элемент
        for element_name, element_config in global_config.items():
            if not isinstance(element_config, dict):
                continue
            
            if element_name == 'mujoco':
                self._process_mujoco_element(root, element_config)
            else:
                self._process_generic_global_element(root, element_name, element_config)
    
    def _process_mujoco_element(self, root: ET.Element, config: Dict[str, Any]) -> None:
        """Обрабатывает корневой элемент mujoco."""
        for key, value in config.items():
            root.set(key, str(value))
    
    def _process_generic_global_element(self, root: ET.Element, element_name: str, config: Dict[str, Any]) -> None:
        """Обрабатывает общий глобальный элемент."""
        # Ищем существующий элемент
        existing_element = root.find(f'.//{element_name}')
        
        if existing_element is not None:
            # Обновляем существующий элемент
            for key, value in config.items():
                existing_element.set(key, str(value))
        else:
            # Создаем новый элемент
            new_element = ET.Element(element_name)
            for key, value in config.items():
                new_element.set(key, str(value))
            
            # Вставляем в начало
            root.insert(0, new_element)
    
    def _process_base_link_configuration(self, root: ET.Element) -> None:
        """Обрабатывает конфигурацию базового тела."""
        print("Этап 3: Обработка конфигурации базового тела...")
        
        # Обновляем положение базового тела
        base_position_config = self.config.get('base_link_position', {})
        if 'pos' in base_position_config:
            new_pos = base_position_config['pos']
            base_link = root.find('.//body[@name="base_link"]')
            if base_link is not None:
                new_pos_str = f"{new_pos[0]:.8f} {new_pos[1]:.8f} {new_pos[2]:.8f}"
                base_link.set('pos', new_pos_str)
                print(f"Обновлена позиция base_link: {new_pos_str}")
            else:
                print("Предупреждение: Не удалось найти base_link для обновления позиции")
        
        # Добавляем inertial для base_link
        base_link_config = self.config.get('base_link_body', {})
        if 'inertial' in base_link_config:
            inertial = base_link_config['inertial']
            base_link = root.find('.//body[@name="base_link"]')
            if base_link is not None:
                # Создаем элемент inertial
                inertial_elem = ET.Element('inertial')
                inertial_elem.set('pos', f"{inertial['pos'][0]:.6f} {inertial['pos'][1]:.6f} {inertial['pos'][2]:.6f}")
                inertial_elem.set('mass', f"{inertial['mass']:.6f}")
                inertial_elem.set('fullinertia', f"{inertial['fullinertia'][0]:.6f} {inertial['fullinertia'][1]:.6f} {inertial['fullinertia'][2]:.6f} {inertial['fullinertia'][3]:.6f} {inertial['fullinertia'][4]:.6f} {inertial['fullinertia'][5]:.6f}")
                
                # Добавляем inertial в base_link (после freejoint)
                freejoint = base_link.find('.//freejoint[@name="floating_base"]')
                if freejoint is not None:
                    index = list(base_link).index(freejoint)
                    base_link.insert(index + 1, inertial_elem)
                else:
                    base_link.insert(0, inertial_elem)
                
                print("Добавлены инерциальные параметры для base_link")
            else:
                print("Предупреждение: Не удалось найти base_link для добавления инерциальных параметров")
    
    def _process_body_inertials(self, root: ET.Element) -> None:
        """Обрабатывает инерциальные параметры всех тел."""
        print("Этап 4: Обработка инерциальных параметров тел...")
        
        body_inertials = self.config.get('body_inertials', {})
        
        for body_name, inertial_data in body_inertials.items():
            body = root.find(f'.//body[@name="{body_name}"]')
            if body is not None:
                # Ищем существующий inertial
                existing_inertial = body.find('inertial')
                if existing_inertial is not None:
                    # Обновляем существующий inertial
                    existing_inertial.set('pos', f"{inertial_data['pos'][0]:.6f} {inertial_data['pos'][1]:.6f} {inertial_data['pos'][2]:.6f}")
                    existing_inertial.set('mass', f"{inertial_data['mass']:.6f}")
                    existing_inertial.set('diaginertia', f"{inertial_data['diaginertia'][0]:.6f} {inertial_data['diaginertia'][1]:.6f} {inertial_data['diaginertia'][2]:.6f}")
                    
                    # Добавляем quat если есть
                    if "quat" in inertial_data:
                        quat = inertial_data["quat"]
                        existing_inertial.set('quat', f"{quat[0]:.6f} {quat[1]:.6f} {quat[2]:.6f} {quat[3]:.6f}")
                    
                    print(f"Обновлены инерциальные параметры для {body_name}")
            else:
                print(f"Предупреждение: Не удалось найти тело: {body_name}")
    
    def _process_contact_and_physics(self, root: ET.Element) -> None:
        """Обрабатывает контакты и физические параметры."""
        print("Этап 5: Обработка контактов и физических параметров...")
        
        global_mjcf = self.config.get('global_mjcf', {})
        
        # Добавляем исключения контактов между hip и base_link
        hip_and_base_contact = global_mjcf.get('hip_and_base_contact', False)
        self._add_hip_and_base_contact_exclusions(root, enable_contact=hip_and_base_contact)
        
        # Обновляем группу коллизии для класса collision
        self._update_collision_group(root)
    
    def _add_hip_and_base_contact_exclusions(self, root: ET.Element, enable_contact: bool = False) -> None:
        """Добавляет исключения контактов между hip звеньями и base_link."""
        try:
            if enable_contact:
                print("Контакт между hip и base_link включен - исключения не добавляются")
                return
            
            print("Добавление исключений контактов между hip звеньями и base_link...")
            
            # Ищем или создаем секцию contact
            contact = root.find('.//contact')
            if contact is None:
                print("Секция <contact> не найдена, создаем новую")
                mujoco = root.find('.//mujoco')
                if mujoco is not None:
                    contact = ET.SubElement(mujoco, 'contact')
                else:
                    print("Ошибка: секция <mujoco> не найдена")
                    return
            
            # Список всех hip звеньев
            hip_links = ['hip_bl_link', 'hip_br_link', 'hip_fl_link', 'hip_fr_link']
            
            # Добавляем исключения для hip звеньев
            for hip_link in hip_links:
                exclude_elem = ET.Element('exclude')
                exclude_elem.set('body1', 'base_link')
                exclude_elem.set('body2', hip_link)
                contact.append(exclude_elem)
                print(f"Добавлено исключение: base_link <-> {hip_link}")
            
            print(f"Добавлено {len(hip_links)} исключений контактов")
            
        except Exception as e:
            print(f"Ошибка добавления исключений контактов: {e}")
    
    def _update_collision_group(self, root: ET.Element) -> None:
        """Обновляет группу коллизии для класса collision на 4-ю."""
        try:
            print("Обновление группы коллизии для класса collision...")
            
            # Ищем все default элементы с классом collision
            collision_defaults = root.findall('.//default[@class="collision"]')
            
            if collision_defaults:
                for collision_default in collision_defaults:
                    # Ищем элемент geom внутри default
                    geom = collision_default.find('geom')
                    if geom is not None:
                        # Устанавливаем группу на 4
                        geom.set('group', '4')
                        print("Группа коллизии для класса collision установлена на 4")
                    else:
                        print("Предупреждение: Элемент geom не найден в default[@class='collision']")
            else:
                print("Предупреждение: Класс collision не найден в default секциях")
                
        except Exception as e:
            print(f"Ошибка обновления группы коллизии: {e}")
    
    def _process_actuators_and_keyframes(self, root: ET.Element, joint_limits: Optional[Dict[str, Any]], 
                                        actuator_metadata: Optional[Dict[str, Any]]) -> None:
        """Обрабатывает актуаторы и keyframes."""
        print("Этап 6: Обработка актуаторов и keyframes...")
        
        # Заменяем <motor> на <position> в актуаторах
        ActuatorProcessor.replace_motor_tags_with_position(root, actuator_metadata)
        
        # Применяем угловые ограничения к актуаторам
        global_mjcf = self.config.get('global_mjcf', {})
        apply_joint_limits = global_mjcf.get('apply_joint_limits', True)
        
        if joint_limits and apply_joint_limits:
            print("Применение угловых ограничений к актуаторам включено")
            ActuatorProcessor.apply_joint_limits_to_actuators(root, joint_limits)
        elif joint_limits and not apply_joint_limits:
            print("Применение угловых ограничений к актуаторам отключено в конфигурации")
        else:
            print("Угловые ограничения не загружены")
        
        # Загружаем и добавляем keyframes
        keyframes_config = self.config.get('keyframes', {})
        if keyframes_config:
            print(f"Найдено {len(keyframes_config)} keyframes для добавления")
            self._add_keyframes_to_mjcf(root, keyframes_config)
        else:
            print("Keyframes не загружены, пропускаем добавление")
    
    def _add_keyframes_to_mjcf(self, root: ET.Element, keyframes_config: Dict[str, Any]) -> None:
        """Добавляет keyframes в MJCF файл."""
        try:
            if not keyframes_config:
                print("Конфигурация keyframes не загружена, пропускаем добавление")
                return
            
            print("Добавление keyframes в MJCF...")
            
            # Проверяем корневой элемент
            if root.tag != 'mujoco':
                print(f"Ошибка: корневой элемент имеет тег '{root.tag}', ожидается 'mujoco'")
                return
            
            # Ищем или создаем секцию keyframe
            keyframe_section = root.find('.//keyframe')
            if keyframe_section is None:
                print("Секция <keyframe> не найдена, создаем новую")
                keyframe_section = ET.SubElement(root, 'keyframe')
            
            # Очищаем существующие ключи
            for existing_key in keyframe_section.findall('key'):
                keyframe_section.remove(existing_key)
            
            # Добавляем каждый keyframe из конфигурации
            for key_name, key_data in keyframes_config.items():
                key_elem = ET.Element('key')
                key_elem.set('name', key_name)
                
                # Добавляем qpos если есть
                if 'qpos' in key_data:
                    qpos_str = ' '.join([f"{val:.6f}" for val in key_data['qpos']])
                    key_elem.set('qpos', qpos_str)
                    print(f"Добавлен qpos для keyframe '{key_name}': {len(key_data['qpos'])} значений")
                
                # Добавляем qvel если есть
                if 'qvel' in key_data:
                    qvel_str = ' '.join([f"{val:.6f}" for val in key_data['qvel']])
                    key_elem.set('qvel', qvel_str)
                    print(f"Добавлен qvel для keyframe '{key_name}': {len(key_data['qvel'])} значений")
                
                # Добавляем ctrl если есть
                if 'ctrl' in key_data:
                    ctrl_str = ' '.join([f"{val:.6f}" for val in key_data['ctrl']])
                    key_elem.set('ctrl', ctrl_str)
                    print(f"Добавлен ctrl для keyframe '{key_name}': {len(key_data['ctrl'])} значений")
                
                # Добавляем time если есть
                if 'time' in key_data:
                    key_elem.set('time', f"{key_data['time']:.6f}")
                    print(f"Добавлен time для keyframe '{key_name}': {key_data['time']}")
                
                keyframe_section.append(key_elem)
                print(f"Добавлен keyframe: {key_name}")
            
            print(f"Добавлено {len(keyframes_config)} keyframes")
            
        except Exception as e:
            print(f"Ошибка добавления keyframes: {e}")
    
    def _process_ordering_and_sensors(self, root: ET.Element) -> None:
        """Обрабатывает упорядочивание и сенсоры."""
        print("Этап 7: Обработка упорядочивания и сенсоров...")
        
        # Сортируем тела ног в секции worldbody в порядке FL -> FR -> BL -> BR
        self._sort_leg_bodies_in_worldbody(root)
        
        # Сортируем актуаторы ног в секции actuator в порядке FL -> FR -> BL -> BR
        self._sort_leg_actuators(root)
        
        # Добавляем недостающие базовые сенсоры
        SensorManager.add_base_sensors(root, self.config)
        
        # Добавляем сайты для ног
        self._add_foot_sites_to_worldbody(root)
        
        # Добавляем сенсоры для ног
        SensorManager.add_foot_sensors(root, self.config)
        
        # Удаляем дублирующиеся сенсоры
        SensorManager.remove_duplicate_sensors(root)
    
    def _sort_leg_bodies_in_worldbody(self, root: ET.Element) -> None:
        """Сортирует тела ног в секции worldbody в порядке FL -> FR -> BL -> BR."""
        try:
            print("Сортировка тел ног в worldbody в порядке FL -> FR -> BL -> BR...")
            
            # Ищем base_link в worldbody
            base_link = root.find('.//worldbody//body[@name="base_link"]')
            if base_link is None:
                print("base_link не найден в worldbody, сортировка ног невозможна")
                return
            
            # Собираем все тела ног
            leg_bodies = []
            other_bodies = []
            
            for body_elem in base_link.findall('body'):
                body_name = body_elem.get('name', '')
                
                # Определяем к какой ноге относится тело
                if 'leg_block_fl' in body_name:
                    leg_bodies.append(('FL', body_elem))
                elif 'leg_block_fr' in body_name:
                    leg_bodies.append(('FR', body_elem))
                elif 'leg_block_bl' in body_name:
                    leg_bodies.append(('BL', body_elem))
                elif 'leg_block_br' in body_name:
                    leg_bodies.append(('BR', body_elem))
                else:
                    # Не ножное тело
                    other_bodies.append(body_elem)
            
            # Сортируем ножные тела по порядку: FL -> FR -> BL -> BR
            leg_order = ['FL', 'FR', 'BL', 'BR']
            sorted_leg_bodies = []
            
            for leg_type in leg_order:
                for leg_body in leg_bodies:
                    if leg_body[0] == leg_type:
                        sorted_leg_bodies.append(leg_body[1])
                        break
            
            print(f"Найдено {len(leg_bodies)} тел ног")
            print(f"Найдено {len(other_bodies)} других тел")
            print(f"Отсортировано {len(sorted_leg_bodies)} тел ног")
            
            # Очищаем base_link от всех тел
            for body_elem in list(base_link.findall('body')):
                base_link.remove(body_elem)
            
            # Добавляем отсортированные ножные тела
            for leg_body in sorted_leg_bodies:
                base_link.append(leg_body)
            
            # Добавляем остальные тела
            for other_body in other_bodies:
                base_link.append(other_body)
            
            print("Сортировка тел ног в worldbody завершена успешно")
            
        except Exception as e:
            print(f"Ошибка сортировки тел ног в worldbody: {e}")
    
    def _sort_leg_actuators(self, root: ET.Element) -> None:
        """Сортирует актуаторы ног в секции actuator в том же порядке, что и тела ног."""
        try:
            print("Сортировка актуаторов ног в порядке FL -> FR -> BL -> BR...")
            
            # Ищем секцию actuator
            actuator = root.find('.//actuator')
            if actuator is None:
                print("Секция <actuator> не найдена, сортировка актуаторов невозможна")
                return
            
            # Собираем все актуаторы для ног
            leg_actuators = []
            other_actuators = []
            
            for actuator_elem in actuator.findall('*'):
                joint_name = actuator_elem.get('joint', '')
                
                # Определяем к какой ноге относится актуатор
                if 'leg_block_fl' in joint_name or 'hip_fl' in joint_name or 'shin_fl' in joint_name:
                    leg_actuators.append(('FL', actuator_elem))
                elif 'leg_block_fr' in joint_name or 'hip_fr' in joint_name or 'shin_fr' in joint_name:
                    leg_actuators.append(('FR', actuator_elem))
                elif 'leg_block_bl' in joint_name or 'hip_bl' in joint_name or 'shin_bl' in joint_name:
                    leg_actuators.append(('BL', actuator_elem))
                elif 'leg_block_br' in joint_name or 'hip_br' in joint_name or 'shin_br' in joint_name:
                    leg_actuators.append(('BR', actuator_elem))
                else:
                    # Не ножной актуатор
                    other_actuators.append(actuator_elem)
            
            # Сортируем ножные актуаторы по порядку ног: FL -> FR -> BL -> BR
            leg_order = ['FL', 'FR', 'BL', 'BR']
            sorted_leg_actuators = []
            
            for leg_type in leg_order:
                # Находим все актуаторы для данной ноги
                for leg_actuator in leg_actuators:
                    if leg_actuator[0] == leg_type:
                        sorted_leg_actuators.append(leg_actuator[1])
            
            print(f"Найдено {len(leg_actuators)} ножных актуаторов")
            print(f"Найдено {len(other_actuators)} других актуаторов")
            print(f"Отсортировано {len(sorted_leg_actuators)} ножных актуаторов")
            
            # Очищаем секцию actuator
            for elem in list(actuator):
                actuator.remove(elem)
            
            # Добавляем отсортированные ножные актуаторы
            for leg_actuator in sorted_leg_actuators:
                actuator.append(leg_actuator)
            
            # Добавляем остальные актуаторы
            for other_actuator in other_actuators:
                actuator.append(other_actuator)
            
            print("Сортировка актуаторов ног завершена успешно")
            
        except Exception as e:
            print(f"Ошибка сортировки актуаторов ног: {e}")
    
    def _add_foot_sites_to_worldbody(self, root: ET.Element) -> None:
        """Добавляет сайты для каждой ноги в worldbody."""
        try:
            print("Добавление сайтов для ног...")
            
            # Находим все тела ног автоматически
            all_bodies = root.findall('.//body')
            foot_bodies = [body for body in all_bodies 
                          if body.get('name', '').startswith('foot_') and body.get('name', '').endswith('_link')]
            
            for foot_body in foot_bodies:
                foot_body_name = foot_body.get('name')
                # Извлекаем префикс ноги (foot_fr, foot_fl, etc.)
                foot_prefix = foot_body_name.replace('_link', '')
                site_name = f"{foot_prefix}_site"
                
                # Проверяем, есть ли уже сайт
                existing_site = foot_body.find(f'.//site[@name="{site_name}"]')
                if existing_site is None:
                    # Ищем геометрию коллизии для извлечения параметров
                    collision_geom = foot_body.find('.//geom[@class="collision"]')
                    if collision_geom is not None:
                        # Извлекаем параметры из геометрии коллизии
                        site_pos = collision_geom.get('pos')
                        site_type = collision_geom.get('type')
                        site_size = collision_geom.get('size')
                        site_quat = collision_geom.get('quat')
                        
                        # Проверяем, что все необходимые параметры найдены
                        if site_pos is not None and site_type is not None and site_size is not None:
                            # Создаем сайт с параметрами из геометрии коллизии
                            site_elem = ET.Element('site')
                            site_elem.set('name', site_name)
                            site_elem.set('pos', site_pos)
                            site_elem.set('type', site_type)
                            site_elem.set('size', site_size)
                            if site_quat is not None:
                                site_elem.set('quat', site_quat)
                            site_elem.set('group', '5')
                            
                            # Добавляем сайт в тело ноги
                            foot_body.append(site_elem)
                            print(f"Добавлен сайт {site_name} в {foot_body_name} (тип: {site_type}, размер: {site_size})")
                        else:
                            print(f"Ошибка: Неполные параметры геометрии коллизии для {foot_body_name}")
                    else:
                        print(f"Ошибка: Геометрия коллизии не найдена для {foot_body_name}, сайт не создан")
                else:
                    print(f"Сайт {site_name} уже существует в {foot_body_name}")
            
            print(f"Добавление сайтов для ног завершено. Обработано {len(foot_bodies)} ног")
            
        except Exception as e:
            print(f"Ошибка добавления сайтов для ног: {e}")
    
    def _save_processed_mjcf(self, root: ET.Element, mjcf_path: str) -> None:
        """Сохраняет обработанный MJCF файл."""
        print("Этап 8: Сохранение обработанного MJCF...")
        
        # Конвертируем обратно в строку
        mjcf_content = ET.tostring(root, encoding='unicode', method='xml')
        
        # Форматируем XML для красивого вывода
        mjcf_content = XMLFormatter.pretty_print_xml(mjcf_content)
        
        # Записываем обновленный MJCF файл
        with open(mjcf_path, 'w', encoding='utf-8') as f:
            f.write(mjcf_content)
        
        print("Постобработка MJCF завершена успешно")
