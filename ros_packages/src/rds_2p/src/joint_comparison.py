#!/usr/bin/env python3
"""
Скрипт для сравнения /joint_commands и /joint_states в ROS
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
import time
import argparse
import math

class JointComparison(Node):
    def __init__(self, state_delay=2.0):
        super().__init__('joint_comparison')
        
        self.state_delay = state_delay  # Задержка для стабилизации состояния
        
        # Хранилище данных
        self.commands_data = {}  # {joint_name: position}
        self.states_data = {}    # {joint_name: position}
        
        # Создаем подписчики
        self.commands_sub = self.create_subscription(
            JointState,
            '/joint_commands',
            self.commands_callback,
            10
        )
        
        self.states_sub = self.create_subscription(
            JointState,
            '/joint_states', 
            self.states_callback,
            10
        )
        
        # Таймер для периодического сравнения
        self.timer = self.create_timer(0.5, self.compare_joints)  # 2 Hz
        
        self.get_logger().info(f'Joint Comparison запущен (задержка: {state_delay}с)')
        
    def commands_callback(self, msg):
        """Обработка сообщений joint_commands"""
        for i, joint_name in enumerate(msg.name):
            if i < len(msg.position):
                self.commands_data[joint_name] = msg.position[i]
    
    def states_callback(self, msg):
        """Обработка сообщений joint_states"""
        for i, joint_name in enumerate(msg.name):
            if i < len(msg.position):
                self.states_data[joint_name] = msg.position[i]
    
    def compare_joints(self):
        """Сравнение команд и состояний суставов"""
        if not self.commands_data or not self.states_data:
            return
        
        # Находим общие суставы
        common_joints = set(self.commands_data.keys()) & set(self.states_data.keys())
        
        if not common_joints:
            return
        
        # Ждем стабилизации состояния
        time.sleep(self.state_delay)
        
        # Выводим результаты
        self.print_comparison_results(common_joints)
    
    def print_comparison_results(self, joint_names):
        """Вывод результатов сравнения"""
        if not joint_names:
            return
        
        self.get_logger().info("=" * 60)
        self.get_logger().info("СРАВНЕНИЕ СУСТАВОВ")
        self.get_logger().info("=" * 60)
        
        for joint_name in sorted(joint_names):
            cmd_pos = self.commands_data[joint_name]
            state_pos = self.states_data[joint_name]
            diff = abs(cmd_pos - state_pos)
            diff_deg = math.degrees(diff)
            
            self.get_logger().info(
                f"{joint_name:20} | "
                f"Целевая: {cmd_pos:8.4f} | "
                f"Текущее: {state_pos:8.4f} | "
                f"Разница: {diff:8.4f} ({diff_deg:6.2f}°)"
            )
        
        self.get_logger().info("")
    

def main():
    parser = argparse.ArgumentParser(description='Сравнение joint_commands и joint_states')
    parser.add_argument('--state-delay', type=float, default=2.0,
                       help='Задержка для стабилизации состояния в секундах (по умолчанию: 2.0)')
    
    args = parser.parse_args()
    
    rclpy.init()
    
    try:
        node = JointComparison(state_delay=args.state_delay)
        
        print("Скрипт запущен. Нажмите Ctrl+C для остановки.")
        print(f"Задержка стабилизации: {args.state_delay}с")
        print("Ожидание данных с топиков /joint_commands и /joint_states...")
        
        rclpy.spin(node)
        
    except KeyboardInterrupt:
        print("\nОстановка...")
        
    finally:
        rclpy.shutdown()

if __name__ == '__main__':
    main()
