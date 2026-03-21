#!/usr/bin/env python3
"""Универсальный Action сервер для поддержки нескольких типов действий.

Просто добавляйте свои функции-обработчики действий в этот файл!
"""

import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer
from typing import Dict, Any, Optional
import importlib
import yaml
import json
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from std_msgs.msg import String

# Импортируем обработчики действий
from rds_2p_commands.action_handlers.say_handler import SayHandler


class UnifiedActionServer(Node):
    """Универсальный Action сервер для нескольких типов действий."""

    def __init__(self):
        super().__init__('unified_action_server')
        
        self._action_servers: Dict[str, ActionServer] = {}
        
        # Отслеживание активных действий по классам
        # {class_name: [goal_handle1, goal_handle2, ...]}
        self._active_goals_by_class: Dict[str, list] = {}
        
        # Маппинг action_name -> class (загружается из command_mappings.yaml)
        self._action_classes: Dict[str, str] = {}
        
        # Свойства классов (приоритет, таймаут, поведение)
        self._class_properties: Dict[str, Dict[str, Any]] = {}
        
        # Загрузка конфигурации
        self._load_command_mappings_config()  # Загружаем классы из command_mappings.yaml
        self._load_class_properties_config()  # Загружаем свойства классов
        
        # Параметр: разрешить ли параллельное выполнение действий одного класса
        self.declare_parameter('allow_parallel_same_class', False)
        self.allow_parallel_same_class = self.get_parameter('allow_parallel_same_class').get_parameter_value().bool_value
        
        # Параметры для публикации списка команд
        self.declare_parameter('commands_topic', '/commands')
        self.declare_parameter('commands_publish_rate', 0.1)  # 1 раз в 10 секунд
        
        commands_topic = self.get_parameter('commands_topic').get_parameter_value().string_value
        commands_publish_rate = self.get_parameter('commands_publish_rate').get_parameter_value().double_value
        
        # Публикатор списка команд
        self._commands_publisher = self.create_publisher(String, commands_topic, 10)
        self._commands_publish_rate = commands_publish_rate
        self._commands_topic = commands_topic
        
        # Таймер для периодической публикации (если rate > 0)
        if commands_publish_rate > 0:
            timer_period = 1.0 / commands_publish_rate if commands_publish_rate > 0 else 10.0
            self._commands_timer = self.create_timer(timer_period, self._publish_command_list)
        
        # Хранилище информации о командах для публикации
        self._command_info: Dict[str, Dict[str, Any]] = {}
        
        self.get_logger().info('Unified Action Server инициализирован')
        
        # Регистрируем действия
        self._register_actions()
        
        # Публикуем начальный список команд
        self._publish_command_list()
    
    def _load_command_mappings_config(self):
        """Загрузка классов действий из command_mappings.yaml."""
        try:
            package_share_dir = get_package_share_directory('rds_2p_commands')
            config_path = Path(package_share_dir) / 'config' / 'command_mappings.yaml'
            
            if not config_path.exists():
                self.get_logger().warn(f'Конфигурация команд не найдена: {config_path}')
                return
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            commands_config = config.get('commands', {})
            for command_name, command_config in commands_config.items():
                action_name = command_config.get('action_name')
                command_class = command_config.get('class', 'default')
                
                if action_name:
                    self._action_classes[action_name] = command_class
            
            self.get_logger().info(f'Загружены классы для {len(self._action_classes)} действий из command_mappings.yaml')
            
        except Exception as e:
            self.get_logger().error(f'Ошибка при загрузке конфигурации команд: {e}')
    
    def _load_class_properties_config(self):
        """Загрузка свойств классов из action_classes.yaml."""
        try:
            package_share_dir = get_package_share_directory('rds_2p_commands')
            config_path = Path(package_share_dir) / 'config' / 'action_classes.yaml'
            
            if not config_path.exists():
                self.get_logger().warn(f'Конфигурация свойств классов не найдена: {config_path}')
                return
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            classes_config = config.get('classes', {})
            for class_name, class_props in classes_config.items():
                self._class_properties[class_name] = {
                    'priority': class_props.get('priority', 0),
                    'cancel_timeout': class_props.get('cancel_timeout', 0.0),
                    'conflict_behavior': class_props.get('conflict_behavior', 'reject')
                }
            
            self.get_logger().info(f'Загружены свойства для {len(self._class_properties)} классов')
            
        except Exception as e:
            self.get_logger().error(f'Ошибка при загрузке свойств классов: {e}')
    
    def _register_actions(self):
        """Регистрация всех действий. Добавьте сюда свои действия!"""
        
        # ============================================
        # ДЕЙСТВИЕ 1: Say (пример кастомного действия)
        # ============================================
        self.register_action(
            action_type='rds_2p_commands/action/Say',
            action_name='/say',
            handler=SayHandler(self),
            command_info={
                'name': 'say',
                'display_name': 'Сказать',
                'parser': 'extract_text',
                'class': 'audio_output',
                'keywords': ['say', 'скажи', 'сказать', 'произнести'],
                'parameters': {
                    'type': 'string',
                    'name': 'text',
                    'description': 'Текст для вывода'
                }
            }
        )
        
        # ============================================
        # ДОБАВЬТЕ СВОИ ДЕЙСТВИЯ ЗДЕСЬ:
        # ============================================
        # Пример 1: Простая функция-обработчик
        # self.register_action(
        #     action_type='your_package/action/YourAction',
        #     action_name='/your/action',
        #     handler=self.handle_your_action  # Просто метод этого класса!
        # )
        #
        # Пример 2: Класс-обработчик (как DanceHandler)
        # from rds_2p_commands.action_handlers.your_handler import YourHandler
        # self.register_action(
        #     action_type='your_package/action/YourAction',
        #     action_name='/your/action',
        #     handler=YourHandler(self)
        # )
        
        self.get_logger().info(f'Зарегистрировано действий: {len(self._action_servers)}')
    
    # ============================================
    # ПРИМЕР: Простая функция-обработчик действия
    # ============================================
    # Раскомментируйте и адаптируйте под ваше действие:
    #
    # def handle_your_action(self, goal_handle):
    #     """Пример обработчика действия."""
    #     # Получаем параметры из goal
    #     param = goal_handle.request.some_param
    #     
    #     self.get_logger().info(f'Выполняю действие с параметром: {param}')
    #     
    #     # Ваша логика здесь
    #     # ...
    #     
    #     # Проверка на отмену
    #     if goal_handle.is_cancel_requested:
    #         goal_handle.canceled()
    #         from your_package.action import YourAction
    #         return YourAction.Result(success=False, message='Отменено')
    #     
    #     # Завершаем успешно
    #     goal_handle.succeed()
    #     from your_package.action import YourAction
    #     return YourAction.Result(success=True, message='Выполнено')
    
    def register_action(
        self,
        action_type: str,
        action_name: str,
        handler: Any,
        command_info: Optional[Dict[str, Any]] = None
    ):
        """
        Регистрация действия.
        
        Args:
            action_type: Тип Action (например, 'rds_2p_dance/action/PlayDance')
            action_name: Имя Action сервера (например, '/dance/play')
            handler: Обработчик действия (объект с методом execute_callback или функция)
        """
        try:
            # Динамически импортируем Action тип
            module_path, class_name = action_type.rsplit('/', 1)
            package_name = module_path.replace('/', '.')
            
            action_module = importlib.import_module(package_name)
            action_class = getattr(action_module, class_name)
            
            # Определяем callback функцию
            if hasattr(handler, 'execute_callback'):
                # Если handler - объект с методом execute_callback
                original_callback = handler.execute_callback
            elif callable(handler):
                # Если handler - функция
                original_callback = handler
            else:
                raise ValueError(f'Handler должен быть функцией или объектом с методом execute_callback')
            
            # Обертываем callback для проверки классов команд
            def wrapped_callback(goal_handle):
                # Определяем класс действия
                action_class = self._action_classes.get(action_name, 'default')
                class_props = self._class_properties.get(action_class, {
                    'priority': 0,
                    'cancel_timeout': 0.0,
                    'conflict_behavior': 'reject'
                })
                
                # Проверяем конфликты с активными действиями того же класса
                if not self.allow_parallel_same_class:
                    active_goals = self._active_goals_by_class.get(action_class, [])
                    if active_goals:
                        conflict_behavior = class_props['conflict_behavior']
                        new_priority = class_props['priority']
                        
                        if conflict_behavior == 'cancel_previous':
                            # Отменяем предыдущие команды с меньшим или равным приоритетом
                            cancel_timeout = class_props['cancel_timeout']
                            for old_goal_handle in active_goals[:]:  # Копируем список для безопасной итерации
                                # Получаем приоритет старой команды
                                old_action_name = None
                                for name, cls in self._action_classes.items():
                                    if cls == action_class:
                                        # Находим action_name для старого goal (упрощенно)
                                        old_action_name = name
                                        break
                                
                                old_class_props = self._class_properties.get(action_class, {'priority': 0})
                                old_priority = old_class_props['priority']
                                
                                if new_priority >= old_priority:
                                    self.get_logger().info(
                                        f'Отменяю предыдущее действие класса "{action_class}" '
                                        f'(приоритет: {old_priority} < {new_priority})'
                                    )
                                    # В ROS2 Action Server для прерывания выполнения цели используем abort()
                                    # Обработчик должен проверять is_cancel_requested и корректно завершаться
                                    try:
                                        old_goal_handle.abort()
                                    except Exception as e:
                                        self.get_logger().warn(f'Ошибка при отмене предыдущей цели: {e}')
                                    self._unregister_active_goal(action_class, old_goal_handle)
                        
                        elif conflict_behavior == 'reject':
                            # Отклоняем новую команду
                            self.get_logger().warn(
                                f'Действие {action_name} (класс "{action_class}") отклонено: '
                                f'уже выполняется {len(active_goals)} действие(й) того же класса'
                            )
                            goal_handle.abort()
                            return None
                        
                        elif conflict_behavior == 'queue':
                            # Можно реализовать очередь в будущем
                            self.get_logger().warn(
                                f'Действие {action_name} (класс "{action_class}") поставлено в очередь'
                            )
                            # Пока просто отклоняем
                            goal_handle.abort()
                            return None
                
                # Регистрируем активное действие
                self._register_active_goal(action_class, goal_handle)
                
                # Вызываем оригинальный callback
                try:
                    result = original_callback(goal_handle)
                    return result
                finally:
                    # Удаляем из активных при завершении (в любом случае)
                    self._unregister_active_goal(action_class, goal_handle)
            
            # Создаем Action сервер с обернутым callback
            action_server = ActionServer(
                self,
                action_class,
                action_name,
                wrapped_callback
            )
            
            self._action_servers[action_name] = action_server
            
            # Сохраняем информацию о команде для публикации
            if command_info:
                self._command_info[action_name] = command_info
                # Добавляем action_name и action_type в command_info
                command_info['action_name'] = action_name
                command_info['action_type'] = action_type
            
            self.get_logger().info(
                f'✓ Зарегистрировано действие: {action_name} ({action_type})'
            )
            
            # Публикуем обновленный список команд
            self._publish_command_list()
            
        except Exception as e:
            self.get_logger().error(
                f'✗ Ошибка при регистрации действия {action_name}: {e}'
            )
            import traceback
            traceback.print_exc()
    
    def _register_active_goal(self, action_class: str, goal_handle):
        """Регистрация активного goal по классу действия."""
        if action_class not in self._active_goals_by_class:
            self._active_goals_by_class[action_class] = []
        self._active_goals_by_class[action_class].append(goal_handle)
        self.get_logger().debug(
            f'Зарегистрировано активное действие класса "{action_class}" '
            f'(всего активных: {len(self._active_goals_by_class[action_class])})'
        )
    
    def _unregister_active_goal(self, action_class: str, goal_handle):
        """Удаление завершенного goal из активных."""
        if action_class in self._active_goals_by_class:
            if goal_handle in self._active_goals_by_class[action_class]:
                self._active_goals_by_class[action_class].remove(goal_handle)
            if len(self._active_goals_by_class[action_class]) == 0:
                del self._active_goals_by_class[action_class]
        self.get_logger().debug(
            f'Удалено активное действие класса "{action_class}"'
        )
    
    def _publish_command_list(self):
        """Публикует список доступных команд в JSON формате."""
        try:
            # Загружаем конфигурацию команд для получения дополнительной информации
            command_mappings = {}
            try:
                package_share_dir = get_package_share_directory('rds_2p_commands')
                config_path = Path(package_share_dir) / 'config' / 'command_mappings.yaml'
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                        command_mappings = config.get('commands', {})
            except Exception as e:
                self.get_logger().warn(f'Не удалось загрузить command_mappings.yaml: {e}')
            
            # Формируем список команд из зарегистрированных действий
            commands = []
            for action_name, action_server in self._action_servers.items():
                # Ищем информацию о команде в конфиге
                command_config = None
                for cmd_name, cmd_cfg in command_mappings.items():
                    if cmd_cfg.get('action_name') == action_name:
                        command_config = cmd_cfg
                        command_name = cmd_name
                        break
                
                if not command_config:
                    # Если команда не найдена в конфиге, используем базовую информацию
                    command_name = action_name.split('/')[-1]  # Извлекаем имя из пути
                    command_config = {}
                
                # Формируем информацию о команде
                command_info = {
                    'name': command_name,
                    'display_name': command_config.get('display_name', command_name.capitalize()),
                    'action_name': action_name,
                    'action_type': command_config.get('action_type', 'unknown'),
                    'parser': command_config.get('parser', 'none'),
                    'class': command_config.get('class', 'default'),
                    'keywords': command_config.get('keywords', []),
                }
                
                # Добавляем информацию о параметрах, если есть
                if command_config.get('parser') == 'extract_number':
                    # Для команд с числовыми параметрами
                    command_info['parameters'] = {
                        'type': 'number',
                        'name': f'{command_name}_number',
                        'parser': 'extract_number'
                    }
                    # Если это команда dance, пытаемся определить доступные значения
                    if command_name == 'dance':
                        # Попробуем получить информацию о доступных танцах из rds_2p_dance
                        # Пока используем значения по умолчанию
                        command_info['parameters']['min'] = 1
                        command_info['parameters']['max'] = 10
                
                commands.append(command_info)
            
            # Формируем JSON сообщение
            message = {
                'server_name': 'unified_action_server',
                'server_namespace': '/',
                'commands': commands
            }
            
            # Публикуем
            msg = String()
            msg.data = json.dumps(message, ensure_ascii=False)
            self._commands_publisher.publish(msg)
            
            self.get_logger().debug(f'Опубликован список из {len(commands)} команд в {self._commands_topic}')
            
        except Exception as e:
            self.get_logger().error(f'Ошибка при публикации списка команд: {e}')
            import traceback
            traceback.print_exc()


def main(args=None):
    """Главная функция для запуска узла."""
    rclpy.init(args=args)
    
    try:
        unified_server = UnifiedActionServer()
        rclpy.spin(unified_server)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'\nОшибка: {e}')
        import traceback
        traceback.print_exc()
    finally:
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
