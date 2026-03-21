#!/usr/bin/env python3
"""Нода для парсинга команд из Telegram и голосовых расшифровок.

Поддерживает два режима обработки:
1. CVC классификатор команд (основной)
2. Парсинг по ключевым словам (fallback)
"""

import re
import json
import yaml
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from std_msgs.msg import String
from vosk_ros2.msg import Transcription
from rds_2p_dance.action import PlayDance
from rds_2p_commands.action import Say
from pathlib import Path
from typing import Dict, Optional, Any, Callable
from ament_index_python.packages import get_package_share_directory

from rds_2p_commands.cvc_client import CVCClient


class CommandParserNode(Node):
    """Нода для парсинга и обработки команд."""

    def __init__(self):
        super().__init__('command_parser')
        
        # Параметры CVC
        self.declare_parameter('cvc_enabled', True)
        self.declare_parameter('cvc_url', 'http://localhost:8000')
        self.declare_parameter('cvc_confidence_threshold', 0.7)
        self.declare_parameter('cvc_timeout', 2.0)
        self.declare_parameter('config_file', 'command_mappings.yaml')
        
        self.cvc_enabled = self.get_parameter('cvc_enabled').get_parameter_value().bool_value
        cvc_url = self.get_parameter('cvc_url').get_parameter_value().string_value
        self.cvc_confidence_threshold = self.get_parameter('cvc_confidence_threshold').get_parameter_value().double_value
        cvc_timeout = self.get_parameter('cvc_timeout').get_parameter_value().double_value
        
        # Инициализация CVC клиента
        self.cvc_client = None
        if self.cvc_enabled:
            self.cvc_client = CVCClient(base_url=cvc_url, timeout=cvc_timeout)
            if self.cvc_client.check_health():
                self.get_logger().info(f'CVC классификатор подключен: {cvc_url}')
            else:
                self.get_logger().warn(f'CVC классификатор недоступен: {cvc_url}, используется fallback парсинг')
                self.cvc_enabled = False
        
        # Загрузка конфигурации команд (только команды, CVC настройки уже в параметрах)
        self.command_config = self._load_command_config()
        
        # Регистрация обработчиков команд
        self.command_handlers: Dict[str, Callable] = {}
        self._register_command_handlers()
        
        # Отслеживание активных команд по классам
        # {class_name: [goal_handle1, goal_handle2, ...]}
        self._active_goals_by_class: Dict[str, list] = {}
        
        # Параметр: разрешить ли параллельное выполнение команд одного класса
        self.declare_parameter('allow_parallel_same_class', False)
        self.allow_parallel_same_class = self.get_parameter('allow_parallel_same_class').get_parameter_value().bool_value
        
        # Параметр: список топиков транскрипции для подписки
        self.declare_parameter('transcription_topics', ['/audio/transcription'])
        transcription_topics_param = self.get_parameter('transcription_topics').get_parameter_value().string_array_value
        if not transcription_topics_param:
            transcription_topics_param = ['/audio/transcription']
        
        # Подписки на источники команд
        self.telegram_sub = self.create_subscription(
            String,
            '/telegram/message',
            self.telegram_callback,
            10
        )
        
        # Подписки на топики транскрипции (может быть несколько)
        self.voice_subs = []
        for topic in transcription_topics_param:
            sub = self.create_subscription(
                Transcription,
                topic,
                self.voice_callback,
                10
            )
            self.voice_subs.append(sub)
            self.get_logger().info(f'Подписка на топик транскрипции: {topic}')
        
        # Action клиенты
        self.dance_action_client = ActionClient(self, PlayDance, '/dance/play')
        self.say_action_client = ActionClient(self, Say, '/say')
        
        # Хранилище активных goal handles для отмены
        self._active_goal_handles: Dict[str, list] = {}  # {action_name: [goal_handle1, ...]}
        
        self.get_logger().info('Command Parser Node запущен')
        self.get_logger().info(f'CVC классификатор: {"включен" if self.cvc_enabled else "выключен"}')
    
    def _load_command_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации команд из YAML файла."""
        try:
            config_file = self.get_parameter('config_file').get_parameter_value().string_value
            package_share_dir = get_package_share_directory('rds_2p_commands')
            config_path = Path(package_share_dir) / 'config' / config_file
            
            if not config_path.exists():
                self.get_logger().warn(f'Конфигурационный файл не найден: {config_path}, используются значения по умолчанию')
                return self._get_default_config()
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            self.get_logger().info(f'Конфигурация загружена из {config_path}')
            return config
            
        except Exception as e:
            self.get_logger().error(f'Ошибка при загрузке конфигурации: {e}')
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Возвращает конфигурацию по умолчанию (только команды, CVC настройки из параметров ROS2)."""
        return {
            'commands': {
                'dance': {
                    'keywords': ['dance', 'play', 'танцуй'],
                    'cvc_command': 'dance',
                    'action_type': 'rds_2p_dance/action/PlayDance',
                    'action_name': '/dance/play',
                    'parser': 'extract_number',
                    'class': 'motors'
                }
            }
        }
    
    def _register_command_handlers(self):
        """Регистрация обработчиков команд."""
        # Регистрируем обработчик для танца
        self.command_handlers['dance'] = self.handle_dance_command
        
        # Регистрируем обработчик для say (пример кастомного действия)
        self.command_handlers['say'] = self.handle_say_command
        
        # Можно добавить другие обработчики здесь
        # self.command_handlers['move'] = self.handle_move_command
    
    def telegram_callback(self, msg: String):
        """Обработка команд из Telegram."""
        if not msg.data:
            return
        
        text = msg.data
        
        # Проверяем специальные команды отмены
        text_lower = text.strip().lower()
        if text_lower == 'cancel' or text_lower == 'stop' or text_lower == 'отмена':
            self._handle_cancel_command('telegram')
            return
        
        # Игнорируем специальные JSON сообщения (auth_request и другие системные)
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'type' in data:
                message_type = data.get('type')
                # Игнорируем системные сообщения
                if message_type in ['auth_request']:
                    self.get_logger().debug(f'Игнорировано системное сообщение типа: {message_type}')
                    return
        except (json.JSONDecodeError, ValueError):
            # Не JSON, обрабатываем как обычную команду
            pass
        
        # Обрабатываем как обычную команду
        self.process_command(text, source='telegram')
    
    def voice_callback(self, msg: Transcription):
        """Обработка команд из голосовых расшифровок."""
        if msg.text:
            self.process_command(msg.text, source='voice')
    
    def _handle_cancel_command(self, source: str):
        """Обрабатывает команду отмены всех активных действий."""
        cancelled_count = 0
        
        # Отменяем все активные цели через Action клиенты
        for action_name, goal_handles in self._active_goal_handles.items():
            for goal_handle in goal_handles[:]:  # Копируем список
                try:
                    # Отправляем запрос на отмену через Action Client
                    from action_msgs.msg import GoalInfo
                    goal_info = GoalInfo()
                    goal_info.goal_id = goal_handle.goal_id
                    
                    try:
                        if action_name == '/dance/play':
                            future = self.dance_action_client.cancel_goal_async(goal_info)
                            cancelled_count += 1
                        elif action_name == '/say':
                            future = self.say_action_client.cancel_goal_async(goal_info)
                            cancelled_count += 1
                    except Exception as e:
                        self.get_logger().warn(f'Ошибка при отмене цели {action_name}: {e}')
                except Exception as e:
                    self.get_logger().warn(f'Ошибка при отмене цели {action_name}: {e}')
        
        # Очищаем список активных целей
        self._active_goal_handles.clear()
        self._active_goals_by_class.clear()
        
        if cancelled_count > 0:
            self.get_logger().info(f'Отменено {cancelled_count} активных действий (источник: {source})')
        else:
            self.get_logger().info(f'Нет активных действий для отмены (источник: {source})')
    
    def process_command(self, text: str, source: str = 'unknown'):
        """
        Обработка команды из любого источника.

        Args:
            text: Текст команды
            source: Источник команды ('telegram', 'voice', 'unknown')
        """
        text = text.strip()
        if not text:
            return
        
        self.get_logger().info(f'Получена команда из {source}: {text}')
        
        # Попытка классификации через CVC
        cvc_result = None
        if self.cvc_enabled and self.cvc_client:
            cvc_result = self.cvc_client.classify(text, return_confidence=True)
            
            if cvc_result and 'command' in cvc_result:
                confidence = cvc_result.get('confidence', 0.0)
                if confidence >= self.cvc_confidence_threshold:
                    command_name = cvc_result['command']
                    self.get_logger().info(
                        f'CVC классифицировал команду: {command_name} '
                        f'(confidence: {confidence:.2f})'
                    )
                    self._execute_command(command_name, text, source, cvc_result)
                    return
                else:
                    self.get_logger().warn(
                        f'Низкая уверенность CVC: {confidence:.2f} < {self.cvc_confidence_threshold}, '
                        f'используется fallback парсинг'
                    )
            else:
                self.get_logger().warn('CVC классификация не удалась, используется fallback парсинг')
        
        # Fallback: парсинг по ключевым словам
        self._parse_and_execute_fallback(text, source)
    
    def _parse_and_execute_fallback(self, text: str, source: str):
        """Парсинг команды по ключевым словам (fallback)."""
        text_lower = text.lower()
        
        # Проверяем каждую команду в конфигурации
        for command_name, command_config in self.command_config.get('commands', {}).items():
            keywords = command_config.get('keywords', [])
            
            # Проверяем наличие ключевых слов
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    self.get_logger().info(
                        f'Fallback парсинг определил команду: {command_name} '
                        f'(ключевое слово: {keyword})'
                    )
                    self._execute_command(command_name, text, source, None)
                    return
        
        self.get_logger().warn(f'Не удалось распознать команду: {text}')
    
    def _execute_command(self, command_name: str, text: str, source: str, cvc_result: Optional[Dict]):
        """
        Выполнение команды через соответствующий обработчик.

        Args:
            command_name: Имя команды
            text: Исходный текст команды
            source: Источник команды
            cvc_result: Результат CVC классификации (если был)
        """
        if command_name not in self.command_handlers:
            self.get_logger().error(f'Обработчик для команды "{command_name}" не найден')
            return
        
        # Проверяем класс команды и активные команды
        command_config = self.command_config.get('commands', {}).get(command_name, {})
        command_class = command_config.get('class', 'default')
        
        # Проверяем, можно ли выполнить команду (если есть активные команды того же класса)
        if not self.allow_parallel_same_class:
            active_goals = self._active_goals_by_class.get(command_class, [])
            if active_goals:
                self.get_logger().warn(
                    f'Команда "{command_name}" (класс "{command_class}") отклонена: '
                    f'уже выполняется {len(active_goals)} команда(ы) того же класса'
                )
                return
        
        handler = self.command_handlers[command_name]
        
        # Извлекаем параметры команды
        parsed_params = self._extract_command_params(command_name, text, cvc_result)
        
        # Добавляем информацию о классе команды
        parsed_params['command_class'] = command_class
        
        # Вызываем обработчик
        try:
            handler(text, source, parsed_params)
        except Exception as e:
            self.get_logger().error(f'Ошибка при выполнении команды {command_name}: {e}')
            import traceback
            traceback.print_exc()
    
    def _register_active_goal(self, command_class: str, goal_handle):
        """Регистрация активного goal по классу команды."""
        if command_class not in self._active_goals_by_class:
            self._active_goals_by_class[command_class] = []
        self._active_goals_by_class[command_class].append(goal_handle)
    
    def _unregister_active_goal(self, command_class: str, goal_handle):
        """Удаление завершенного goal из активных."""
        if command_class in self._active_goals_by_class:
            if goal_handle in self._active_goals_by_class[command_class]:
                self._active_goals_by_class[command_class].remove(goal_handle)
            if len(self._active_goals_by_class[command_class]) == 0:
                del self._active_goals_by_class[command_class]
    
    def _extract_command_params(self, command_name: str, text: str, cvc_result: Optional[Dict]) -> Dict[str, Any]:
        """
        Извлечение параметров команды из текста.

        Args:
            command_name: Имя команды
            text: Исходный текст команды
            cvc_result: Результат CVC классификации

        Returns:
            Словарь с параметрами команды
        """
        params = {}
        
        command_config = self.command_config.get('commands', {}).get(command_name, {})
        parser_type = command_config.get('parser', 'extract_number')
        
        if parser_type == 'extract_number':
            # Извлекаем число из текста
            numbers = re.findall(r'\d+', text)
            if numbers:
                params['dance_number'] = int(numbers[0])
            else:
                params['dance_number'] = 1  # По умолчанию
        elif parser_type == 'extract_text':
            # Извлекаем текст после команды (убираем ключевые слова)
            # Например: "скажи привет" -> "привет"
            text_lower = text.lower()
            # Убираем ключевые слова из начала
            for keyword in command_config.get('keywords', []):
                if text_lower.startswith(keyword):
                    extracted = text[len(keyword):].strip()
                    if extracted:
                        params['text'] = extracted
                        break
            # Если ничего не извлекли, используем весь текст
            if 'text' not in params:
                params['text'] = text.strip()
        elif parser_type == 'custom':
            # Можно добавить кастомные парсеры
            pass
        
        # Добавляем информацию из CVC результата, если есть
        if cvc_result:
            params['cvc_confidence'] = cvc_result.get('confidence', 0.0)
            # Можно добавить дополнительные параметры из CVC
        
        return params
    
    def handle_dance_command(self, text: str, source: str, params: Dict[str, Any]):
        """
        Обработчик команды танца.

        Args:
            text: Исходный текст команды
            source: Источник команды
            params: Параметры команды (включая dance_number)
        """
        dance_number = params.get('dance_number', 1)
        command_class = params.get('command_class', 'default')
        
        self.get_logger().info(
            f'Отправка команды танца #{dance_number} из {source} (класс: {command_class})'
        )
        
        # Ждем доступности Action сервера
        if not self.dance_action_client.wait_for_server(timeout_sec=1.0):
            self.get_logger().error('Dance Action сервер недоступен')
            return
        
        # Создаем goal
        goal_msg = PlayDance.Goal()
        goal_msg.dance_number = dance_number
        
        # Отправляем goal асинхронно с callback для отслеживания
        send_goal_future = self.dance_action_client.send_goal_async(goal_msg)
        
        def goal_response_callback(future):
            goal_handle = future.result()
            if not goal_handle.accepted:
                self.get_logger().warn('Dance goal отклонен')
                return
            
            # Регистрируем активный goal
            self._register_active_goal(command_class, goal_handle)
            
            # Сохраняем goal_handle для возможности отмены
            action_name = '/dance/play'
            if action_name not in self._active_goal_handles:
                self._active_goal_handles[action_name] = []
            self._active_goal_handles[action_name].append(goal_handle)
            
            self.get_logger().info(f'Команда танца #{dance_number} принята (класс: {command_class})')
            
            # Ожидаем результат для отслеживания завершения
            result_future = goal_handle.get_result_async()
            
            def result_callback(future):
                # Удаляем из списка активных для отмены
                if action_name in self._active_goal_handles:
                    if goal_handle in self._active_goal_handles[action_name]:
                        self._active_goal_handles[action_name].remove(goal_handle)
                    if not self._active_goal_handles[action_name]:
                        del self._active_goal_handles[action_name]
                result = future.result().result
                # Удаляем из активных при завершении
                self._unregister_active_goal(command_class, goal_handle)
                self.get_logger().info(
                    f'Команда танца #{dance_number} завершена '
                    f'(success: {result.success}, класс: {command_class})'
                )
            
            result_future.add_done_callback(result_callback)
        
        send_goal_future.add_done_callback(goal_response_callback)
        self.get_logger().info(f'Команда танца #{dance_number} отправлена')
    
    def handle_say_command(self, text: str, source: str, params: Dict[str, Any]):
        """
        Обработчик команды say (пример кастомного действия).

        Args:
            text: Исходный текст команды
            source: Источник команды
            params: Параметры команды (включая text)
        """
        say_text = params.get('text', text)
        command_class = params.get('command_class', 'default')
        
        self.get_logger().info(
            f'Отправка команды say "{say_text}" из {source} (класс: {command_class})'
        )
        
        # Ждем доступности Action сервера
        if not self.say_action_client.wait_for_server(timeout_sec=1.0):
            self.get_logger().error('Say Action сервер недоступен')
            return
        
        # Создаем goal
        goal_msg = Say.Goal()
        goal_msg.text = say_text
        
        # Отправляем goal асинхронно с callback для отслеживания
        send_goal_future = self.say_action_client.send_goal_async(goal_msg)
        
        def goal_response_callback(future):
            goal_handle = future.result()
            if not goal_handle.accepted:
                self.get_logger().warn('Say goal отклонен')
                return
            
            # Регистрируем активный goal
            self._register_active_goal(command_class, goal_handle)
            
            # Сохраняем goal_handle для возможности отмены
            action_name = '/say'
            if action_name not in self._active_goal_handles:
                self._active_goal_handles[action_name] = []
            self._active_goal_handles[action_name].append(goal_handle)
            
            self.get_logger().info(f'Команда say принята (класс: {command_class})')
            
            # Ожидаем результат для отслеживания завершения
            result_future = goal_handle.get_result_async()
            
            def result_callback(future):
                result = future.result().result
                # Удаляем из активных при завершении
                self._unregister_active_goal(command_class, goal_handle)
                # Удаляем из списка активных для отмены
                if action_name in self._active_goal_handles:
                    if goal_handle in self._active_goal_handles[action_name]:
                        self._active_goal_handles[action_name].remove(goal_handle)
                    if not self._active_goal_handles[action_name]:
                        del self._active_goal_handles[action_name]
                self.get_logger().info(
                    f'Команда say завершена '
                    f'(success: {result.success}, класс: {command_class})'
                )
            
            result_future.add_done_callback(result_callback)
        
        send_goal_future.add_done_callback(goal_response_callback)
        self.get_logger().info(f'Команда say "{say_text}" отправлена')


def main(args=None):
    """Главная функция для запуска узла."""
    rclpy.init(args=args)
    
    try:
        command_parser = CommandParserNode()
        rclpy.spin(command_parser)
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

