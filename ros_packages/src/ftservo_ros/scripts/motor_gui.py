#!/usr/bin/env python3

import os
import yaml
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from ftservo_ros.msg import (
    MotorStates, MotorState,
    MotorTelemetries, MotorTelemetry,
    MotorCommands, MotorCommand,
    MotorParams, MotorParam, MotorJointMapping
)
from std_msgs.msg import Bool
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from typing import Dict, Optional


class MotorTestGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FTServo Motor Test GUI")
        self.root.geometry("900x800")
        
        # ROS2 node
        rclpy.init()
        self.node = Node('motor_test_gui')
        
        # Объявляем параметры
        self.node.declare_parameter('config_file', '')
        
        # QoS для надежной доставки
        self.qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            depth=10
        )
        
        # QoS для сенсорных данных (SENSOR_DATA профиль)
        self.sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        
        # Публикаторы и подписчики
        self.control_cmd_pub = self.node.create_publisher(
            MotorCommands, 'motors/commands', self.qos
        )
        self.params_pub = self.node.create_publisher(
            MotorParams, 'motors/params', self.qos
        )
        self.states_sub = self.node.create_subscription(
            MotorStates, 'motors/states', self.states_callback, self.sensor_qos
        )
        self.telemetry_sub = self.node.create_subscription(
            MotorTelemetries, 'motors/telemetries', self.telemetry_callback, self.sensor_qos
        )
        self.mapping_sub = self.node.create_subscription(
            MotorJointMapping, 'motors/joint_mapping', self.mapping_callback, self.qos
        )
        
        # Загружаем конфигурацию моторов
        self.load_motor_config()
        
        # Словарь для хранения данных о двигателях
        self.motors_states: Dict[int, MotorState] = {}      # Критичные данные движения
        self.motors_telemetry: Dict[int, MotorTelemetry] = {}  # Некритичные данные
        self.motor_names: Dict[int, str] = {}  # Словарь ID -> имя двигателя
        self.motor_configs: Dict[int, dict] = {}  # Конфигурации моторов
        self.motor_bindings: Dict[int, dict] = {}  # Привязки мотор-сустав
        
        # Словарь для расшифровки кодов ошибок Feetech сервоприводов
        self.error_codes = {
            0: "No Error",
            1: "Voltage Error",
            2: "Temperature Error", 
            3: "Overload Error",
            4: "Position Error",
            5: "Speed Error",
            6: "Communication Error",
            7: "EEPROM Error",
            8: "Motor Error",
            9: "Encoder Error",
            10: "PID Error",
            11: "Target Error",
            12: "System Error"
        }
        
        # Переменные для управления постоянным обновлением
        self.always_update_timer = None
        self.update_interval = 10  # фиксированный интервал 10 миллисекунд для режима Always Update
        self.commands_sent_count = 0  # Счетчик отправленных команд
        
        self.setup_ui()
        
        # Обработчик закрытия окна
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Запуск ROS2 в отдельном потоке
        self.ros_thread = threading.Thread(target=self.ros_spin, daemon=True)
        self.ros_thread.start()
    
    def load_motor_config(self):
        """Загружает конфигурацию моторов из YAML файла"""
        try:
            # Получаем путь к конфигурационному файлу из параметров ROS2
            config_file_param = self.node.get_parameter('config_file').value
            
            if config_file_param:
                # Используем путь из параметра
                config_path = config_file_param
                self.node.get_logger().info(f"Loading config from parameter: {config_path}")
            else:
                # Используем путь по умолчанию
                config_path = os.path.join(
                    os.path.dirname(__file__), 
                    '..', 'config', 'config_example.yaml'
                )
                self.node.get_logger().info(f"Loading config from default path: {config_path}")
            
            # Проверяем, существует ли файл
            if not os.path.exists(config_path):
                raise FileNotFoundError(f"Configuration file not found: {config_path}")
            
            with open(config_path, 'r', encoding='utf-8') as file:
                config_data = yaml.safe_load(file)
            
            # Загружаем типы двигателей
            self.motor_types = {}
            if 'motor_types' in config_data:
                self.motor_types = config_data['motor_types']
            
            # Загружаем конфигурации моторов
            self.motor_configs = {}
            if 'motors' in config_data:
                for motor_name, motor_config in config_data['motors'].items():
                    motor_id = motor_config['id']
                    motor_type = motor_config['type']
                    
                    # Получаем конфигурацию типа
                    if motor_type in self.motor_types:
                        type_config = self.motor_types[motor_type]
                        
                        # Объединяем конфигурацию мотора с параметрами типа
                        zero_offset_units = motor_config.get('zero_offset_units', 0)
                        # Вычисляем zero_offset в радианах
                        zero_offset_rad = zero_offset_units / type_config['motor_units_per_radian']
                        
                        full_config = {
                            'name': motor_name,
                            'joint_name': motor_config['joint_name'],
                            'type': motor_type,
                            'min_position': motor_config.get('min_position', 0),
                            'max_position': motor_config.get('max_position', 0),
                            'zero_offset_units': zero_offset_units,
                            'zero_offset': zero_offset_rad,  # Добавляем zero_offset в радианах
                            'min_position_units': motor_config.get('min_position_units', type_config['min_position_units']),
                            'max_position_units': motor_config.get('max_position_units', type_config['max_position_units']),
                            'reversed': motor_config.get('reversed', False),
                            # Параметры из типа
                            'min_velocity_units': type_config['min_velocity_units'],
                            'max_velocity_units': type_config['max_velocity_units'],
                            'min_acceleration_units': type_config['min_acceleration_units'],
                            'max_acceleration_units': type_config['max_acceleration_units'],
                            'voltage_scale': type_config['voltage_scale'],
                            'current_scale': type_config['current_scale'],
                            'effort_scale': type_config['effort_scale'],
                            'max_velocity': type_config['max_velocity'],
                            'max_acceleration': type_config['max_acceleration'],
                            'conversion': type_config
                        }
                        
                        self.motor_configs[motor_id] = full_config
                        

            
            self.node.get_logger().info(f"Loaded configuration for {len(self.motor_configs)} motors")
            
        except Exception as e:
            self.node.get_logger().error(f"Failed to load motor configuration: {e}")
            # Устанавливаем значения по умолчанию
            self.motor_configs = {}
            self.motor_types = {}
        
    def setup_ui(self):
        # Основной фрейм
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Конфигурация сетки
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Левая панель - выбор двигателя
        left_frame = ttk.LabelFrame(main_frame, text="Motor Selection", padding="5")
        left_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))
        
        ttk.Label(left_frame, text="Select Motor:").grid(row=0, column=0, sticky=tk.W)
        self.motor_var = tk.StringVar()
        self.motor_combo = ttk.Combobox(left_frame, textvariable=self.motor_var, state="readonly")
        self.motor_combo.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        self.motor_combo.bind('<<ComboboxSelected>>', self.on_motor_selected)
        
        # Кнопки управления
        ttk.Button(left_frame, text="Enable All", command=self.enable_all).grid(row=2, column=0, sticky=(tk.W, tk.E), pady=2)
        ttk.Button(left_frame, text="Disable All", command=self.disable_all).grid(row=3, column=0, sticky=(tk.W, tk.E), pady=2)
        ttk.Button(left_frame, text="Home All", command=self.home_all).grid(row=4, column=0, sticky=(tk.W, tk.E), pady=2)
        
        # Правая панель - управление выбранным двигателем
        right_frame = ttk.LabelFrame(main_frame, text="Motor Control", padding="5")
        right_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        right_frame.columnconfigure(1, weight=1)
        
        # Позиция
        ttk.Label(right_frame, text="Position (rad):").grid(row=0, column=0, sticky=tk.W)
        self.position_var = tk.DoubleVar(value=0.0)
        self.position_scale = ttk.Scale(right_frame, from_=-3.14, to=3.14, 
                                       variable=self.position_var, orient=tk.HORIZONTAL)
        self.position_scale.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0))
        self.position_entry = ttk.Entry(right_frame, textvariable=self.position_var, width=10)
        self.position_entry.grid(row=0, column=2, padx=(5, 0))
        
        # Скорость
        ttk.Label(right_frame, text="Velocity (rad/s):").grid(row=1, column=0, sticky=tk.W)
        self.velocity_var = tk.DoubleVar(value=1.0)
        self.velocity_scale = ttk.Scale(right_frame, from_=0.0, to=5.0, 
                                       variable=self.velocity_var, orient=tk.HORIZONTAL)
        self.velocity_scale.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(5, 0))
        self.velocity_entry = ttk.Entry(right_frame, textvariable=self.velocity_var, width=10)
        self.velocity_entry.grid(row=1, column=2, padx=(5, 0))
        
        # Ускорение (остается для задания, но отображается нагрузка)
        ttk.Label(right_frame, text="Acceleration (rad/s²):").grid(row=2, column=0, sticky=tk.W)
        self.acceleration_var = tk.DoubleVar(value=1.0)
        self.acceleration_scale = ttk.Scale(right_frame, from_=0.0, to=10.0, 
                                           variable=self.acceleration_var, orient=tk.HORIZONTAL)
        self.acceleration_scale.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(5, 0))
        self.acceleration_entry = ttk.Entry(right_frame, textvariable=self.acceleration_var, width=10)
        self.acceleration_entry.grid(row=2, column=2, padx=(5, 0))
        
        # Кнопки управления
        control_frame = ttk.Frame(right_frame)
        control_frame.grid(row=3, column=0, columnspan=3, pady=10)
        
        self.send_command_btn = ttk.Button(control_frame, text="Send Command", command=self.send_command)
        self.send_command_btn.grid(row=0, column=0, padx=5)
        ttk.Button(control_frame, text="Enable", command=self.enable_motor).grid(row=0, column=1, padx=5)
        ttk.Button(control_frame, text="Disable", command=self.disable_motor).grid(row=0, column=2, padx=5)
        ttk.Button(control_frame, text="Home", command=self.home_motor).grid(row=0, column=3, padx=5)
        
        # Чекбокс для постоянного обновления
        self.always_update_var = tk.BooleanVar(value=False)
        self.always_update_cb = ttk.Checkbutton(control_frame, text="Always Update (10ms)", 
                                               variable=self.always_update_var, 
                                               command=self.on_always_update_change)
        self.always_update_cb.grid(row=1, column=0, columnspan=2, pady=(5, 0), sticky=tk.W)
        
        # Информация о выбранном двигателе
        info_frame = ttk.LabelFrame(main_frame, text="Selected Motor Information", padding="5")
        info_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        info_frame.columnconfigure(1, weight=1)
        
        # Фрейм для кнопок управления информацией
        info_control_frame = ttk.Frame(info_frame)
        info_control_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 5))
        
        ttk.Button(info_control_frame, text="Clear Log", command=self.clear_info).grid(row=0, column=0, padx=(0, 5))
        ttk.Button(info_control_frame, text="Refresh", command=self.refresh_info).grid(row=0, column=1, padx=5)
        
        # Чекбокс для автоматического обновления
        self.auto_update_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(info_control_frame, text="Auto-update", variable=self.auto_update_var).grid(row=0, column=2, padx=(20, 0))
        
        self.info_text = tk.Text(info_frame, height=30, width=80)
        self.info_text.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E))
        
        # Скроллбар для текста
        scrollbar = ttk.Scrollbar(info_frame, orient=tk.VERTICAL, command=self.info_text.yview)
        scrollbar.grid(row=1, column=2, sticky=(tk.N, tk.S))
        self.info_text.configure(yscrollcommand=scrollbar.set)
        
        # Привязка событий
        self.position_var.trace('w', self.on_position_change)
        self.velocity_var.trace('w', self.on_velocity_change)
        self.acceleration_var.trace('w', self.on_acceleration_change)
        
    def ros_spin(self):
        """Запуск ROS2 в отдельном потоке"""
        try:
            rclpy.spin(self.node)
        except KeyboardInterrupt:
            pass
        
    def states_callback(self, msg):
        """Обработка критичных данных движения всех моторов"""
        for motor_state in msg.states:
            motor_id = motor_state.motor_id
            
            # Всегда используем формат motor_X для имен
            motor_name = f"motor_{motor_id}"
            self.motor_names[motor_id] = motor_name
            
            # Сохраняем критичные данные движения
            self.motors_states[motor_id] = motor_state
            
            # Обновляем список двигателей в комбобоксе
            current_motor_ids = [int(x.split('_')[1]) for x in self.motor_combo['values'] if x.startswith('motor_')]
            if motor_id not in current_motor_ids:
                self.root.after(0, self.update_motor_list)
                
        # Обновляем информацию только если включено автоматическое обновление
        if self.auto_update_var.get():
            self.root.after(0, self.update_info)
    
    def telemetry_callback(self, msg):
        """Обработка некритичных телеметрических данных всех моторов"""
        for telemetry in msg.telemetries:
            motor_id = telemetry.motor_id
            
            # Сохраняем некритичные данные
            self.motors_telemetry[motor_id] = telemetry
    

    
    def mapping_callback(self, msg):
        """Обработка привязок мотор-сустав"""
        for binding in msg.bindings:
            self.motor_bindings[binding.motor_id] = {
                'joint_name': binding.joint_name,
                'motor_name': binding.motor_name,
                'motor_type': binding.motor_type,
                'reversed': binding.reversed,
                'zero_offset': binding.zero_offset,
                'min_position': binding.min_position,
                'max_position': binding.max_position,
                'max_velocity': binding.max_velocity,
                'max_acceleration': binding.max_acceleration
            }
        
    def update_motor_list(self):
        """Обновление списка двигателей"""
        motor_ids = sorted(self.motors_states.keys())
        motor_names = []
        
        for motor_id in motor_ids:
            # Всегда используем формат motor_X для отображения в селекторе
            motor_names.append(f"motor_{motor_id}")
        
        self.motor_combo['values'] = motor_names
        
        if not self.motor_var.get() and motor_names:
            self.motor_var.set(motor_names[0])
            
    def on_motor_selected(self, event):
        """Обработка выбора двигателя"""
        selected = self.motor_var.get()
        if selected:
            motor_id = self.get_motor_id_from_name(selected)
            if motor_id and motor_id in self.motors_states:
                motor_state = self.motors_states[motor_id]
                
                # Обновляем ограничения ползунков на основе привязок или конфигурации мотора
                if motor_id in self.motor_bindings:
                    binding = self.motor_bindings[motor_id]
                    
                    # Используем данные из привязок (уже в радианах)
                    # TODO нужно исправить проблемы с инвертирование пределов и сразу их инвертировать, например
                    min_position = binding['min_position']
                    max_position = binding['max_position']
                    if binding['reversed']:
                        min_position, max_position = -max_position, -min_position
                    self.position_scale.configure(from_=min_position, to=max_position)
                    
                    # Устанавливаем текущую позицию (в радианах)
                    current_pos = motor_state.position
                    self.position_var.set(current_pos)
                    
                    # Обновляем ограничения скорости
                    self.velocity_scale.configure(from_=0.0, to=binding['max_velocity'])
                    
                    # Обновляем ограничения ускорения
                    self.acceleration_scale.configure(from_=0.0, to=binding['max_acceleration'])
                    
                    # Обновляем информацию о выбранном моторе
                    self.update_info()
                elif motor_id in self.motor_configs:
                    config = self.motor_configs[motor_id]
                    
                    # Рассчитываем пределы в радианах на основе units
                    min_pos_units = config['min_position_units']
                    max_pos_units = config['max_position_units']
                    zero_offset_units = config['zero_offset_units']
                    motor_units_per_radian = config['conversion']['motor_units_per_radian']
                    
                    # Преобразуем units в радианы относительно zero_offset
                    min_pos_rad = (min_pos_units - zero_offset_units) / motor_units_per_radian
                    max_pos_rad = (max_pos_units - zero_offset_units) / motor_units_per_radian
                    if config['reversed']:
                        min_pos_rad, max_pos_rad = -max_pos_rad, -min_pos_rad
                    self.position_scale.configure(from_=min_pos_rad, to=max_pos_rad)
                    
                    # Устанавливаем текущую позицию (в радианах)
                    current_pos = motor_state.position
                    self.position_var.set(current_pos)
                    
                    # Обновляем ограничения скорости
                    max_vel = config['max_velocity']
                    self.velocity_scale.configure(from_=0.0, to=max_vel)
                    
                    # Обновляем ограничения ускорения
                    max_accel = config['max_acceleration']
                    self.acceleration_scale.configure(from_=0.0, to=max_accel)
                    
                    # Обновляем информацию о выбранном моторе
                    self.update_info()
                else:
                    # Если конфигурация не найдена, используем значения по умолчанию
                    self.position_scale.configure(from_=-3.14, to=3.14)
                    self.velocity_scale.configure(from_=0.0, to=5.0)
                    self.acceleration_scale.configure(from_=0.0, to=10.0)
                    self.position_var.set(motor_state.position)
                    self.update_info()
            
    def send_command(self):
        """Отправка команды управления выбранному двигателю"""
        selected = self.motor_var.get()
        if not selected:
            messagebox.showwarning("Warning", "Please select a motor first!")
            return
            
        motor_id = self.get_motor_id_from_name(selected)
        if not motor_id:
            messagebox.showwarning("Warning", "Invalid motor selection!")
            return
        
        # Получаем позицию из GUI (в радианах)
        target_position = self.position_var.get()
        
        # Используем новый топик для команд управления
        cmd = MotorCommand()
        cmd.motor_id = motor_id
        cmd.target_position = target_position
        cmd.target_velocity = self.velocity_var.get()
        cmd.target_acceleration = self.acceleration_var.get()
        
        cmd_array = MotorCommands()
        cmd_array.header.stamp = self.node.get_clock().now().to_msg()
        cmd_array.commands = [cmd]
        
        self.control_cmd_pub.publish(cmd_array)
        self.node.get_logger().info(f"Sent command to motor {motor_id}: pos={target_position:.3f}, vel={self.velocity_var.get():.3f}, accel={self.acceleration_var.get():.3f}")
        
    def enable_motor(self):
        """Включение выбранного двигателя"""
        selected = self.motor_var.get()
        if selected:
            motor_id = self.get_motor_id_from_name(selected)
            self.node.get_logger().info(f"Enabling motor {motor_id}...")
        self.send_motor_params(True)
        
    def disable_motor(self):
        """Выключение выбранного двигателя"""
        selected = self.motor_var.get()
        if selected:
            motor_id = self.get_motor_id_from_name(selected)
            self.node.get_logger().info(f"Disabling motor {motor_id}...")
        self.send_motor_params(False)
        
    def home_motor(self):
        """Возврат выбранного двигателя в исходное положение"""
        selected = self.motor_var.get()
        if not selected:
            messagebox.showwarning("Warning", "Please select a motor first!")
            return
            
        motor_id = self.get_motor_id_from_name(selected)
        if not motor_id:
            messagebox.showwarning("Warning", "Invalid motor selection!")
            return
        
        # Устанавливаем позицию 0 (в радианах) - это соответствует zero_offset_units
        self.position_var.set(0.0)
        
        self.node.get_logger().info(f"Homing motor {motor_id}...")
        self.send_command()
        
    def enable_all(self):
        """Включение всех двигателей"""
        self.node.get_logger().info("Enabling all motors...")
        self.send_motor_params(True, all_motors=True)
        
    def disable_all(self):
        """Выключение всех двигателей"""
        self.node.get_logger().info("Disabling all motors...")
        self.send_motor_params(False, all_motors=True)
        
    def home_all(self):
        """Возврат всех двигателей в исходное положение"""
        cmd_array = MotorCommands()
        cmd_array.header.stamp = self.node.get_clock().now().to_msg()
        
        for motor_id in self.motors_states.keys():
            cmd = MotorCommand()
            cmd.motor_id = motor_id
            
            # Устанавливаем позицию 0
            cmd.target_position = 0.0
            cmd.target_velocity = 1.0
            cmd.target_acceleration = 1.0
            cmd_array.commands.append(cmd)
            
        self.control_cmd_pub.publish(cmd_array)
        self.node.get_logger().info(f"Sent home command to {len(cmd_array.commands)} motors")
        
    def send_motor_params(self, enabled, all_motors=False):
        """Отправка параметров управления моторов (только включение/выключение)"""
        if all_motors:
            motor_ids = list(self.motors_states.keys())
        else:
            selected = self.motor_var.get()
            if not selected:
                messagebox.showwarning("Warning", "Please select a motor first!")
                return
            motor_id = self.get_motor_id_from_name(selected)
            if not motor_id:
                messagebox.showwarning("Warning", "Invalid motor selection!")
                return
            motor_ids = [motor_id]
            
        # Создаем сообщение с параметрами
        params_msg = MotorParams()
        params_msg.header.stamp = self.node.get_clock().now().to_msg()
        params_msg.header.frame_id = "motor_gui"
        
        for motor_id in motor_ids:
            param = MotorParam()
            param.motor_id = motor_id
            param.enabled = enabled
            
            params_msg.params.append(param)
        
        # Отправляем параметры
        self.params_pub.publish(params_msg)
        self.node.get_logger().info(f"Sent {'enable' if enabled else 'disable'} params to {len(motor_ids)} motors")
        
    def on_position_change(self, *args):
        """Обработка изменения позиции"""
        try:
            value = self.position_var.get()
            self.position_scale.set(value)
        except:
            pass
            
    def on_velocity_change(self, *args):
        """Обработка изменения скорости"""
        try:
            value = self.velocity_var.get()
            self.velocity_scale.set(value)
        except:
            pass
            
    def on_acceleration_change(self, *args):
        """Обработка изменения ускорения"""
        try:
            value = self.acceleration_var.get()
            self.acceleration_scale.set(value)
        except:
            pass
            
    def on_always_update_change(self):
        """Обработка изменения состояния чекбокса Always Update"""
        if self.always_update_var.get():
            self.start_always_update()
        else:
            self.stop_always_update()
            
    def start_always_update(self):
        """Запуск постоянного обновления"""
        self.send_command_btn.config(state='disabled')
        
        # Запускаем таймер для постоянной публикации каждые 10мс
        self.always_update_timer = self.root.after(self.update_interval, self.always_update_callback)
        
        self.node.get_logger().info("Always Update mode enabled - continuously publishing motor commands every 10ms")
        
    def stop_always_update(self):
        """Остановка постоянного обновления"""
        if self.always_update_timer:
            self.root.after_cancel(self.always_update_timer)
            self.always_update_timer = None
            
        self.send_command_btn.config(state='normal')
        
        # Сбрасываем счетчик команд
        self.commands_sent_count = 0
        
        self.node.get_logger().info("Always Update mode disabled")
        
    def always_update_callback(self):
        """Callback для постоянного обновления с фиксированным интервалом 10мс"""
        if self.always_update_var.get():
            # Публикуем текущие значения ползунков
            self.publish_current_values()
            
            # Планируем следующий вызов через 10мс
            self.always_update_timer = self.root.after(self.update_interval, self.always_update_callback)
            
    def publish_current_values(self):
        """Публикация текущих значений ползунков каждые 10мс"""
        selected = self.motor_var.get()
        if not selected:
            return
            
        motor_id = self.get_motor_id_from_name(selected)
        if not motor_id:
            return
        
        # Создаем команду с текущими значениями
        cmd = MotorCommand()
        cmd.motor_id = motor_id
        cmd.target_position = self.position_var.get()
        cmd.target_velocity = self.velocity_var.get()
        cmd.target_acceleration = self.acceleration_var.get()
        
        cmd_array = MotorCommands()
        cmd_array.header.stamp = self.node.get_clock().now().to_msg()
        cmd_array.commands = [cmd]
        
        self.control_cmd_pub.publish(cmd_array)
        
        # Увеличиваем счетчик команд
        self.commands_sent_count += 1
        
    def on_closing(self):
        """Обработчик закрытия окна"""
        # Останавливаем таймер постоянного обновления (10мс)
        if self.always_update_timer:
            self.root.after_cancel(self.always_update_timer)
            self.always_update_timer = None
        
        # Закрываем окно
        self.root.destroy()
            
    def update_info(self):
        """Обновление информации о выбранном двигателе"""
        # Проверяем, выбран ли мотор
        selected = self.motor_var.get()
        if not selected:
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, "Please select a motor to view its information.")
            return
        
        # Получаем ID выбранного мотора
        motor_id = self.get_motor_id_from_name(selected)
        if not motor_id:
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, f"Invalid motor selection: {selected}")
            return
        
        # Проверяем, есть ли данные о выбранном моторе
        if motor_id not in self.motors_states:
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, f"No data available for {selected}")
            return
        
        # Получаем данные мотора
        motor_state = self.motors_states[motor_id]
        telemetry = self.motors_telemetry.get(motor_id, None)
        
        # Очищаем текстовое поле
        self.info_text.delete(1.0, tk.END)
        
        # Формируем подробную информацию о выбранном моторе
        joint_name = ""
        if motor_id in self.motor_bindings:
            joint_name = f" ({self.motor_bindings[motor_id]['joint_name']})"
        elif motor_id in self.motor_configs:
            joint_name = f" ({self.motor_configs[motor_id]['joint_name']})"
        
        info = f"=== {selected.upper()}{joint_name} DETAILED INFORMATION ===\n\n"
        
        # Информация о конфигурации мотора
        if motor_id in self.motor_bindings:
            binding = self.motor_bindings[motor_id]
            info += "MOTOR INFO:\n"
            info += f"  Name:         {binding['motor_name']}\n"
            info += f"  Joint:        {binding['joint_name']}\n"
            info += f"  Type:         {binding['motor_type']}\n"
            info += f"  Reversed:    {binding['reversed']}\n"
            info += f"  Zero Offset:  {binding['zero_offset']:.3f} rad\n"
            info += f"  Min Position: {binding['min_position']:.3f} rad\n"
            info += f"  Max Position: {binding['max_position']:.3f} rad\n\n"
        elif motor_id in self.motor_configs:
            config = self.motor_configs[motor_id]
            info += "MOTOR INFO:\n"
            info += f"  Name:         {config['name']}\n"
            info += f"  Joint:        {config['joint_name']}\n"
            info += f"  Type:         {config['type']}\n"
            info += f"  Reversed:    {config['reversed']}\n"
            
            # Добавляем информацию о пределах
            min_pos_units = config['min_position_units']
            max_pos_units = config['max_position_units']
            zero_offset_units = config['zero_offset_units']
            motor_units_per_radian = config['conversion']['motor_units_per_radian']
            
            # Рассчитываем пределы в радианах
            min_pos_rad = (min_pos_units - zero_offset_units) / motor_units_per_radian
            max_pos_rad = (max_pos_units - zero_offset_units) / motor_units_per_radian
            
            info += f"  Zero Offset:  {zero_offset_units} units ({config['zero_offset']:.3f} rad)\n"
            info += f"  Min Position: {min_pos_units} units ({min_pos_rad:.3f} rad)\n"
            info += f"  Max Position: {max_pos_units} units ({max_pos_rad:.3f} rad)\n\n"
        
        # Основные параметры
        info += "CURRENT STATE:\n"
        info += f"  Position:     {motor_state.position:.3f} rad\n"
        info += f"  Velocity:     {motor_state.velocity:.3f} rad/s\n"
        info += f"  Load:         {motor_state.load:.3f} %\n"
        info += f"  Enabled:      {motor_state.enabled}\n"
        if motor_state.error:
            info += f"  Error:        ERROR DETECTED\n"
            # Если есть телеметрия, показываем код ошибки
            if telemetry and telemetry.error_code != 0:
                error_desc = self.error_codes.get(telemetry.error_code, f"Unknown Error ({telemetry.error_code})")
                info += f"  Error Code:   {telemetry.error_code} - {error_desc}\n"
        info += "\n"
        
        # Электрические параметры
        if telemetry:
            info += "ELECTRICAL:\n"
            info += f"  Voltage:      {telemetry.voltage:.3f} V\n"
            info += f"  Current:      {telemetry.current:.3f} A\n"
            info += f"  Temperature:  {telemetry.temperature:.1f} °C\n"
            if telemetry.error_code != 0:
                error_desc = self.error_codes.get(telemetry.error_code, f"Unknown Error ({telemetry.error_code})")
                info += f"  Error Code:   {telemetry.error_code} ❌ {error_desc}\n"
            else:
                info += f"  Error Code:   {self.error_codes[0]}\n"
            info += "\n"
        
        # Временная метка
        import datetime
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        info += f"Last Update: {current_time}\n"
        
        # Вставляем информацию
        self.info_text.insert(tk.END, info)
    
    def clear_info(self):
        """Очистка информационного поля"""
        self.info_text.delete(1.0, tk.END)
    
    def refresh_info(self):
        """Принудительное обновление информации"""
        self.update_info()
            
    def run(self):
        """Запуск GUI"""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            # Останавливаем таймер постоянного обновления (10мс)
            if self.always_update_timer:
                self.root.after_cancel(self.always_update_timer)
                self.always_update_timer = None
            
            self.node.destroy_node()
            rclpy.shutdown()

    def get_motor_id_from_name(self, motor_name):
        """Получает motor_id из имени мотора"""
        # Извлекаем ID из формата motor_X
        if motor_name.startswith('motor_'):
            try:
                return int(motor_name.split('_')[1])
            except (IndexError, ValueError):
                pass
        
        return None


def main():
    app = MotorTestGUI()
    app.run()


if __name__ == '__main__':
    main() 