#!/usr/bin/env python3
"""Telegram бот для управления роботом через ROS2.

Поддерживает:
- Авторизацию через 4-значный код
- Динамическое меню с кнопками для команд
- Текстовые и голосовые сообщения
- Интеграцию с command_parser_node через топики
"""

import asyncio
import json
import time
import random
import string
from typing import Dict, Set, Any, Optional, List
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from std_msgs.msg import String
from vosk_ros2.msg import Transcription

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from audio_common_msgs.msg import AudioStamped
import soundfile as sf


class AuthStates(StatesGroup):
    """Состояния для авторизации."""
    waiting_for_code = State()


class TelegramBotNode(Node):
    """ROS2 нода для Telegram бота."""
    
    def __init__(self):
        super().__init__('telegram_bot')
        
        # Параметры
        self.declare_parameter('telegram_token', '')
        self.declare_parameter('commands_topic', '/commands')
        self.declare_parameter('telegram_whitelist', '')
        self.declare_parameter('code_timeout', 60.0)  # 1 минута по умолчанию
        self.declare_parameter('menu_refresh_interval', 5.0)
        self.declare_parameter('audio_topic', '/telegram/audio')
        self.declare_parameter('audio_sample_rate', 16000)
        self.declare_parameter('auth_enabled', True)  # Включена ли авторизация
        
        telegram_token = self.get_parameter('telegram_token').get_parameter_value().string_value
        if not telegram_token:
            self.get_logger().error('telegram_token не указан!')
            raise ValueError('telegram_token обязателен')
        
        commands_topic = self.get_parameter('commands_topic').get_parameter_value().string_value
        whitelist_str = self.get_parameter('telegram_whitelist').get_parameter_value().string_value
        self.code_timeout = self.get_parameter('code_timeout').get_parameter_value().double_value
        self.audio_topic = self.get_parameter('audio_topic').get_parameter_value().string_value
        self.audio_sample_rate = int(self.get_parameter('audio_sample_rate').get_parameter_value().integer_value)
        self.auth_enabled = self.get_parameter('auth_enabled').get_parameter_value().bool_value
        
        # Инициализация aiogram
        self.bot = Bot(token=telegram_token)
        self.dp = Dispatcher(storage=MemoryStorage())
        
        # Event loop для запуска корутин из синхронных callbacks
        self._bot_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Авторизация
        self._authorized_chats: Set[int] = set()
        self._pending_codes: Dict[int, Dict[str, Any]] = {}  # {chat_id: {'code': str, 'timestamp': float}}
        
        # Парсим начальный whitelist
        if whitelist_str:
            try:
                for chat_id_str in whitelist_str.split(','):
                    chat_id = int(chat_id_str.strip())
                    self._authorized_chats.add(chat_id)
            except ValueError:
                self.get_logger().warn(f'Неверный формат whitelist: {whitelist_str}')
        
        # Команды
        self._available_commands: Dict[str, Dict[str, Any]] = {}  # {command_name: command_info}
        self._command_sources: Dict[str, str] = {}  # {command_name: server_name}
        
        # Отслеживание голосовых сообщений для отправки транскрипций
        # {chat_id: {'pending_message_id': int, 'timestamp': float}}
        self._pending_transcriptions: Dict[int, Dict[str, Any]] = {}
        
        # ROS2 публикаторы и подписчики
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        
        self._message_to_ros_pub = self.create_publisher(String, '/telegram/message', qos_profile)
        
        audio_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        self._audio_pub = self.create_publisher(AudioStamped, self.audio_topic, audio_qos)
        
        # Подписка на топик команд (один топик, в который публикуют все серверы)
        self._commands_sub = self.create_subscription(
            String, commands_topic, self._commands_callback, qos_profile
        )
        
        # Подписка на топик транскрипции для Telegram аудио
        transcription_topic = self.audio_topic.rstrip('/') + '/transcription'
        self._transcription_sub = self.create_subscription(
            Transcription, transcription_topic, self._transcription_callback, qos_profile
        )
        self.get_logger().info(f'Подписка на топик транскрипции: {transcription_topic}')
        
        # Регистрация обработчиков aiogram
        self._register_handlers()
        
        # Таймер для очистки устаревших кодов (проверяем каждые 10 секунд)
        self.create_timer(10.0, self._cleanup_expired_codes)
        
        # Таймер для очистки устаревших pending транскрипций (проверяем каждые 30 секунд)
        self.create_timer(30.0, self._cleanup_expired_transcriptions)
        
        # Флаг для управления циклом бота
        self._running = True
        
        if not self.auth_enabled:
            self.get_logger().warn('⚠️ Авторизация ОТКЛЮЧЕНА - все пользователи имеют доступ!')
        else:
            self.get_logger().info('Авторизация включена')
        
        self.get_logger().info('Telegram Bot Node инициализирован')
    
    def _register_handlers(self):
        """Регистрация обработчиков команд и сообщений aiogram."""
        self.dp.message.register(self._start_handler, Command('start'))
        self.dp.message.register(self._help_handler, Command('help'))
        self.dp.message.register(self._menu_handler, Command('menu'))
        self.dp.message.register(self._refresh_commands_handler, Command('refresh_commands'))
        self.dp.message.register(self._status_handler, Command('status'))
        self.dp.message.register(self._cancel_handler, Command('cancel'))
        self.dp.message.register(self._logout_handler, Command('logout'))
        self.dp.message.register(self._voice_message_handler, lambda m: m.voice is not None)
        self.dp.message.register(self._text_message_handler)
        self.dp.callback_query.register(self._callback_query_handler)
    
    def _is_authorized(self, chat_id: int) -> bool:
        """Проверяет, авторизован ли пользователь. Если авторизация отключена, всегда возвращает True."""
        if not self.auth_enabled:
            return True
        return chat_id in self._authorized_chats
    
    async def _start_handler(self, message: Message):
        """Обработчик команды /start."""
        chat_id = message.chat.id
        
        if self._is_authorized(chat_id):
            await message.answer(
                'Добро пожаловать! Используйте /menu для просмотра доступных команд.'
            )
        else:
            await message.answer(
                'Для использования бота требуется авторизация.\n'
                'Запрашиваю код авторизации у робота...'
            )
            await self._request_auth_code(chat_id)
    
    async def _help_handler(self, message: Message):
        """Обработчик команды /help."""
        help_text = (
            'Доступные команды:\n'
            '/start - Начать работу с ботом\n'
            '/menu - Показать меню команд\n'
            '/help - Показать эту справку\n'
            '/refresh_commands - Обновить список команд\n'
            '/status - Показать статус робота\n'
            '/cancel - Отменить текущее действие робота\n'
            '/logout - Отвязать аккаунт (выйти)\n\n'
            'Вы также можете отправлять текстовые команды или голосовые сообщения.'
        )
        await message.answer(help_text)
    
    async def _menu_handler(self, message: Message):
        """Обработчик команды /menu."""
        chat_id = message.chat.id
        
        if not self._is_authorized(chat_id):
            await message.answer('Сначала пройдите авторизацию через /start')
            return
        
        keyboard = self._build_menu()
        if keyboard:
            await message.answer('Выберите команду:', reply_markup=keyboard)
        else:
            await message.answer('Команды пока не загружены. Попробуйте /refresh_commands')
    
    async def _refresh_commands_handler(self, message: Message):
        """Обработчик команды /refresh_commands."""
        chat_id = message.chat.id
        
        if not self._is_authorized(chat_id):
            await message.answer('Сначала пройдите авторизацию через /start')
            return
        
        await message.answer('Обновляю список команд...')
        # Команды обновятся автоматически при получении сообщений из топиков
    
    async def _status_handler(self, message: Message):
        """Обработчик команды /status."""
        chat_id = message.chat.id
        
        if not self._is_authorized(chat_id):
            await message.answer('Сначала пройдите авторизацию через /start')
            return
        
        # Формируем статус
        status_lines = [
            '📊 Статус робота:',
            '',
            f'✅ Авторизация: активна',
            f'📋 Доступно команд: {len(self._available_commands)}',
        ]
        
        if self._available_commands:
            status_lines.append('')
            status_lines.append('Доступные команды:')
            for cmd_name in sorted(self._available_commands.keys())[:10]:  # Показываем первые 10
                cmd_info = self._available_commands[cmd_name]
                display_name = cmd_info.get('display_name', cmd_name)
                status_lines.append(f'  • {display_name}')
            if len(self._available_commands) > 10:
                status_lines.append(f'  ... и еще {len(self._available_commands) - 10} команд')
        
        status_text = '\n'.join(status_lines)
        await message.answer(status_text)
    
    async def _cancel_handler(self, message: Message):
        """Обработчик команды /cancel - отмена текущих действий."""
        chat_id = message.chat.id
        
        if not self._is_authorized(chat_id):
            await message.answer('Сначала пройдите авторизацию через /start')
            return
        
        # Публикуем команду отмены в /telegram/message
        cancel_msg = String()
        cancel_msg.data = 'cancel'
        self._message_to_ros_pub.publish(cancel_msg)
        
        await message.answer('🛑 Команда отмены отправлена роботу')
    
    async def _logout_handler(self, message: Message):
        """Обработчик команды /logout - отвязка аккаунта."""
        chat_id = message.chat.id
        
        if not self._is_authorized(chat_id):
            await message.answer('Вы не авторизованы.')
            return
        
        # Удаляем из списка авторизованных
        self._authorized_chats.discard(chat_id)
        
        # Удаляем ожидающий код, если есть
        if chat_id in self._pending_codes:
            del self._pending_codes[chat_id]
        
        self.get_logger().info(f'Пользователь {chat_id} отвязал аккаунт')
        await message.answer('✅ Аккаунт отвязан. Для повторной авторизации используйте /start')
    
    async def _text_message_handler(self, message: Message):
        """Обработчик текстовых сообщений."""
        chat_id = message.chat.id
        text = message.text
        
        if not text:
            return
        
        # Проверка авторизации
        if not self._is_authorized(chat_id):
            # Проверяем, не вводит ли пользователь код авторизации
            if chat_id in self._pending_codes:
                await self._handle_auth_code_input(message, text)
                return
            else:
                await message.answer('Сначала пройдите авторизацию через /start')
                return
        
        # Публикуем сообщение в ROS2
        msg = String()
        msg.data = text
        self._message_to_ros_pub.publish(msg)
        
        self.get_logger().debug(f'Отправлено сообщение в /telegram/message: {text}')
    
    async def _voice_message_handler(self, message: Message):
        """Обработчик голосовых сообщений."""
        chat_id = message.chat.id
        
        # Проверка авторизации
        if not self._is_authorized(chat_id):
            await message.answer('Сначала пройдите авторизацию через /start')
            return
        
        if not message.voice:
            return
        
        try:
            # Отправляем сообщение о обработке и сохраняем его ID для последующего обновления
            processing_msg = await message.answer('Обрабатываю голосовое сообщение...')
            pending_message_id = processing_msg.message_id
            
            # Сохраняем информацию о pending транскрипции
            self._pending_transcriptions[chat_id] = {
                'pending_message_id': pending_message_id,
                'timestamp': time.time()
            }
            
            # Скачиваем файл
            file = await self.bot.get_file(message.voice.file_id)
            file_path = file.file_path
            
            # Скачиваем файл во временную директорию
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as tmp_file:
                tmp_path = tmp_file.name
                await self.bot.download_file(file_path, tmp_path)
            
            try:
                # Конвертируем и публикуем
                await self._process_voice_file(tmp_path, chat_id)
                # Не отправляем сообщение об успехе - оно будет заменено транскрипцией
            finally:
                # Удаляем временный файл
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                    
        except Exception as e:
            self.get_logger().error(f'Ошибка при обработке голосового сообщения: {e}')
            import traceback
            traceback.print_exc()
            # Отправляем пользователю сообщение об ошибке
            error_msg = str(e)
            await message.answer(f'❌ Ошибка при обработке голосового сообщения: {error_msg}')
    
    async def _process_voice_file(self, file_path: str, chat_id: int):
        """Обрабатывает голосовой файл и публикует в ROS2 топик."""
        try:
            import numpy as np
            from scipy import signal
            
            # Используем soundfile для декодирования OGG Opus
            # soundfile поддерживает OGG Opus и возвращает данные напрямую как numpy array
            data, sample_rate = sf.read(file_path, dtype='int16')
            
            # data уже является numpy array int16
            # Если стерео, data имеет форму (samples, channels)
            channels = 1 if data.ndim == 1 else data.shape[1]
            
            # Если стерео, конвертируем в моно (до нормализации)
            if channels > 1:
                pcm_data = data.mean(axis=1).astype(np.int16)
            else:
                pcm_data = data.flatten()
            
            # Конвертируем в float32 и нормализуем
            samples = pcm_data.astype(np.float32) / 32768.0
            
            # Ресемплинг если нужно
            if sample_rate != self.audio_sample_rate:
                num_samples = int(len(samples) * self.audio_sample_rate / sample_rate)
                samples = signal.resample(samples, num_samples)
            
            # Публикуем чанками (размер чанка как у микрофона - обычно 1024 или 2048 сэмплов)
            # Для vosk важно публиковать данные быстро, без задержек, чтобы они накапливались
            chunk_size = 1024  # Размер чанка для публикации (как у микрофона)
            for i in range(0, len(samples), chunk_size):
                chunk = samples[i:i+chunk_size]
                
                msg = AudioStamped()
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.header.frame_id = 'telegram_voice'
                
                msg.audio.info.format = 1  # paFloat32
                msg.audio.info.channels = 1
                msg.audio.info.rate = self.audio_sample_rate
                msg.audio.info.chunk = len(chunk)
                
                msg.audio.audio_data.float32_data = chunk.tolist()
                
                self._audio_pub.publish(msg)
                
                # Минимальная задержка для неблокирующей публикации
                # Даем ROS2 время обработать сообщение, но не замедляем поток данных
                await asyncio.sleep(0.001)  # 1ms - минимальная задержка
            
            self.get_logger().info(f'Опубликовано голосовое сообщение: {len(samples)} сэмплов')
            
        except Exception as e:
            self.get_logger().error(f'Ошибка при обработке голосового файла: {e}')
            import traceback
            traceback.print_exc()
            # Пробрасываем исключение дальше, чтобы пользователь получил сообщение
            raise
    
    async def _callback_query_handler(self, callback_query: CallbackQuery):
        """Обработчик callback_query от inline кнопок."""
        chat_id = callback_query.message.chat.id
        
        if not self._is_authorized(chat_id):
            await callback_query.answer('Сначала пройдите авторизацию', show_alert=True)
            return
        
        data = callback_query.data
        
        if data.startswith('cmd:'):
            # Выбор команды
            command_name = data[4:]
            await self._handle_command_selection(callback_query, command_name)
        elif data.startswith('param:'):
            # Выбор параметра команды
            parts = data[6:].split(':')
            if len(parts) == 2:
                command_name, param_value = parts
                await self._handle_parameter_selection(callback_query, command_name, param_value)
        elif data == 'back':
            # Назад к главному меню
            keyboard = self._build_menu()
            if keyboard:
                await callback_query.message.edit_text('Выберите команду:', reply_markup=keyboard)
            await callback_query.answer()
        elif data == 'refresh':
            # Обновить меню
            keyboard = self._build_menu()
            if keyboard:
                await callback_query.message.edit_text('Меню обновлено. Выберите команду:', reply_markup=keyboard)
            await callback_query.answer('Меню обновлено')
        else:
            await callback_query.answer('Неизвестная команда')
    
    def _build_menu(self) -> Optional[InlineKeyboardMarkup]:
        """Строит динамическое меню из доступных команд."""
        if not self._available_commands:
            return None
        
        buttons = []
        for command_name, command_info in self._available_commands.items():
            display_name = command_info.get('display_name', command_name.capitalize())
            buttons.append([InlineKeyboardButton(
                text=display_name,
                callback_data=f'cmd:{command_name}'
            )])
        
        # Кнопка "Обновить"
        buttons.append([InlineKeyboardButton(text='🔄 Обновить', callback_data='refresh')])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    def _build_command_submenu(self, command_name: str) -> Optional[InlineKeyboardMarkup]:
        """Строит подменю для команды с параметрами."""
        if command_name not in self._available_commands:
            return None
        
        command_info = self._available_commands[command_name]
        params = command_info.get('parameters', {})
        
        buttons = []
        
        # Если есть available_values, создаем кнопки для каждого значения
        if 'available_values' in params:
            available_values = params['available_values']
            descriptions = params.get('descriptions', {})
            
            # Группируем кнопки по 2 в ряд
            row = []
            for value in available_values:
                desc = descriptions.get(str(value), f'{command_info.get("display_name", command_name)} {value}')
                row.append(InlineKeyboardButton(
                    text=desc,
                    callback_data=f'param:{command_name}:{value}'
                ))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
        else:
            # Если нет available_values, просто отправляем команду без параметров
            buttons.append([InlineKeyboardButton(
                text='Выполнить',
                callback_data=f'param:{command_name}:'
            )])
        
        # Кнопка "Назад"
        buttons.append([InlineKeyboardButton(text='⬅️ Назад', callback_data='back')])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    async def _handle_command_selection(self, callback_query: CallbackQuery, command_name: str):
        """Обработка выбора команды из меню."""
        if command_name not in self._available_commands:
            await callback_query.answer('Команда не найдена', show_alert=True)
            return
        
        command_info = self._available_commands[command_name]
        params = command_info.get('parameters', {})
        
        # Если есть параметры, показываем подменю
        if params and 'available_values' in params:
            keyboard = self._build_command_submenu(command_name)
            if keyboard:
                display_name = command_info.get('display_name', command_name.capitalize())
                await callback_query.message.edit_text(
                    f'{display_name}\nВыберите параметр:',
                    reply_markup=keyboard
                )
                await callback_query.answer()
        else:
            # Если параметров нет, сразу отправляем команду
            await self._send_command(callback_query.message.chat.id, command_name, '')
            await callback_query.answer('Команда отправлена')
    
    async def _handle_parameter_selection(self, callback_query: CallbackQuery, command_name: str, param_value: str):
        """Обработка выбора параметра команды."""
        if command_name not in self._available_commands:
            await callback_query.answer('Команда не найдена', show_alert=True)
            return
        
        await self._send_command(callback_query.message.chat.id, command_name, param_value)
        await callback_query.answer('Команда отправлена')
    
    async def _send_command(self, chat_id: int, command_name: str, param_value: str):
        """Отправляет команду в /telegram/message."""
        command_info = self._available_commands.get(command_name, {})
        
        # Формируем текст команды
        if param_value:
            command_text = f'{command_name} {param_value}'
        else:
            command_text = command_name
        
        msg = String()
        msg.data = command_text
        self._message_to_ros_pub.publish(msg)
        
        self.get_logger().debug(f'Отправлена команда в /telegram/message: {command_text}')
    
    async def _request_auth_code(self, chat_id: int):
        """Генерирует и публикует код авторизации."""
        # Генерируем 4-значный код
        code = f"{random.randint(1000, 9999)}"
        
        # Сохраняем код для проверки
        self._pending_codes[chat_id] = {
            'code': code,
            'timestamp': time.time()
        }
        
        # Логируем код в логах Telegram бота
        self.get_logger().info('=' * 50)
        self.get_logger().info(f'КОД АВТОРИЗАЦИИ ДЛЯ TELEGRAM (chat_id: {chat_id}): {code}')
        self.get_logger().info('=' * 50)
        
        await self.bot.send_message(
            chat_id,
            'Код авторизации будет отображен в логах робота. Введите его для продолжения.'
        )
    
    async def _handle_auth_code_input(self, message: Message, text: str):
        """Обрабатывает ввод кода авторизации."""
        chat_id = message.chat.id
        
        # Проверяем формат кода (должен быть 4 цифры)
        code_input = text.strip()
        if not code_input.isdigit() or len(code_input) != 4:
            await message.answer('❌ Код должен состоять из 4 цифр. Попробуйте еще раз.')
            return
        
        if chat_id not in self._pending_codes:
            await message.answer('Код не запрошен или истек. Используйте /start для запроса нового кода')
            return
        
        code_info = self._pending_codes[chat_id]
        expected_code = code_info['code']
        
        # Проверяем, не истек ли код
        if time.time() - code_info['timestamp'] > self.code_timeout:
            del self._pending_codes[chat_id]
            await message.answer('⏰ Код истек. Используйте /start для запроса нового кода')
            return
        
        if code_input == expected_code:
            # Код верный
            self._authorized_chats.add(chat_id)
            del self._pending_codes[chat_id]
            await message.answer('✅ Авторизация успешна! Используйте /menu для просмотра команд.')
        else:
            # Код неверный
            await message.answer('❌ Неверный код. Попробуйте еще раз или запросите новый код через /start')
    
    def _transcription_callback(self, msg: Transcription):
        """Обработчик транскрипций из vosk."""
        if not msg.text or not msg.text.strip():
            return
        
        # Ищем chat_id, который ожидает транскрипцию
        # Используем самый свежий pending (последний отправивший голосовое сообщение)
        if not self._pending_transcriptions:
            return
        
        # Берем самый свежий pending (последний по timestamp)
        chat_id = max(self._pending_transcriptions.keys(), 
                     key=lambda k: self._pending_transcriptions[k]['timestamp'])
        
        pending_info = self._pending_transcriptions.pop(chat_id)
        pending_message_id = pending_info['pending_message_id']
        
        # Отправляем транскрипцию пользователю через async задачу
        self._schedule_async_task(self._send_transcription_to_user(
            chat_id, pending_message_id, msg.text
        ))
    
    async def _send_transcription_to_user(self, chat_id: int, pending_message_id: int, transcription_text: str):
        """Отправляет транскрипцию пользователю, заменяя сообщение об обработке."""
        try:
            # Редактируем сообщение об обработке, заменяя его на транскрипцию
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=pending_message_id,
                text=f'🎤 Расшифровка: {transcription_text}'
            )
        except Exception as e:
            # Если не удалось отредактировать (например, сообщение слишком старое),
            # отправляем новое сообщение
            self.get_logger().debug(f'Не удалось отредактировать сообщение {pending_message_id}: {e}')
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f'🎤 Расшифровка: {transcription_text}'
                )
            except Exception as e2:
                self.get_logger().error(f'Ошибка отправки транскрипции пользователю {chat_id}: {e2}')
    
    def _commands_callback(self, msg: String):
        """Обработчик сообщений из топика команд."""
        try:
            data = json.loads(msg.data)
            server_name = data.get('server_name', 'unknown')
            commands = data.get('commands', [])
            
            # Обновляем список команд
            for command in commands:
                command_name = command.get('name')
                if command_name:
                    self._available_commands[command_name] = command
                    self._command_sources[command_name] = server_name
            
            self.get_logger().debug(
                f'Обновлен список команд из {server_name}: {len(commands)} команд'
            )
            
        except Exception as e:
            self.get_logger().error(f'Ошибка при обработке списка команд: {e}')
    
    def _cleanup_expired_codes(self):
        """Очищает устаревшие коды авторизации."""
        current_time = time.time()
        expired_chats = []
        
        for chat_id, code_info in self._pending_codes.items():
            elapsed = current_time - code_info['timestamp']
            if elapsed > self.code_timeout:
                expired_chats.append(chat_id)
        
        for chat_id in expired_chats:
            del self._pending_codes[chat_id]
            self.get_logger().info(f'Код авторизации истек для chat_id: {chat_id} (таймаут: {self.code_timeout} сек)')
    
    def _cleanup_expired_transcriptions(self):
        """Очищает устаревшие pending транскрипции (старше 60 секунд)."""
        current_time = time.time()
        expired_chats = []
        timeout = 60.0  # 60 секунд таймаут для транскрипций
        
        for chat_id, pending_info in self._pending_transcriptions.items():
            elapsed = current_time - pending_info['timestamp']
            if elapsed > timeout:
                expired_chats.append(chat_id)
        
        for chat_id in expired_chats:
            del self._pending_transcriptions[chat_id]
            self.get_logger().debug(f'Удалена устаревшая pending транскрипция для chat_id: {chat_id}')
    
    def _schedule_async_task(self, coro):
        """Планирует выполнение async функции из синхронного callback."""
        if self._bot_loop and self._bot_loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._bot_loop)
        else:
            self.get_logger().warn('Event loop бота недоступен, не удалось отправить сообщение')
    
    async def _process_updates(self):
        """Обрабатывает обновления от Telegram вручную (без start_polling)."""
        try:
            # Пропускаем накопленные обновления при старте
            await self.bot.delete_webhook(drop_pending_updates=True)
            
            offset = None
            while self._running:
                try:
                    # Получаем обновления
                    updates = await self.bot.get_updates(offset=offset, timeout=5, allowed_updates=['message', 'callback_query'])
                    
                    if updates:
                        # Обрабатываем каждое обновление
                        for update in updates:
                            offset = update.update_id + 1
                            await self.dp.feed_update(self.bot, update)
                    
                    # Небольшая задержка между запросами
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    if self._running:  # Логируем только если еще работаем
                        self.get_logger().error(f'Ошибка при получении обновлений: {e}')
                    await asyncio.sleep(1)
                    
        except Exception as e:
            self.get_logger().error(f'Критическая ошибка в боте: {e}')
            import traceback
            traceback.print_exc()
    
    def run(self):
        """Запускает бота в отдельном потоке без обработки сигналов."""
        import threading
        
        def run_async():
            # Создаем новый event loop для этого потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._bot_loop = loop  # Сохраняем ссылку на event loop
            
            try:
                # Запускаем обработку обновлений
                loop.run_until_complete(self._process_updates())
            except Exception as e:
                self.get_logger().error(f'Ошибка в event loop бота: {e}')
                import traceback
                traceback.print_exc()
            finally:
                self._bot_loop = None
                loop.close()
        
        bot_thread = threading.Thread(target=run_async, daemon=True)
        bot_thread.start()
        self.get_logger().info('Telegram бот запущен')


def main(args=None):
    """Главная функция для запуска узла."""
    rclpy.init(args=args)
    
    node = None
    try:
        node = TelegramBotNode()
        node.run()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'\nОшибка: {e}')
        import traceback
        traceback.print_exc()
    finally:
        if node:
            node._running = False
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()

