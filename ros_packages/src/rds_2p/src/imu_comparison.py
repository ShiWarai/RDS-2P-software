#!/usr/bin/env python3
"""
Скрипт для сравнения /imu и /fake_imu в ROS

Данные от виртуального twin:
- angular_velocity: гироскоп
- orientation: кватернион из rotation matrix
- linear_acceleration: gravity vector (вычисленный из orientation)
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Imu
import time
import argparse
import math

class ImuComparison(Node):
    def __init__(self, state_delay=2.0):
        super().__init__('imu_comparison')
        
        self.state_delay = state_delay  # Задержка для стабилизации состояния
        
        # Хранилище данных
        self.imu_data = None       # Данные с /imu
        self.fake_imu_data = None  # Данные с /fake_imu
        
        # QoS профиль для сенсорных данных (BEST_EFFORT)
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        
        # Создаем подписчики
        self.imu_sub = self.create_subscription(
            Imu,
            '/imu',
            self.imu_callback,
            sensor_qos
        )
        
        self.fake_imu_sub = self.create_subscription(
            Imu,
            '/fake_imu', 
            self.fake_imu_callback,
            sensor_qos
        )
        
        # Таймер для периодического сравнения
        self.timer = self.create_timer(0.5, self.compare_imu)  # 2 Hz
        
        self.get_logger().info(f'IMU Comparison запущен (задержка: {state_delay}с)')
        
    def imu_callback(self, msg):
        """Обработка сообщений /imu"""
        self.imu_data = msg
    
    def fake_imu_callback(self, msg):
        """Обработка сообщений /fake_imu"""
        self.fake_imu_data = msg
    
    def compare_imu(self):
        """Сравнение данных IMU"""
        if self.imu_data is None or self.fake_imu_data is None:
            return
        
        # Ждем стабилизации состояния
        time.sleep(self.state_delay)
        
        # Выводим результаты
        self.print_comparison_results()
    
    def quaternion_to_euler(self, x, y, z, w):
        """Конвертация кватерниона в углы Эйлера (roll, pitch, yaw) в радианах"""
        # Roll (x-axis rotation)
        sinr_cosp = 2 * (w * x + y * z)
        cosr_cosp = 1 - 2 * (x * x + y * y)
        roll = math.atan2(sinr_cosp, cosr_cosp)
        
        # Pitch (y-axis rotation)
        sinp = 2 * (w * y - z * x)
        if abs(sinp) >= 1:
            pitch = math.copysign(math.pi / 2, sinp)
        else:
            pitch = math.asin(sinp)
        
        # Yaw (z-axis rotation)
        siny_cosp = 2 * (w * z + x * y)
        cosy_cosp = 1 - 2 * (y * y + z * z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        
        return roll, pitch, yaw
    
    def print_comparison_results(self):
        """Вывод результатов сравнения"""
        if self.imu_data is None or self.fake_imu_data is None:
            return
        
        self.get_logger().info("=" * 80)
        self.get_logger().info("СРАВНЕНИЕ IMU")
        self.get_logger().info("=" * 80)
        
        # Сравнение ориентации (кватернион)
        self.get_logger().info("\n--- ОРИЕНТАЦИЯ (Quaternion) ---")
        imu_q = self.imu_data.orientation
        fake_q = self.fake_imu_data.orientation
        
        self.get_logger().info(
            f"  x | Real: {imu_q.x:8.4f} | Fake: {fake_q.x:8.4f} | "
            f"Разница: {abs(imu_q.x - fake_q.x):8.4f}"
        )
        self.get_logger().info(
            f"  y | Real: {imu_q.y:8.4f} | Fake: {fake_q.y:8.4f} | "
            f"Разница: {abs(imu_q.y - fake_q.y):8.4f}"
        )
        self.get_logger().info(
            f"  z | Real: {imu_q.z:8.4f} | Fake: {fake_q.z:8.4f} | "
            f"Разница: {abs(imu_q.z - fake_q.z):8.4f}"
        )
        self.get_logger().info(
            f"  w | Real: {imu_q.w:8.4f} | Fake: {fake_q.w:8.4f} | "
            f"Разница: {abs(imu_q.w - fake_q.w):8.4f}"
        )
        
        # Конвертация в углы Эйлера для наглядности
        imu_roll, imu_pitch, imu_yaw = self.quaternion_to_euler(
            imu_q.x, imu_q.y, imu_q.z, imu_q.w
        )
        fake_roll, fake_pitch, fake_yaw = self.quaternion_to_euler(
            fake_q.x, fake_q.y, fake_q.z, fake_q.w
        )
        
        self.get_logger().info("\n--- ОРИЕНТАЦИЯ (Euler Angles) ---")
        self.get_logger().info(
            f"  Roll  | Real: {imu_roll:8.4f} ({math.degrees(imu_roll):7.2f}°) | "
            f"Fake: {fake_roll:8.4f} ({math.degrees(fake_roll):7.2f}°) | "
            f"Разница: {abs(imu_roll - fake_roll):8.4f} ({math.degrees(abs(imu_roll - fake_roll)):6.2f}°)"
        )
        self.get_logger().info(
            f"  Pitch | Real: {imu_pitch:8.4f} ({math.degrees(imu_pitch):7.2f}°) | "
            f"Fake: {fake_pitch:8.4f} ({math.degrees(fake_pitch):7.2f}°) | "
            f"Разница: {abs(imu_pitch - fake_pitch):8.4f} ({math.degrees(abs(imu_pitch - fake_pitch)):6.2f}°)"
        )
        self.get_logger().info(
            f"  Yaw   | Real: {imu_yaw:8.4f} ({math.degrees(imu_yaw):7.2f}°) | "
            f"Fake: {fake_yaw:8.4f} ({math.degrees(fake_yaw):7.2f}°) | "
            f"Разница: {abs(imu_yaw - fake_yaw):8.4f} ({math.degrees(abs(imu_yaw - fake_yaw)):6.2f}°)"
        )
        
        # Сравнение угловой скорости
        self.get_logger().info("\n--- УГЛОВАЯ СКОРОСТЬ (rad/s) ---")
        imu_av = self.imu_data.angular_velocity
        fake_av = self.fake_imu_data.angular_velocity
        
        self.get_logger().info(
            f"  x | Real: {imu_av.x:8.4f} | Fake: {fake_av.x:8.4f} | "
            f"Разница: {abs(imu_av.x - fake_av.x):8.4f}"
        )
        self.get_logger().info(
            f"  y | Real: {imu_av.y:8.4f} | Fake: {fake_av.y:8.4f} | "
            f"Разница: {abs(imu_av.y - fake_av.y):8.4f}"
        )
        self.get_logger().info(
            f"  z | Real: {imu_av.z:8.4f} | Fake: {fake_av.z:8.4f} | "
            f"Разница: {abs(imu_av.z - fake_av.z):8.4f}"
        )
        
        # Сравнение линейного ускорения (gravity)
        self.get_logger().info("\n--- ЛИНЕЙНОЕ УСКОРЕНИЕ / GRAVITY (m/s²) ---")
        imu_la = self.imu_data.linear_acceleration
        fake_la = self.fake_imu_data.linear_acceleration
        
        self.get_logger().info(
            f"  x | Real: {imu_la.x:8.4f} | Fake: {fake_la.x:8.4f} | "
            f"Разница: {abs(imu_la.x - fake_la.x):8.4f}"
        )
        self.get_logger().info(
            f"  y | Real: {imu_la.y:8.4f} | Fake: {fake_la.y:8.4f} | "
            f"Разница: {abs(imu_la.y - fake_la.y):8.4f}"
        )
        self.get_logger().info(
            f"  z | Real: {imu_la.z:8.4f} | Fake: {fake_la.z:8.4f} | "
            f"Разница: {abs(imu_la.z - fake_la.z):8.4f}"
        )
        
        self.get_logger().info("\n" + "=" * 80 + "\n")
    

def main():
    parser = argparse.ArgumentParser(description='Сравнение /imu и /fake_imu')
    parser.add_argument('--state-delay', type=float, default=2.0,
                       help='Задержка для стабилизации состояния в секундах (по умолчанию: 2.0)')
    
    args = parser.parse_args()
    
    rclpy.init()
    
    try:
        node = ImuComparison(state_delay=args.state_delay)
        
        print("Скрипт запущен. Нажмите Ctrl+C для остановки.")
        print(f"Задержка стабилизации: {args.state_delay}с")
        print("Ожидание данных с топиков /imu и /fake_imu...")
        
        rclpy.spin(node)
        
    except KeyboardInterrupt:
        print("\nОстановка...")
        
    finally:
        rclpy.shutdown()

if __name__ == '__main__':
    main()

