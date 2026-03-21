#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
import yaml
import os
import threading
import sys
import signal


class KeyframeConsole(Node):
    def __init__(self):
        super().__init__('keyframe_console')
        
        # Флаг для корректного завершения
        self._shutdown_requested = False
        
        # Параметры - используем относительный путь от ros_packages директории
        # __file__ указывает на install/rds-2p/lib/rds-2p/keyframe_console.py
        # Нужно подняться до ros_packages и затем до родительской директории
        install_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        ros_packages_dir = os.path.dirname(install_dir)
        default_keyframes_path = os.path.join(ros_packages_dir, '..', 'mjcf_src', 'configs', 'keyframes.yml')
        self.declare_parameter('keyframes_file', default_keyframes_path)
        
        keyframes_file = self.get_parameter('keyframes_file').get_parameter_value().string_value
        
        # Загружаем keyframes
        self.keyframes = self.load_keyframes(keyframes_file)
        self.current_keyframe = 'home'
        
        # Определяем имена джойнтов
        self.joint_names = [
            'leg_block_bl_joint', 'hip_bl_joint', 'shin_bl_joint',
            'leg_block_br_joint', 'hip_br_joint', 'shin_br_joint', 
            'leg_block_fl_joint', 'hip_fl_joint', 'shin_fl_joint',
            'leg_block_fr_joint', 'hip_fr_joint', 'shin_fr_joint'
        ]
        
        # Оптимальный QoS для минимальной задержки с гарантированной доставкой
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
        
        command_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1  # Только последнее сообщение (без очереди)
        )
        
        # Создаем publisher с надежным QoS
        self.joint_cmd_pub = self.create_publisher(JointState, '/joint_commands', command_qos)
        
        # Создаем таймер для публикации
        timer_period = 0.02  # 50 Гц
        self.timer = self.create_timer(timer_period, self.publish_current_keyframe)
        
        self.get_logger().info('Keyframe Console initialized')
        self.print_current_status()

    def load_keyframes(self, file_path: str):
        """Загружает keyframes из YAML файла"""
        try:
            with open(file_path, 'r') as file:
                data = yaml.safe_load(file)
                return data.get('keyframes', {})
        except Exception as e:
            self.get_logger().error(f'Failed to load keyframes from {file_path}: {e}')
            return {}

    def get_current_positions(self):
        """Получает позиции для текущего keyframe"""
        if self.current_keyframe not in self.keyframes:
            self.get_logger().warn(f'Keyframe "{self.current_keyframe}" not found, using home')
            self.current_keyframe = 'home'
        
        keyframe_data = self.keyframes[self.current_keyframe]
        qpos = keyframe_data.get('qpos', [])
        
        # Извлекаем только позиции джойнтов (пропускаем первые 7 элементов - позиция и ориентация корпуса)
        if len(qpos) >= 19:  # 7 (корпус) + 12 (джойнты)
            joint_positions = qpos[7:19]  # Берем элементы с 7 по 18
            return joint_positions
        else:
            self.get_logger().error(f'Invalid qpos length in keyframe "{self.current_keyframe}": {len(qpos)}')
            return [0.0] * len(self.joint_names)

    def publish_current_keyframe(self):
        """Публикует команды для текущего keyframe"""
        joint_cmd = JointState()
        joint_cmd.header.stamp = self.get_clock().now().to_msg()
        joint_cmd.header.frame_id = 'base_link'
        
        # Заполняем имена джоинтов
        joint_cmd.name = self.joint_names
        
        # Получаем позиции для текущего keyframe
        joint_cmd.position = self.get_current_positions()
        
        # Заполняем скорости и усилия
        joint_cmd.velocity = [0.0] * len(self.joint_names)
        joint_cmd.effort = [0.0] * len(self.joint_names)
        
        # Публикуем
        self.joint_cmd_pub.publish(joint_cmd)

    def switch_keyframe(self, keyframe_name: str):
        """Переключает на указанный keyframe"""
        if keyframe_name in self.keyframes:
            self.current_keyframe = keyframe_name
            self.get_logger().info(f'Switched to keyframe: {self.current_keyframe}')
            self.print_current_status()
        else:
            available = list(self.keyframes.keys())
            self.get_logger().error(f'Keyframe "{keyframe_name}" not found. Available: {available}')


    def print_current_status(self):
        """Выводит текущий статус"""
        print(f"\nТекущий keyframe: {self.current_keyframe}")
        if self.current_keyframe in self.keyframes:
            positions = self.get_current_positions()
            print(f"Позиции джойнтов: {[f'{pos:.3f}' for pos in positions[:3]]}...")
        
        # Показываем список доступных поз
        self.print_available_keyframes()

    def print_available_keyframes(self):
        """Выводит список доступных keyframes"""
        print("\nДоступные keyframes:")
        for i, keyframe in enumerate(self.keyframes.keys(), 1):
            marker = " <-- ТЕКУЩИЙ" if keyframe == self.current_keyframe else ""
            print(f"  {i}. {keyframe}{marker}")
        print(f"\nИспользуйте номер (1-{len(self.keyframes)}) или название для переключения")

    def handle_input(self):
        """Обрабатывает ввод пользователя"""
        while rclpy.ok() and not self._shutdown_requested:
            try:
                user_input = input("\nВведите команду: ").strip().lower()
                
                if user_input in ['quit', 'exit', 'q']:
                    print("Выход из программы...")
                    self._shutdown_requested = True
                    break
                elif user_input == '':
                    continue
                else:
                    # Пробуем найти keyframe по имени или номеру
                    if user_input.isdigit():
                        # Ввод по номеру
                        try:
                            index = int(user_input) - 1
                            keyframes_list = list(self.keyframes.keys())
                            if 0 <= index < len(keyframes_list):
                                self.switch_keyframe(keyframes_list[index])
                            else:
                                print(f"Номер {user_input} вне диапазона (1-{len(keyframes_list)})")
                        except ValueError:
                            print("Неверный номер")
                    else:
                        # Ввод по имени
                        self.switch_keyframe(user_input)
                        
            except EOFError:
                print("\nВыход из программы...")
                self._shutdown_requested = True
                break
            except KeyboardInterrupt:
                print("\nВыход из программы...")
                self._shutdown_requested = True
                break


def main(args=None):
    rclpy.init(args=args)
    
    keyframe_console = KeyframeConsole()
    
    # Запускаем обработку ввода в отдельном потоке
    input_thread = threading.Thread(target=keyframe_console.handle_input, daemon=True)
    input_thread.start()
    
    try:
        # Основной цикл ROS2
        while rclpy.ok() and not keyframe_console._shutdown_requested:
            rclpy.spin_once(keyframe_console, timeout_sec=0.1)
    except KeyboardInterrupt:
        keyframe_console.get_logger().info('Получен сигнал завершения...')
        keyframe_console._shutdown_requested = True
    finally:
        # Корректное завершение
        try:
            keyframe_console.destroy_node()
        except Exception as e:
            print(f"Ошибка при уничтожении узла: {e}")
        
        # Проверяем, что контекст еще не был завершен
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception as e:
            print(f"Ошибка при завершении ROS2: {e}")


if __name__ == '__main__':
    main()
