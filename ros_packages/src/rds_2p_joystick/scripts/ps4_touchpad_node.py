#!/usr/bin/env python3
"""
ROS2 узел для чтения данных тачпада с контроллера PS4 через hidraw.

Этот узел читает данные тачпада с контроллера PS4 DualShock 4 через hidraw
и публикует их как сообщения geometry_msgs/msg/PointStamped в ROS2.

Тачпад поддерживает мультитач (до 2 одновременных касаний).

Требования:
- Доступ к устройствам /dev/hidraw* (пользователь должен быть в группе 'input')
- ds4drv должен быть запущен с флагом --hidraw
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PointStamped
from std_msgs.msg import Header, Bool
import os
import struct
import threading
import select
import fcntl
from dataclasses import dataclass
from typing import Optional, Dict

# Константы для тачпада
class TouchpadConstants:
    """Константы для обработки данных тачпада."""
    # Размеры тачпада (разрешение PS4 тачпада)
    # Из https://www.psdevwiki.com/ps4/DualShock_4
    # Серия CUH-ZCT1x (Retail) 1920x943 (44.86 точек/мм)
    TOUCHPAD_WIDTH = 1920
    TOUCHPAD_HEIGHT = 943
    
    # Диапазон сырых координат (12-битные значения: 0-4095)
    RAW_COORDINATE_MAX = 4095
    
    # Максимальное количество одновременных касаний
    MAX_TOUCHES = 1  # Обрабатывать только первое касание
    
    # Структура HID отчета для контроллера PS4
    # Входной отчет составляет 64 байта
    REPORT_SIZE = 64
    # Данные тачпада начинаются с байта 35 во входном отчете
    TOUCHPAD_DATA_OFFSET = 35
    # Каждое касание находится на расстоянии 4 байта (Касание 0 на байте 35, Касание 1 на байте 39)
    TOUCH_BYTE_SPACING = 4
    
    # Маски для ID касания и флага активности
    TOUCH_ACTIVE_MASK = 0x80  # Бит 7: 0 = активно, 1 = неактивно
    TOUCH_ID_MASK = 0x7F      # Младшие 7 бит - это ID касания
    
    # Минимальные валидные значения координат (для фильтрации шума/ложных касаний)
    # Фактическое разрешение тачпада PS4: 1920x943
    # Сырые значения 12-битные (0-4095), но фактический диапазон тачпада: 0-1920 для X и 0-943 для Y
    MIN_VALID_X = 10   # Отфильтровать очень маленькие значения (вероятно шум)
    MIN_VALID_Y = 10   # Отфильтровать очень маленькие значения (вероятно шум)
    MAX_VALID_X = TOUCHPAD_WIDTH   # Максимум X = 1920 (фактическая ширина тачпада)
    MAX_VALID_Y = TOUCHPAD_HEIGHT  # Максимум Y = 943 (фактическая высота тачпада)
    
    # Включить маппинг координат (нормализация к 0.0-1.0)
    ENABLE_COORDINATE_MAPPING = False  # Отключено - публиковать сырые значения


@dataclass
class TouchPoint:
    """Данные одной точки касания."""
    x: float = 0.0  # Нормализовано 0.0-1.0
    y: float = 0.0  # Нормализовано 0.0-1.0
    tracking_id: int = -1  # -1 означает отсутствие касания
    is_active: bool = False


class PS4TouchpadNode(Node):
    """ROS2 узел для данных тачпада контроллера PS4 через hidraw."""

    def __init__(self) -> None:
        super().__init__('ps4_touchpad_node')
        
        # Настройка параметров
        self._setup_parameters()
        
        # Настройка структур данных (нужно для настройки устройства)
        self._setup_data_structures()
        
        # Настройка устройства (открывает hidraw файл)
        if not self._setup_device():
            return
        
        # Настройка публикаторов
        self._setup_publishers()
        
        # Запуск потока чтения (после открытия файла)
        self._start_reading_thread()
        
        self.get_logger().info(
            f"PS4 Touchpad node started. Publishing to /joy/touchpad at {self.publish_rate} Hz"
        )
    
    def _setup_parameters(self) -> None:
        """Настройка и получение параметров ROS."""
        # Объявление параметров
        self.declare_parameter('hidraw_device', '/dev/hidraw1')
        self.declare_parameter('frame_id', 'ps4_controller')
        self.declare_parameter('publish_rate', 50.0)  # Гц
        self.declare_parameter('debug_touchpad', False)  # Включить отладочное логирование
        
        # Get parameters
        self.hidraw_device_param = self.get_parameter('hidraw_device').get_parameter_value().string_value
        self.frame_id = self.get_parameter('frame_id').get_parameter_value().string_value
        self.publish_rate = self.get_parameter('publish_rate').get_parameter_value().double_value
        self.debug_touchpad = self.get_parameter('debug_touchpad').get_parameter_value().bool_value
    
    def _setup_data_structures(self) -> None:
        """Инициализация структур данных и блокировок."""
        # Блокировка потока для потокобезопасного доступа
        self.data_lock = threading.Lock()
        
        # Точки касания (слот 0 и слот 1)
        self.touch_points: Dict[int, TouchPoint] = {
            0: TouchPoint(),
            1: TouchPoint()
        }
        
        # Последняя опубликованная точка касания (для обнаружения изменений)
        self.last_published_touch: Optional[TouchPoint] = None
        
        # Дескриптор hidraw файла
        self.hidraw_file = None
        self.running = True
    
    def _setup_device(self) -> bool:
        """Настройка и открытие hidraw устройства. Возвращает True при успехе."""
        hidraw_device = self.hidraw_device_param
        
        # Попытка найти hidraw устройство, если не указано или не существует
        if not os.path.exists(hidraw_device):
            hidraw_device = self._find_hidraw_device()
            if not hidraw_device:
                return True  # Продолжить в любом случае
        
        # Try to open the hidraw device
        try:
            self.hidraw_file = open(hidraw_device, 'rb')
            if self.hidraw_file:
                self.get_logger().info(f"Найдено hidraw устройство PS4: {hidraw_device}")
                return True
            else:
                return True  # Continue anyway
        except (PermissionError, OSError, Exception):
            self.hidraw_file = None
            return True  # Continue anyway
    
    def _find_hidraw_device(self) -> Optional[str]:
        """Попытка автоматически найти hidraw устройство контроллера PS4.
        
        Проверяет hidraw устройства, пытаясь прочитать данные и проверить структуру отчёта PS4.
        ds4drv обычно создаёт /dev/hidraw0 или /dev/hidraw1.
        """
        # Проверка распространенных hidraw устройств
        # ds4drv обычно создаёт hidraw0 или hidraw1
        # Проверяем в порядке приоритета: hidraw1, hidraw0, затем остальные
        priority_order = [1, 0] + [i for i in range(2, 10) if i not in [0, 1]]
        
        for i in priority_order:
            hidraw_path = f'/dev/hidraw{i}'
            if not os.path.exists(hidraw_path):
                continue
            
            try:
                # Попытка открыть и прочитать небольшой кусок данных для проверки
                # PS4 контроллер через ds4drv должен возвращать отчёты размером 64 байта
                test_file = open(hidraw_path, 'rb')
                # Пробуем прочитать один отчёт (64 байта)
                data = test_file.read(TouchpadConstants.REPORT_SIZE)
                test_file.close()
                
                # Проверяем, что данные не пустые и имеют правильный размер
                if len(data) == TouchpadConstants.REPORT_SIZE:
                    # Проверяем структуру отчёта PS4
                    # Байт 0 обычно содержит тип отчёта (0x11 для входного отчёта)
                    # Байт 5 обычно содержит состояние батареи и другие флаги
                    if len(data) > 5:
                        # Это может быть PS4 контроллер
                        return hidraw_path
            except (PermissionError, OSError, IOError, Exception):
                continue
        
        # Если не нашли через проверку структуры, возвращаем первое доступное
        # (fallback для случаев, когда чтение не работает)
        for i in priority_order:
            hidraw_path = f'/dev/hidraw{i}'
            if os.path.exists(hidraw_path):
                return hidraw_path
        
        return None
    
    def _setup_publishers(self) -> None:
        """Настройка публикаторов ROS и таймеров."""
        # Публикатор для координат тачпада (нормализовано 0.0-1.0)
        # Публикует основную точку касания (первое активное касание или среднее, если оба активны)
        self.touchpad_pub = self.create_publisher(PointStamped, '/joy/touchpad', 10)
        
        # Публикатор для состояния касания (есть ли активное касание)
        self.touch_state_pub = self.create_publisher(Bool, '/joy/touchpad/active', 10)
        
        # Таймер для публикации данных тачпада
        publish_timer_period = 1.0 / self.publish_rate
        self.publish_timer = self.create_timer(publish_timer_period, self.publish_touchpad)
    
    def _start_reading_thread(self) -> None:
        """Запуск потока для чтения данных hidraw."""
        self.reading_thread = threading.Thread(target=self._read_hidraw_data, daemon=True)
        self.reading_thread.start()
    
    def _parse_touchpad_data(self, report_data: bytes) -> None:
        """Парсинг данных тачпада из HID отчета.
        
        Args:
            report_data: Сырые данные HID отчета (64 байта)
        
        Формат тачпада PS4 (на основе Stack Overflow и ds4mac):
        https://stackoverflow.com/questions/21452600/dualshock-4-touch-pad-with-c-sharp
        https://github.com/MarcoLuglio/ds4mac/blob/master/GamePad/DualShock4Controller.swift
        
        - Проверка смещения: если report_data[0] == 0x11 и report_data[1] == 0xC0, offset = 2, иначе 0
        - Касание 0 (touch_idx=0):
          - Байт 35 + offset: ID касания (7 бит) + флаг активности (бит 7: 0=активно, 1=неактивно)
          - X: 12 бит из байтов 36-37: (byte[37] << 8) | byte[36] & 0x0FFF
          - Y: 12 бит из байтов 37-38: (byte[38] << 4) | (byte[37] >> 4) & 0x0FFF
        - Касание 1 (touch_idx=1):
          - Байт 39 + offset: ID касания + флаг активности
          - X: 12 бит из байтов 40-41: (byte[41] << 8) | byte[40] & 0x0FFF
          - Y: 12 бит из байтов 41-42: (byte[42] << 4) | (byte[41] >> 4) & 0x0FFF
        """
        if len(report_data) < 43:
            return
        
        # Проверка смещения (если отчет начинается с 0x11 0xC0)
        offset = 0
        if len(report_data) > 1 and report_data[0] == 0x11 and report_data[1] == 0xC0:
            offset = 2
        
        # Парсинг точек касания (обрабатывать только первое касание, если MAX_TOUCHES = 1)
        with self.data_lock:
            for touch_idx in range(TouchpadConstants.MAX_TOUCHES):
                # Базовое смещение для данных касания
                # Касание 0: байт 35, Касание 1: байт 39
                touch_base = TouchpadConstants.TOUCHPAD_DATA_OFFSET + offset + (touch_idx * TouchpadConstants.TOUCH_BYTE_SPACING)
                
                if touch_base + 3 >= len(report_data):
                    # Недостаточно данных для этого касания
                    self.touch_points[touch_idx] = TouchPoint(
                        x=0.0,
                        y=0.0,
                        tracking_id=-1,
                        is_active=False
                    )
                    continue
                
                # Извлечение ID касания и флага активности (на основе реализации ds4mac)
                # Бит 7: 0 = активно, 1 = неактивно
                # Младшие 7 бит: ID касания
                touch_byte = report_data[touch_base]
                is_active = (touch_byte & TouchpadConstants.TOUCH_ACTIVE_MASK) == 0
                touch_id = touch_byte & TouchpadConstants.TOUCH_ID_MASK
                
                if is_active:
                    # Парсинг координаты X (12 бит из байтов touch_base+1 и touch_base+2)
                    # Формат: (byte[touch_base+2] << 8) | byte[touch_base+1] & 0x0FFF
                    x_raw = ((report_data[touch_base + 2] << 8) | report_data[touch_base + 1]) & 0x0FFF
                    
                    # Парсинг координаты Y (12 бит из байтов touch_base+2 и touch_base+3)
                    # Формат: (byte[touch_base+3] << 4) | (byte[touch_base+2] >> 4) & 0x0FFF
                    y_raw = ((report_data[touch_base + 3] << 4) | (report_data[touch_base + 2] >> 4)) & 0x0FFF
                    
                    # Валидация координат для фильтрации ложных касаний
                    # Проверка, находятся ли координаты в разумном диапазоне
                    if (x_raw < TouchpadConstants.MIN_VALID_X or 
                        x_raw > TouchpadConstants.MAX_VALID_X or
                        y_raw < TouchpadConstants.MIN_VALID_Y or 
                        y_raw > TouchpadConstants.MAX_VALID_Y):
                        # Невалидные координаты, обработать как отсутствие касания
                        if self.debug_touchpad and touch_idx == 0:
                            self.get_logger().debug(
                                f"Касание {touch_idx} отфильтровано: невалидные координаты "
                                f"X={x_raw}, Y={y_raw} (валидный диапазон: "
                                f"X={TouchpadConstants.MIN_VALID_X}-{TouchpadConstants.MAX_VALID_X}, "
                                f"Y={TouchpadConstants.MIN_VALID_Y}-{TouchpadConstants.MAX_VALID_Y})"
                            )
                        self.touch_points[touch_idx] = TouchPoint(
                            x=0.0,
                            y=0.0,
                            tracking_id=-1,
                            is_active=False
                        )
                        continue
                    
                    # Дополнительная валидация: проверка на подозрительные паттерны
                    # Значения типа 0, 8, 2048, 4095 часто являются артефактами
                    suspicious_values = [0, 8, 2048, 4095, 4094, 4093]
                    if x_raw in suspicious_values or y_raw in suspicious_values:
                        # Подозрительное значение, вероятно артефакт
                        if self.debug_touchpad and touch_idx == 0:
                            self.get_logger().debug(
                                f"Касание {touch_idx} отфильтровано: подозрительное значение "
                                f"X={x_raw}, Y={y_raw}"
                            )
                        self.touch_points[touch_idx] = TouchPoint(
                            x=0.0,
                            y=0.0,
                            tracking_id=-1,
                            is_active=False
                        )
                        continue
                    
                    # Использовать сырые значения напрямую (без маппинга)
                    x_norm = float(x_raw)
                    y_norm = float(y_raw)
                    
                    if self.debug_touchpad and touch_idx == 0:
                        self.get_logger().debug(
                            f"Touch {touch_idx} parsed: ID={touch_id}, active={is_active}, "
                            f"X_raw={x_raw}, Y_raw={y_raw}, "
                            f"X_norm={x_norm:.3f}, Y_norm={y_norm:.3f}, "
                            f"bytes: {report_data[touch_base:touch_base+4].hex()}"
                        )
                    
                    self.touch_points[touch_idx] = TouchPoint(
                        x=x_norm,
                        y=y_norm,
                        tracking_id=touch_id,
                        is_active=True
                    )
                else:
                    # Нет касания
                    self.touch_points[touch_idx] = TouchPoint(
                        x=0.0,
                        y=0.0,
                        tracking_id=-1,
                        is_active=False
                    )
    
    def _read_hidraw_data(self) -> None:
        """Чтение данных из hidraw устройства в отдельном потоке."""
        if self.hidraw_file is None:
            self.get_logger().warn("Hidraw файл недоступен, данные тачпада не будут читаться")
            return
        
        try:
            # Установка файла в неблокирующий режим
            flags = fcntl.fcntl(self.hidraw_file.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(self.hidraw_file.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
        except Exception as e:
            self.get_logger().debug(f"Не удалось установить неблокирующий режим: {e}")
        
        import time
        try:
            while self.running:
                # Использование select для проверки доступности данных (неблокирующий режим)
                ready, _, _ = select.select([self.hidraw_file], [], [], 0.1)
                
                if ready:
                    # Чтение HID отчета (64 байта для контроллера PS4)
                    report_data = self.hidraw_file.read(TouchpadConstants.REPORT_SIZE)
                    
                    if len(report_data) == 0:
                        # Устройство отключено
                        break
                    
                    if len(report_data) < TouchpadConstants.REPORT_SIZE:
                        # Неполные данные, пропустить
                        continue
                    
                    # Проверка, является ли это входным отчетом (первый байт должен быть 0x11 для PS4)
                    if report_data[0] == 0x11:
                        # Парсинг данных тачпада
                        self._parse_touchpad_data(report_data)
                    elif self.debug_touchpad:
                        self.get_logger().debug(f"Получен отчет с типом 0x{report_data[0]:02x}, ожидался 0x11")
                else:
                    # Данные недоступны, небольшая задержка, чтобы избежать активного цикла
                    time.sleep(0.01)
                
        except OSError as e:
            if e.errno != 11:  # EAGAIN - данные недоступны (ожидаемо в неблокирующем режиме)
                self.get_logger().error(f"OSError при чтении данных hidraw: {e}")
        except Exception as e:
            self.get_logger().error(f"Ошибка при чтении данных hidraw: {e}")
        finally:
            if self.hidraw_file:
                try:
                    self.hidraw_file.close()
                except:
                    pass
    
    def _get_primary_touch_point(self) -> Optional[TouchPoint]:
        """Получение основной точки касания (первое активное касание или среднее, если оба активны).
        
        Returns:
            TouchPoint если есть активное касание, None в противном случае
        """
        with self.data_lock:
            active_touches = [
                tp for tp in self.touch_points.values() if tp.is_active
            ]
            
            if not active_touches:
                return None
            
            if len(active_touches) == 1:
                return active_touches[0]
            
            # Если оба касания активны, вернуть среднюю позицию
            # Это полезно для рисования одиночных штрихов
            avg_x = sum(tp.x for tp in active_touches) / len(active_touches)
            avg_y = sum(tp.y for tp in active_touches) / len(active_touches)
            return TouchPoint(x=avg_x, y=avg_y, tracking_id=0, is_active=True)
    
    def publish_touchpad(self) -> None:
        """Публикация данных тачпада как сообщений ROS2 (только при наличии активного касания)."""
        # Получение основной точки касания (возвращает только активные касания или None)
        touch = self._get_primary_touch_point()
        
        # Публиковать только если есть активное касание
        if touch is None:
            # Нет активного касания - очистить последнее опубликованное касание и ничего не публиковать
            with self.data_lock:
                self.last_published_touch = None
            return
        
        # Активное касание - использовать фактические сырые координаты
        x_to_publish = touch.x
        y_to_publish = touch.y
        
        # Проверка изменения данных (публиковать только при изменении)
        with self.data_lock:
            # Порог для сырых значений (диапазон 0-4095)
            threshold = 1.0
            
            # Проверка значительного изменения координат
            coords_changed = (self.last_published_touch is None or
                            not self.last_published_touch.is_active or
                            abs(self.last_published_touch.x - x_to_publish) >= threshold or
                            abs(self.last_published_touch.y - y_to_publish) >= threshold)
            
            # Публиковать только если координаты изменились
            if not coords_changed:
                # Данные не изменились, пропустить публикацию
                return
            
            # Обновить последнее опубликованное касание
            self.last_published_touch = TouchPoint(
                x=x_to_publish,
                y=y_to_publish,
                tracking_id=touch.tracking_id,
                is_active=True
            )
        
        # Публикация координат касания
        point_msg = PointStamped()
        point_msg.header = Header()
        point_msg.header.stamp = self.get_clock().now().to_msg()
        point_msg.header.frame_id = self.frame_id
        point_msg.point.x = x_to_publish
        point_msg.point.y = y_to_publish
        point_msg.point.z = 0.0  # Не используется
        
        self.touchpad_pub.publish(point_msg)
        
        # Публикация состояния касания (всегда True при публикации)
        state_msg = Bool()
        state_msg.data = True
        self.touch_state_pub.publish(state_msg)
        
        if self.debug_touchpad:
            self.get_logger().debug(f"Опубликовано касание: X={x_to_publish:.3f}, Y={y_to_publish:.3f}, active=True")
    
    def destroy_node(self) -> None:
        """Очистка при уничтожении узла."""
        self.running = False
        if self.hidraw_file:
            try:
                self.hidraw_file.close()
            except:
                pass
        super().destroy_node()


def main(args=None) -> None:
    """Главная точка входа для узла PS4 Touchpad."""
    rclpy.init(args=args)
    
    node = PS4TouchpadNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            rclpy.shutdown()
        except Exception:
            pass  # shutdown мог быть уже вызван


if __name__ == '__main__':
    main()
