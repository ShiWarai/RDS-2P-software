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

from rds_2p_commands.action_handlers.robot_routine_handler import RobotRoutineHandler

# Имя «слота» для единственного PandaCommand (совпадает с command_parser_node.PANDA_GOAL_CLASS).
PANDA_ACTION_SLOT = 'motors'


class UnifiedActionServer(Node):
    """Универсальный Action сервер для нескольких типов действий."""

    def __init__(self):
        super().__init__('unified_action_server')
        
        self.declare_parameter('commands_config', 'commands.yaml')

        self._action_servers: Dict[str, ActionServer] = {}

        # Отслеживание активных действий по классам
        self._active_goals_by_class: Dict[str, list] = {}

        # Один PandaCommand-сервер → один слот активных целей
        self._action_classes: Dict[str, str] = {'/robot/panda_command': PANDA_ACTION_SLOT}

        # Параметр: разрешить ли параллельное выполнение команд одного слота
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
    
    def _register_actions(self):
        """Регистрация всех действий. Добавьте сюда свои действия!"""
        
        rr = RobotRoutineHandler(self)
        self.register_action(
            action_type='rds_2p_commands/action/PandaCommand',
            action_name='/robot/panda_command',
            handler=rr,
            command_info={
                'name': 'panda_command',
                'display_name': 'Команды Panda',
                'parser': 'routine_id',
                'class': 'motors',
                'keywords': ['лапу', 'лежать', 'равняйсь', 'смирно', 'служить'],
                'parameters': {'type': 'string', 'name': 'routine_id', 'description': 'give_paw, lie_down, ...'},
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
            
            # Обертываем callback: без параллели — отменяем предыдущую цель того же слота
            def wrapped_callback(goal_handle):
                slot = self._action_classes.get(action_name, 'default')

                if not self.allow_parallel_same_class:
                    active_goals = self._active_goals_by_class.get(slot, [])
                    if active_goals:
                        for old_gh in active_goals[:]:
                            self.get_logger().info(
                                f'Отмена предыдущей цели (слот "{slot}") перед новой'
                            )
                            try:
                                old_gh.abort()
                            except Exception as e:
                                self.get_logger().warn(f'Ошибка при отмене предыдущей цели: {e}')
                            self._unregister_active_goal(slot, old_gh)

                self._register_active_goal(slot, goal_handle)
                try:
                    return original_callback(goal_handle)
                finally:
                    self._unregister_active_goal(slot, goal_handle)
            
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
            cfg_name = (
                self.get_parameter('commands_config').get_parameter_value().string_value
            )
            cmd_map: Dict[str, Any] = {}
            try:
                package_share_dir = get_package_share_directory('rds_2p_commands')
                config_path = Path(package_share_dir) / 'config' / cfg_name
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        doc = yaml.safe_load(f) or {}
                    cmd_map = doc.get('commands', {})
                else:
                    self.get_logger().warn(f'Файл команд не найден: {config_path}')
            except Exception as e:
                self.get_logger().warn(f'Не удалось загрузить {cfg_name}: {e}')

            commands_out = []
            for action_name in self._action_servers:
                if action_name != '/robot/panda_command':
                    commands_out.append({
                        'name': action_name.split('/')[-1],
                        'action_name': action_name,
                        'action_type': 'unknown',
                        'keywords': [],
                        'class': self._action_classes.get(action_name, 'default'),
                    })
                    continue
                for cmd_name, cmd_cfg in cmd_map.items():
                    commands_out.append({
                        'name': cmd_name,
                        'display_name': cmd_name,
                        'action_name': action_name,
                        'action_type': 'rds_2p_commands/action/PandaCommand',
                        'routine_id': cmd_name,
                        'parser': 'routine_id',
                        'class': PANDA_ACTION_SLOT,
                        'keywords': cmd_cfg.get('keywords', []),
                        'parameters': {
                            'type': 'string',
                            'name': 'routine_id',
                            'description': 'ключ команды из commands.yaml',
                        },
                    })

            message = {
                'server_name': 'unified_action_server',
                'server_namespace': '/',
                'commands': commands_out,
            }

            msg = String()
            msg.data = json.dumps(message, ensure_ascii=False)
            self._commands_publisher.publish(msg)

            self.get_logger().debug(
                f'Опубликован список из {len(commands_out)} команд в {self._commands_topic}'
            )

        except Exception as e:
            self.get_logger().error(f'Ошибка при публикации списка команд: {e}')
            import traceback
            traceback.print_exc()


def main(args=None):
    """Главная функция для запуска узла."""
    from rclpy.executors import MultiThreadedExecutor

    rclpy.init(args=args)

    try:
        unified_server = UnifiedActionServer()
        executor = MultiThreadedExecutor(num_threads=6)
        executor.add_node(unified_server)
        executor.spin()
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
