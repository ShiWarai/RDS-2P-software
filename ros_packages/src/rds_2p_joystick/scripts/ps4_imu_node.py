#!/usr/bin/env python3
"""
ROS2 узел для чтения данных IMU (акселерометр и гироскоп) с контроллера PS4.

Этот узел читает данные датчиков движения с контроллера PS4 DualShock 4 и публикует
их как сообщения sensor_msgs/msg/Imu в ROS2.

Требования:
- Пакет python3-evdev: sudo apt install python3-evdev
- Доступ к устройствам /dev/input/event* (пользователь должен быть в группе 'input')
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import Header
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
import time
import os
import math
import threading
import re
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    from evdev import InputDevice, categorize, ecodes
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    print("ERROR: python3-evdev not installed. Install with: sudo apt install python3-evdev")


# Константы
class IMUConstants:
    """Константы для обработки данных IMU."""
    # Масштабный коэффициент акселерометра (преобразование сырых значений в g)
    ACCEL_SCALE = 8192.0
    # Масштабный коэффициент гироскопа (преобразование сырых значений в град/с)
    GYRO_SCALE = 163.84
    # Вес комплементарного фильтра для гироскопа (0.98 = 98% гироскоп, 2% акселерометр)
    COMPLEMENTARY_FILTER_ALPHA = 0.98
    # Стандартная гравитация в м/с²
    GRAVITY_MS2 = 9.80665
    # Интервал задержки калибровки в секундах
    CALIBRATION_SLEEP_INTERVAL = 0.01
    # Максимальная дельта времени для интегрирования (проверка безопасности)
    MAX_DT = 0.1
    # Максимальное количество event устройств для проверки
    MAX_EVENT_DEVICES = 20
    # Значения ковариации по умолчанию
    DEFAULT_COVARIANCE = 0.01
    
    # Коды ABS осей для данных IMU (маппинг ds4drv)
    ABS_ACCEL_X = 6   # ABS_THROTTLE
    ABS_ACCEL_Y = 7   # ABS_RUDDER
    ABS_ACCEL_Z = 8   # ABS_WHEEL
    ABS_GYRO_Z = 25   # ABS_DISTANCE
    ABS_GYRO_X = 26   # ABS_TILT_X
    ABS_GYRO_Y = 27   # ABS_TILT_Y
    
    # Коды типов событий
    EV_ABS = 3
    
    # Ожидаемое смещение 1g для акселерометра Z в горизонтальном положении
    ACCEL_Z_1G_OFFSET = 8192.0


@dataclass
class IMURawData:
    """Сырые данные IMU с устройства."""
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 0.0
    gyro_x: float = 0.0
    gyro_y: float = 0.0
    gyro_z: float = 0.0


@dataclass
class IMUCalibratedData:
    """Калиброванные данные IMU в физических единицах."""
    accel_x_g: float = 0.0
    accel_y_g: float = 0.0
    accel_z_g: float = 0.0
    gyro_x_dps: float = 0.0
    gyro_y_dps: float = 0.0
    gyro_z_dps: float = 0.0


@dataclass
class IMUOffsets:
    """Смещения калибровки для IMU."""
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 0.0
    gyro_x: float = 0.0
    gyro_y: float = 0.0
    gyro_z: float = 0.0


@dataclass
class Orientation:
    """Ориентация в углах Эйлера (градусы)."""
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0


class PS4IMUNode(Node):
    """ROS2 узел для данных IMU контроллера PS4."""

    def __init__(self) -> None:
        super().__init__('ps4_imu_node')
        
        # Настройка параметров
        self._setup_parameters()
        
        # Настройка устройства
        if not self._setup_device():
            return
        
        # Настройка структур данных
        self._setup_data_structures()
        
        # Настройка публикаторов и таймеров
        self._setup_publishers()
        
        # Запуск потока чтения
        self._start_reading_thread()
        
        # Выполнение калибровки
        self._calibrate_imu(self.calibration_samples, self.calibration_duration)
        
        # Инициализация ориентации
        self._initialize_orientation()
    
    def _setup_parameters(self) -> None:
        """Настройка и получение параметров ROS."""
        # Объявление параметров
        # event_device по умолчанию пустое - устройство будет найдено автоматически
        self.declare_parameter('event_device', '')
        self.declare_parameter('frame_id', 'ps4_controller')
        self.declare_parameter('parent_frame_id', 'odom_link')
        self.declare_parameter('publish_rate', 50.0)
        self.declare_parameter('update_rate', 100.0)
        self.declare_parameter('publish_tf', True)
        self.declare_parameter('calibration_samples', 200)
        self.declare_parameter('calibration_duration', 2.0)
        self.declare_parameter('filter_type', 'complementary')  # 'complementary' или 'kalman'
        self.declare_parameter('kalman_q', 0.01)  # Ковариация шума процесса
        self.declare_parameter('kalman_r', 0.1)   # Ковариация шума измерений
        
        # Получение параметров
        self.event_device_param = self.get_parameter('event_device').get_parameter_value().string_value
        self.frame_id = self.get_parameter('frame_id').get_parameter_value().string_value
        self.parent_frame_id = self.get_parameter('parent_frame_id').get_parameter_value().string_value
        self.publish_rate = self.get_parameter('publish_rate').get_parameter_value().double_value
        self.update_rate = self.get_parameter('update_rate').get_parameter_value().double_value
        self.publish_tf = self.get_parameter('publish_tf').get_parameter_value().bool_value
        self.calibration_samples = self.get_parameter('calibration_samples').get_parameter_value().integer_value
        self.calibration_duration = self.get_parameter('calibration_duration').get_parameter_value().double_value
        self.filter_type = self.get_parameter('filter_type').get_parameter_value().string_value
        self.kalman_q = self.get_parameter('kalman_q').get_parameter_value().double_value
        self.kalman_r = self.get_parameter('kalman_r').get_parameter_value().double_value
    
    def _setup_data_structures(self) -> None:
        """Инициализация структур данных и блокировок."""
        # Блокировка потока для потокобезопасного доступа
        self.data_lock = threading.Lock()
        
        # Сырые данные IMU
        self.raw_data = IMURawData()
        
        # Смещения калибровки
        self.offsets = IMUOffsets()
        self.calibrated = False
        
        # Ориентация
        self.orientation = Orientation()
        
        # Параметр комплементарного фильтра
        self.alpha = IMUConstants.COMPLEMENTARY_FILTER_ALPHA
        
        # Время для интегрирования
        self.last_update_time: Optional[float] = None
        
        # Состояние фильтра Калмана (если используется фильтр Калмана)
        if self.filter_type == 'kalman':
            self._init_kalman_filter()
    
    def _setup_device(self) -> bool:
        """Настройка и открытие входного устройства. Возвращает True при успехе."""
        # Проверка доступности evdev
        if not EVDEV_AVAILABLE:
            self.get_logger().error("python3-evdev недоступен. Невозможно читать данные IMU.")
            return False
        
        # Инициализация device
        self.device = None
        event_device = self.event_device_param.strip() if self.event_device_param else ''
        
        # Сначала ищем устройство с поддержкой IMU автоматически
        found_device = self._find_ps4_device_with_imu()
        
        # Если не нашли, читаем логи ds4drv и проверяем устройства оттуда
        if not found_device:
            devices_from_log = self._parse_ds4drv_log()
            
            if devices_from_log:
                # Пробуем использовать устройства из логов
                for dev_path in devices_from_log:
                    try:
                        test_dev = InputDevice(dev_path)
                        caps = test_dev.capabilities()
                        if IMUConstants.EV_ABS in caps:
                            abs_axes = [ax[0] for ax in caps[IMUConstants.EV_ABS]]
                            has_imu = any(ax in [
                                IMUConstants.ABS_GYRO_X,
                                IMUConstants.ABS_GYRO_Y,
                                IMUConstants.ABS_GYRO_Z
                            ] for ax in abs_axes)
                            if has_imu:
                                found_device = dev_path
                                test_dev.close()
                                break
                        test_dev.close()
                    except Exception:
                        continue
        
        if found_device:
            try:
                self.device = InputDevice(found_device)
                # Проверяем, что устройство действительно имеет оси IMU
                caps = self.device.capabilities()
                has_imu = False
                if IMUConstants.EV_ABS in caps:
                    abs_axes = [ax[0] for ax in caps[IMUConstants.EV_ABS]]
                    has_imu = any(ax in [
                        IMUConstants.ABS_GYRO_X,
                        IMUConstants.ABS_GYRO_Y,
                        IMUConstants.ABS_GYRO_Z
                    ] for ax in abs_axes)
                
                if has_imu:
                    self.get_logger().info(
                        f"Найдено устройство PS4 с IMU: {self.device.name} на {found_device}"
                    )
                    return True
                else:
                    self.device.close()
                    self.device = None
            except (OSError, PermissionError):
                self.device = None
        
        # Если не нашли через автоматический поиск, пробуем указанное устройство (если оно указано)
        if self.device is None and event_device and event_device != '':
            try:
                self.device = InputDevice(event_device)
                caps = self.device.capabilities()
                has_imu = False
                if IMUConstants.EV_ABS in caps:
                    abs_axes = [ax[0] for ax in caps[IMUConstants.EV_ABS]]
                    has_imu = any(ax in [
                        IMUConstants.ABS_GYRO_X,
                        IMUConstants.ABS_GYRO_Y,
                        IMUConstants.ABS_GYRO_Z
                    ] for ax in abs_axes)
                
                if has_imu:
                    self.get_logger().info(
                        f"Найдено устройство PS4 с IMU: {self.device.name} на {event_device}"
                    )
                    return True
                else:
                    self.device.close()
                    self.device = None
            except (FileNotFoundError, PermissionError, OSError):
                self.device = None
        
        if self.device is None:
            return False
        
        return True
    
    def _setup_publishers(self) -> None:
        """Настройка публикаторов ROS и таймеров."""
        # Создание публикатора
        self.imu_pub = self.create_publisher(Imu, '/joy/imu', 10)
        
        # Создание TF транслятора
        if self.publish_tf:
            self.tf_broadcaster = TransformBroadcaster(self)
        
        # Создание таймера для обновления ориентации (высокая частота для точности)
        update_timer_period = 1.0 / self.update_rate
        self.update_timer = self.create_timer(update_timer_period, self._update_orientation_timer)
        
        # Создание таймера для публикации сообщений IMU (низкая частота)
        publish_timer_period = 1.0 / self.publish_rate
        self.publish_timer = self.create_timer(publish_timer_period, self.publish_imu)
    
    def _start_reading_thread(self) -> None:
        """Запуск потока для чтения событий устройства."""
        self.reading_thread = threading.Thread(target=self._read_device_events, daemon=True)
        self.reading_thread.start()
    
    def _initialize_orientation(self) -> None:
        """Инициализация ориентации из акселерометра."""
        with self.data_lock:
            raw = self.raw_data
            offsets = self.offsets
        
        # Преобразование в физические единицы
        calibrated = self._convert_raw_to_physical(raw, offsets)
        
        # Вычисление начальной ориентации
        self.orientation.roll = math.degrees(
            math.atan2(calibrated.accel_y_g, calibrated.accel_z_g)
        )
        self.orientation.pitch = math.degrees(
            math.atan2(
                -calibrated.accel_x_g,
                math.sqrt(calibrated.accel_y_g ** 2 + calibrated.accel_z_g ** 2)
            )
        )
        self.orientation.yaw = 0.0
        
        self.last_update_time = time.time()
    
    def _find_ps4_device(self) -> Optional[str]:
        """Попытка автоматически найти event устройство контроллера PS4."""
        return self._find_ps4_device_with_imu()
    
    def _parse_ds4drv_log(self) -> list[str]:
        """Парсит логи ds4drv для извлечения путей к устройствам.
        
        Returns:
            Список путей к event устройствам, созданным ds4drv (последние записи)
        """
        devices = []
        ds4drv_log_path = os.path.expanduser('~/.cache/ds4drv.log')
        
        if not os.path.exists(ds4drv_log_path):
            return devices
        
        try:
            with open(ds4drv_log_path, 'r') as f:
                lines = f.readlines()
                
            # Ищем строки вида: [info][controller 1] Created devices /dev/input/js0 (joystick) /dev/input/event6 (evdev)
            # Берём только последние записи (последние 20 строк), чтобы получить актуальные устройства
            recent_lines = lines[-20:] if len(lines) > 20 else lines
            for line in recent_lines:
                if 'Created devices' in line and 'evdev' in line:
                    # Извлекаем путь к event устройству
                    match = re.search(r'/dev/input/event\d+', line)
                    if match:
                        event_path = match.group(0)
                        if event_path not in devices:
                            devices.append(event_path)
        except Exception:
            pass
        
        return devices
    
    def _find_ps4_device_with_imu(self) -> Optional[str]:
        """Попытка автоматически найти event устройство контроллера PS4 с поддержкой IMU.
        
        Проверяет устройства по наличию осей гироскопа (ABS_GYRO_X, ABS_GYRO_Y, ABS_GYRO_Z),
        что является надёжным индикатором устройства с поддержкой IMU через ds4drv.
        """
        ps4_keywords = ['Wireless Controller', 'Sony', 'DualShock', 'PS4', 'Computer Entertainment']
        
        # Сначала попытка найти устройство ds4drv с осями IMU
        # Устройства ds4drv имеют оси гироскопа (ABS_GYRO_X, ABS_GYRO_Y, ABS_GYRO_Z)
        devices_with_imu: list[Tuple[str, str, list]] = []  # (path, name, gyro_axes)
        devices_without_imu: list[Tuple[str, str]] = []
        all_checked_devices = []
        
        for i in range(IMUConstants.MAX_EVENT_DEVICES):
            event_path = f'/dev/input/event{i}'
            if not os.path.exists(event_path):
                continue
            
            try:
                dev = InputDevice(event_path)
                dev_name = dev.name
                
                # Проверка возможностей - ищем оси IMU
                caps = dev.capabilities()
                has_imu_axes = False
                gyro_axes_found = []
                if IMUConstants.EV_ABS in caps:
                    abs_axes = [ax[0] for ax in caps[IMUConstants.EV_ABS]]
                    # Проверяем наличие осей гироскопа (наиболее надёжный индикатор)
                    for axis in abs_axes:
                        if axis in [
                            IMUConstants.ABS_GYRO_X,
                            IMUConstants.ABS_GYRO_Y,
                            IMUConstants.ABS_GYRO_Z
                        ]:
                            has_imu_axes = True
                            gyro_axes_found.append(axis)
                
                # Проверка, является ли это контроллером PS4
                is_ps4 = any(keyword.lower() in dev_name.lower() for keyword in ps4_keywords)
                
                all_checked_devices.append((event_path, dev_name, is_ps4, has_imu_axes))
                
                if is_ps4:
                    if has_imu_axes:
                        devices_with_imu.append((event_path, dev_name, gyro_axes_found))
                    else:
                        devices_without_imu.append((event_path, dev_name))
                
                dev.close()
            except (OSError, PermissionError, FileNotFoundError) as e:
                all_checked_devices.append((event_path, f"Ошибка: {e}", False, False))
                continue
        
        # Возвращаем только устройства с поддержкой IMU
        if devices_with_imu:
            return devices_with_imu[0][0]
        
        return None
    
    def _read_device_events(self) -> None:
        """Чтение событий из входного устройства в отдельном потоке."""
        if self.device is None:
            return
        
        try:
            for event in self.device.read_loop():
                if event.type == ecodes.EV_ABS:
                    # Обработка событий абсолютных осей
                    # ds4drv предоставляет данные IMU через специальные ABS оси
                    try:
                        raw_value = event.value
                        
                        # Обновление сырых данных с блокировкой потока
                        with self.data_lock:
                            if event.code == IMUConstants.ABS_ACCEL_X:
                                self.raw_data.accel_x = raw_value
                            elif event.code == IMUConstants.ABS_ACCEL_Y:
                                self.raw_data.accel_y = raw_value
                            elif event.code == IMUConstants.ABS_ACCEL_Z:
                                self.raw_data.accel_z = raw_value
                            elif event.code == IMUConstants.ABS_GYRO_X:
                                self.raw_data.gyro_x = raw_value
                            elif event.code == IMUConstants.ABS_GYRO_Y:
                                self.raw_data.gyro_y = raw_value
                            elif event.code == IMUConstants.ABS_GYRO_Z:
                                self.raw_data.gyro_z = raw_value
                    except (ValueError, KeyError):
                        # Игнорировать невалидные коды событий
                        pass
                    
                elif event.type == ecodes.EV_SYN:
                    # Событие синхронизации - игнорировать
                    pass
                            
        except (OSError, RuntimeError):
            pass
    
    def _convert_raw_to_physical(
        self, raw: IMURawData, offsets: IMUOffsets
    ) -> IMUCalibratedData:
        """Преобразование сырых значений IMU в физические единицы.
        
        Args:
            raw: Сырые данные IMU
            offsets: Смещения калибровки
            
        Returns:
            Калиброванные данные IMU в физических единицах
        """
        # Акселерометр: преобразование в g
        accel_x_g = (raw.accel_x - offsets.accel_x) / IMUConstants.ACCEL_SCALE
        accel_y_g = (raw.accel_y - offsets.accel_y) / IMUConstants.ACCEL_SCALE
        accel_z_g = (raw.accel_z - offsets.accel_z) / IMUConstants.ACCEL_SCALE
        
        # Гироскоп: преобразование в град/с
        gyro_x_dps = (raw.gyro_x - offsets.gyro_x) / IMUConstants.GYRO_SCALE
        gyro_y_dps = (raw.gyro_y - offsets.gyro_y) / IMUConstants.GYRO_SCALE
        gyro_z_dps = (raw.gyro_z - offsets.gyro_z) / IMUConstants.GYRO_SCALE
        
        return IMUCalibratedData(
            accel_x_g=accel_x_g,
            accel_y_g=accel_y_g,
            accel_z_g=accel_z_g,
            gyro_x_dps=gyro_x_dps,
            gyro_y_dps=gyro_y_dps,
            gyro_z_dps=gyro_z_dps
        )
    
    def _init_kalman_filter(self) -> None:
        """Инициализация состояния фильтра Калмана."""
        # Состояние: [roll, pitch, yaw] в градусах
        self.kalman_state = [0.0, 0.0, 0.0]
        # Матрица ковариации (3x3)
        self.kalman_P = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0]
        ]
        # Ковариация шума процесса (Q)
        self.kalman_Q = self.kalman_q
        # Ковариация шума измерений (R)
        self.kalman_R = self.kalman_r
    
    def _update_orientation_timer(self) -> None:
        """Обратный вызов таймера для обновления ориентации с высокой частотой."""
        self._update_orientation()
    
    def _update_orientation(self) -> None:
        """Обновление ориентации с использованием выбранного фильтра (комплементарный или Калмана)."""
        current_time = time.time()
        
        if self.last_update_time is None:
            self.last_update_time = current_time
            return
        
        dt = current_time - self.last_update_time
        if dt <= 0 or dt > IMUConstants.MAX_DT:
            self.last_update_time = current_time
            return
        
        if not self.calibrated:
            return
        
        # Получение сырых данных с блокировкой
        with self.data_lock:
            raw = IMURawData(
                accel_x=self.raw_data.accel_x,
                accel_y=self.raw_data.accel_y,
                accel_z=self.raw_data.accel_z,
                gyro_x=self.raw_data.gyro_x,
                gyro_y=self.raw_data.gyro_y,
                gyro_z=self.raw_data.gyro_z
            )
            offsets = IMUOffsets(
                accel_x=self.offsets.accel_x,
                accel_y=self.offsets.accel_y,
                accel_z=self.offsets.accel_z,
                gyro_x=self.offsets.gyro_x,
                gyro_y=self.offsets.gyro_y,
                gyro_z=self.offsets.gyro_z
            )
            orientation = Orientation(
                roll=self.orientation.roll,
                pitch=self.orientation.pitch,
                yaw=self.orientation.yaw
            )
        
        # Преобразование в физические единицы
        calibrated = self._convert_raw_to_physical(raw, offsets)
        
        # Обновление ориентации в зависимости от типа фильтра
        if self.filter_type == 'kalman':
            new_orientation = self._update_orientation_kalman(calibrated, orientation, dt)
        else:
            new_orientation = self._update_orientation_complementary(calibrated, orientation, dt)
        
        # Обновление ориентации с блокировкой
        with self.data_lock:
            self.orientation = new_orientation
        
        self.last_update_time = current_time
    
    def _update_orientation_complementary(
        self, calibrated: IMUCalibratedData, orientation: Orientation, dt: float
    ) -> Orientation:
        """Обновление ориентации с использованием комплементарного фильтра.
        
        На основе реализации mpu6500_ros: углы хранятся в градусах.
        """
        # Вычисление ориентации из акселерометра (в градусах)
        accel_roll = math.degrees(
            math.atan2(calibrated.accel_y_g, calibrated.accel_z_g)
        )
        accel_pitch = math.degrees(
            math.atan2(
                -calibrated.accel_x_g,
                math.sqrt(calibrated.accel_y_g ** 2 + calibrated.accel_z_g ** 2)
            )
        )
        
        # Интегрирование гироскопа (в градусах)
        gyro_roll = orientation.roll + calibrated.gyro_x_dps * dt
        gyro_pitch = orientation.pitch + calibrated.gyro_y_dps * dt
        gyro_yaw = orientation.yaw + calibrated.gyro_z_dps * dt
        
        # Комплементарный фильтр: комбинация интегрирования гироскопа с акселерометром
        new_roll = self.alpha * gyro_roll + (1.0 - self.alpha) * accel_roll
        new_pitch = self.alpha * gyro_pitch + (1.0 - self.alpha) * accel_pitch
        new_yaw = gyro_yaw  # Нет коррекции для yaw (нет магнитометра)
        
        return Orientation(roll=new_roll, pitch=new_pitch, yaw=new_yaw)
    
    def _update_orientation_kalman(
        self, calibrated: IMUCalibratedData, orientation: Orientation, dt: float
    ) -> Orientation:
        """Обновление ориентации с использованием фильтра Калмана.
        
        Упрощенный фильтр Калмана для оценки ориентации.
        Состояние: [roll, pitch, yaw] в градусах
        """
        # Шаг предсказания: интегрирование гироскопа
        predicted_roll = orientation.roll + calibrated.gyro_x_dps * dt
        predicted_pitch = orientation.pitch + calibrated.gyro_y_dps * dt
        predicted_yaw = orientation.yaw + calibrated.gyro_z_dps * dt
        
        # Обновление ковариации (упрощено - добавление шума процесса)
        P = self.kalman_P
        Q = self.kalman_Q
        P[0][0] += Q * dt
        P[1][1] += Q * dt
        P[2][2] += Q * dt
        
        # Измерение: ориентация из акселерометра (только roll и pitch)
        accel_roll = math.degrees(
            math.atan2(calibrated.accel_y_g, calibrated.accel_z_g)
        )
        accel_pitch = math.degrees(
            math.atan2(
                -calibrated.accel_x_g,
                math.sqrt(calibrated.accel_y_g ** 2 + calibrated.accel_z_g ** 2)
            )
        )
        
        # Коэффициент Калмана (упрощено для диагональной ковариации)
        R = self.kalman_R
        K_roll = P[0][0] / (P[0][0] + R)
        K_pitch = P[1][1] / (P[1][1] + R)
        
        # Обновление состояния
        new_roll = predicted_roll + K_roll * (accel_roll - predicted_roll)
        new_pitch = predicted_pitch + K_pitch * (accel_pitch - predicted_pitch)
        new_yaw = predicted_yaw  # Нет измерения для yaw
        
        # Обновление ковариации
        P[0][0] = (1.0 - K_roll) * P[0][0]
        P[1][1] = (1.0 - K_pitch) * P[1][1]
        
        self.kalman_P = P
        
        return Orientation(roll=new_roll, pitch=new_pitch, yaw=new_yaw)
    
    def _euler_to_quaternion(
        self, roll: float, pitch: float, yaw: float
    ) -> Tuple[float, float, float, float]:
        """Преобразование углов Эйлера (roll, pitch, yaw в градусах) в кватернион (w, x, y, z).
        
        На основе реализации mpu6500_ros: углы в градусах, преобразуются в радианы и делятся на 2.
        
        Args:
            roll: Угол крена в градусах
            pitch: Угол тангажа в градусах
            yaw: Угол рыскания в градусах
            
        Returns:
            Кватернион как (w, x, y, z)
        """
        # Преобразование градусов в радианы и деление на 2
        roll_rad = math.radians(roll) / 2.0
        pitch_rad = math.radians(pitch) / 2.0
        yaw_rad = math.radians(yaw) / 2.0
        
        # Вычисление компонентов кватерниона
        w = (math.cos(roll_rad) * math.cos(pitch_rad) * math.cos(yaw_rad) +
             math.sin(roll_rad) * math.sin(pitch_rad) * math.sin(yaw_rad))
        x = (math.sin(roll_rad) * math.cos(pitch_rad) * math.cos(yaw_rad) -
             math.cos(roll_rad) * math.sin(pitch_rad) * math.sin(yaw_rad))
        y = (math.cos(roll_rad) * math.sin(pitch_rad) * math.cos(yaw_rad) +
             math.sin(roll_rad) * math.cos(pitch_rad) * math.sin(yaw_rad))
        z = (math.cos(roll_rad) * math.cos(pitch_rad) * math.sin(yaw_rad) -
             math.sin(roll_rad) * math.sin(pitch_rad) * math.cos(yaw_rad))
        
        return w, x, y, z
    
    def _publish_tf_transform(self, imu_msg: Imu) -> None:
        """Публикация TF трансформации для ориентации контроллера.
        
        Args:
            imu_msg: Сообщение IMU с данными ориентации
        """
        transform = TransformStamped()
        
        # Установка заголовка
        transform.header.stamp = imu_msg.header.stamp
        transform.header.frame_id = self.parent_frame_id
        transform.child_frame_id = self.frame_id
        
        # Перевод (позиция контроллера относительно родительского фрейма)
        # Для контроллера PS4 предполагаем, что он находится в начале координат
        transform.transform.translation.x = 0.0
        transform.transform.translation.y = 0.0
        transform.transform.translation.z = 0.0
        
        # Вращение из ориентации IMU
        transform.transform.rotation.x = imu_msg.orientation.x
        transform.transform.rotation.y = imu_msg.orientation.y
        transform.transform.rotation.z = imu_msg.orientation.z
        transform.transform.rotation.w = imu_msg.orientation.w
        
        # Отправка трансформации
        self.tf_broadcaster.sendTransform(transform)
    
    def _calibrate_imu(self, num_samples: int, duration: float) -> None:
        """Выполнение калибровки путем сбора образцов.
        
        Args:
            num_samples: Количество образцов для сбора
            duration: Максимальная длительность в секундах
        """
        
        accel_sum_x = 0.0
        accel_sum_y = 0.0
        accel_sum_z = 0.0
        gyro_sum_x = 0.0
        gyro_sum_y = 0.0
        gyro_sum_z = 0.0
        
        samples_collected = 0
        start_time = time.time()
        
        # Событие для неблокирующего ожидания
        data_event = threading.Event()
        
        # Сбор образцов
        while samples_collected < num_samples and (time.time() - start_time) < duration:
            # Ожидание данных с таймаутом (неблокирующий режим)
            data_event.wait(timeout=IMUConstants.CALIBRATION_SLEEP_INTERVAL)
            data_event.clear()
            
            # Получение текущих сырых значений с блокировкой
            with self.data_lock:
                raw = self.raw_data
            
            # Проверка наличия валидных данных
            if (raw.accel_x != 0.0 or raw.accel_y != 0.0 or raw.accel_z != 0.0 or
                raw.gyro_x != 0.0 or raw.gyro_y != 0.0 or raw.gyro_z != 0.0):
                accel_sum_x += raw.accel_x
                accel_sum_y += raw.accel_y
                accel_sum_z += raw.accel_z
                gyro_sum_x += raw.gyro_x
                gyro_sum_y += raw.gyro_y
                gyro_sum_z += raw.gyro_z
                samples_collected += 1
        
        if samples_collected > 0:
            # Вычисление смещений
            with self.data_lock:
                self.offsets.accel_x = accel_sum_x / samples_collected
                self.offsets.accel_y = accel_sum_y / samples_collected
                # Для акселерометра Z вычитаем ожидаемое значение гравитации, когда контроллер горизонтален
                self.offsets.accel_z = (
                    accel_sum_z / samples_collected - IMUConstants.ACCEL_Z_1G_OFFSET
                )
                
                self.offsets.gyro_x = gyro_sum_x / samples_collected
                self.offsets.gyro_y = gyro_sum_y / samples_collected
                self.offsets.gyro_z = gyro_sum_z / samples_collected
                
                self.calibrated = True
        else:
            # Использовать нулевые смещения как запасной вариант
            with self.data_lock:
                self.calibrated = True
    
    def publish_imu(self) -> None:
        """Публикация данных IMU как сообщения ROS2.
        
        Примечание: _update_orientation() уже вызывается update_timer,
        поэтому не нужно вызывать его здесь снова.
        """
        if self.device is None or not self.calibrated:
            return
        
        # Получение текущих данных с блокировкой
        with self.data_lock:
            raw = IMURawData(
                accel_x=self.raw_data.accel_x,
                accel_y=self.raw_data.accel_y,
                accel_z=self.raw_data.accel_z,
                gyro_x=self.raw_data.gyro_x,
                gyro_y=self.raw_data.gyro_y,
                gyro_z=self.raw_data.gyro_z
            )
            offsets = IMUOffsets(
                accel_x=self.offsets.accel_x,
                accel_y=self.offsets.accel_y,
                accel_z=self.offsets.accel_z,
                gyro_x=self.offsets.gyro_x,
                gyro_y=self.offsets.gyro_y,
                gyro_z=self.offsets.gyro_z
            )
            orientation = Orientation(
                roll=self.orientation.roll,
                pitch=self.orientation.pitch,
                yaw=self.orientation.yaw
            )
        
        # Преобразование в физические единицы
        calibrated = self._convert_raw_to_physical(raw, offsets)
        
        # Создание сообщения IMU
        imu_msg = Imu()
        imu_msg.header = Header()
        imu_msg.header.stamp = self.get_clock().now().to_msg()
        imu_msg.header.frame_id = self.frame_id
        
        # Установка линейного ускорения (преобразование из g в м/с²)
        imu_msg.linear_acceleration.x = calibrated.accel_x_g * IMUConstants.GRAVITY_MS2
        imu_msg.linear_acceleration.y = calibrated.accel_y_g * IMUConstants.GRAVITY_MS2
        imu_msg.linear_acceleration.z = calibrated.accel_z_g * IMUConstants.GRAVITY_MS2
        
        # Установка угловой скорости (преобразование из град/с в рад/с)
        imu_msg.angular_velocity.x = math.radians(calibrated.gyro_x_dps)
        imu_msg.angular_velocity.y = math.radians(calibrated.gyro_y_dps)
        imu_msg.angular_velocity.z = math.radians(calibrated.gyro_z_dps)
        
        # Вычисление и установка кватерниона ориентации
        q_w, q_x, q_y, q_z = self._euler_to_quaternion(
            orientation.roll, orientation.pitch, orientation.yaw
        )
        imu_msg.orientation.w = q_w
        imu_msg.orientation.x = q_x
        imu_msg.orientation.y = q_y
        imu_msg.orientation.z = q_z
        
        # Установка матриц ковариации
        cov = IMUConstants.DEFAULT_COVARIANCE
        imu_msg.orientation_covariance[0] = cov  # xx
        imu_msg.orientation_covariance[4] = cov  # yy
        imu_msg.orientation_covariance[8] = cov  # zz
        
        imu_msg.angular_velocity_covariance[0] = cov
        imu_msg.angular_velocity_covariance[4] = cov
        imu_msg.angular_velocity_covariance[8] = cov
        
        imu_msg.linear_acceleration_covariance[0] = cov
        imu_msg.linear_acceleration_covariance[4] = cov
        imu_msg.linear_acceleration_covariance[8] = cov
        
        # Публикация сообщения
        self.imu_pub.publish(imu_msg)
        
        # Публикация TF трансформации
        if self.publish_tf:
            self._publish_tf_transform(imu_msg)


def main(args=None) -> None:
    """Главная точка входа для узла PS4 IMU."""
    rclpy.init(args=args)
    
    node = PS4IMUNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if hasattr(node, 'device') and node.device:
                node.device.close()
        except Exception:
            pass
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

