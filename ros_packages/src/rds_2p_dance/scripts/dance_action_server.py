#!/usr/bin/env python3
"""ROS2 Action сервер для проигрывания танцев робота RDS-2P.

Принимает номер танца N и проигрывает файл animationN.csv из папки animations пакета.
"""

import csv
import os
import time
import json
import re
from pathlib import Path
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from ament_index_python.packages import get_package_share_directory

from rds_2p_dance.action import PlayDance

# Имена суставов в порядке их появления в CSV
JOINT_NAMES = [
    'leg_block_fl_joint', 'hip_fl_joint', 'shin_fl_joint',
    'leg_block_fr_joint', 'hip_fr_joint', 'shin_fr_joint',
    'leg_block_bl_joint', 'hip_bl_joint', 'shin_bl_joint',
    'leg_block_br_joint', 'hip_br_joint', 'shin_br_joint'
]


class DanceActionServer(Node):
    """ROS2 Action сервер для проигрывания танцев."""
    
    def __init__(self):
        super().__init__('dance_action_server')
        
        # Получаем путь к пакету
        try:
            package_share_dir = get_package_share_directory('rds_2p_dance')
            self.animations_dir = Path(package_share_dir) / 'animations'
        except Exception as e:
            self.get_logger().error(f'Не удалось получить путь к пакету: {e}')
            raise
        
        # Параметры узла (значения по умолчанию)
        self.declare_parameter('interpolate', True)
        self.declare_parameter('base_rate', 50.0)
        self.declare_parameter('speed_multiplier', 0.7)
        
        # Параметры для публикации списка команд
        self.declare_parameter('commands_topic', '/commands')
        self.declare_parameter('commands_publish_rate', 0.1)  # 1 раз в 10 секунд
        self.declare_parameter('scan_animations_on_start', True)
        
        self.interpolate = self.get_parameter('interpolate').get_parameter_value().bool_value
        self.base_rate = self.get_parameter('base_rate').get_parameter_value().double_value
        self.speed_multiplier = self.get_parameter('speed_multiplier').get_parameter_value().double_value
        
        commands_topic = self.get_parameter('commands_topic').get_parameter_value().string_value
        commands_publish_rate = self.get_parameter('commands_publish_rate').get_parameter_value().double_value
        
        # Публикатор списка команд
        self._commands_publisher = self.create_publisher(String, commands_topic, 10)
        self._commands_publish_rate = commands_publish_rate
        self._commands_topic = commands_topic
        
        # Таймер для периодической публикации (если rate > 0)
        if commands_publish_rate > 0:
            timer_period = 1.0 / commands_publish_rate if commands_publish_rate > 0 else 10.0
            self._commands_timer = self.create_timer(timer_period, self._publish_dance_list)
        
        # QoS для минимальной задержки (как в joint_to_motor_bridge)
        command_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        # Создаем публикатор в /joint_commands
        self.joint_commands_pub = self.create_publisher(
            JointState,
            '/joint_commands',
            command_qos
        )
        
        # Создаем Action сервер
        self._action_server = ActionServer(
            self,
            PlayDance,
            '/dance/play',
            self.execute_callback
        )
        
        self.get_logger().info(
            f'Dance Action Server запущен. Папка анимаций: {self.animations_dir}'
        )
        
        # Публикуем начальный список танцев
        if self.get_parameter('scan_animations_on_start').get_parameter_value().bool_value:
            self._publish_dance_list()
    
    def load_animation_csv(self, filename: str):
        """Загрузить анимацию из CSV файла."""
        filepath = self.animations_dir / filename
        
        if not filepath.exists():
            self.get_logger().error(f'Файл не найден: {filepath}')
            return None, None
        
        try:
            poses = []
            joint_names = []
            
            with open(filepath, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)  # Пропускаем заголовок
                
                # Извлекаем имена суставов из заголовка (пропускаем pose_id и time_to_next)
                if len(header) < 14:  # pose_id + time_to_next + 12 joints
                    self.get_logger().error(f'Неверный формат заголовка CSV: ожидается минимум 14 колонок')
                    return None, None
                
                joint_names = header[2:14]  # Пропускаем pose_id и time_to_next
                
                # Загружаем данные поз
                for row_num, row in enumerate(reader, start=2):
                    # Пропускаем пустые строки без предупреждения
                    if not row or len(row) == 0:
                        continue
                    
                    # Пропускаем строки, которые состоят только из пробелов
                    if all(not cell or cell.strip() == '' for cell in row):
                        continue
                    
                    if len(row) < 14:
                        self.get_logger().warn(f'Пропущена строка {row_num}: недостаточно данных (ожидается 14 колонок, получено {len(row)})')
                        continue
                    
                    try:
                        pose_id = int(row[0])
                        time_to_next = float(row[1])
                        angles = np.array([float(row[i]) for i in range(2, 14)], dtype=np.float32)
                        
                        poses.append((angles, time_to_next))
                    except (ValueError, IndexError) as e:
                        self.get_logger().warn(f'Ошибка парсинга строки {row_num}: {e}')
                        continue
            
            if len(poses) == 0:
                self.get_logger().error('CSV файл не содержит валидных поз')
                return None, None
            
            self.get_logger().info(f'Загружено {len(poses)} поз из {filepath}')
            return poses, joint_names
            
        except Exception as e:
            self.get_logger().error(f'Ошибка при загрузке CSV: {e}')
            return None, None
    
    def calculate_interpolated_pose(self, current_angles: np.ndarray, next_angles: np.ndarray, 
                                   alpha: float) -> np.ndarray:
        """Вычислить интерполированную позу между текущей и следующей."""
        alpha = np.clip(alpha, 0.0, 1.0)
        interpolated = (1.0 - alpha) * current_angles + alpha * next_angles
        return interpolated
    
    def execute_callback(self, goal_handle):
        """Callback для выполнения Action goal."""
        dance_number = goal_handle.request.dance_number
        
        # Получаем параметры из goal или используем значения по умолчанию из параметров узла
        # Если speed_multiplier в goal > 0, используем его, иначе используем параметр узла
        speed_multiplier = goal_handle.request.speed_multiplier
        if speed_multiplier <= 0.0:
            speed_multiplier = self.speed_multiplier
        
        # Используем interpolate из goal, если он True, иначе используем параметр узла
        # Это позволяет не задавать интерполяцию явно (false = использовать параметр узла)
        interpolate = goal_handle.request.interpolate if goal_handle.request.interpolate else self.interpolate
        
        self.get_logger().info(
            f'Получен запрос на проигрывание танца #{dance_number} '
            f'(интерполяция: {"вкл" if interpolate else "выкл"}, '
            f'скорость: {speed_multiplier:.2f}x)'
        )
        
        # Формируем имя файла
        csv_filename = f'animation{dance_number}.csv'
        
        # Загружаем анимацию
        poses, joint_names = self.load_animation_csv(csv_filename)
        
        if poses is None or joint_names is None:
            result = PlayDance.Result()
            result.success = False
            result.message = f'Не удалось загрузить файл {csv_filename}'
            goal_handle.abort()
            return result
        
        # Создаем feedback сообщение
        feedback_msg = PlayDance.Feedback()
        feedback_msg.total_poses = len(poses)
        
        self.get_logger().info(f'Начато воспроизведение танца #{dance_number}: {len(poses)} поз')
        
        # Вычисляем общее время анимации
        total_time = sum(time_to_next for _, time_to_next in poses) / speed_multiplier
        
        start_time = time.perf_counter()
        
        # Проигрывание анимации
        for pose_index in range(len(poses)):
            # Проверка на отмену
            if goal_handle.is_cancel_requested:
                self.get_logger().info('Воспроизведение отменено')
                goal_handle.canceled()
                result = PlayDance.Result()
                result.success = False
                result.message = 'Воспроизведение отменено пользователем'
                return result
            
            current_angles, time_to_next = poses[pose_index]
            
            # Применяем множитель скорости к времени между позами
            time_to_next = time_to_next / speed_multiplier
            
            # Определяем, есть ли следующая поза для интерполяции
            has_next = pose_index < len(poses) - 1
            
            if has_next:
                next_angles, _ = poses[pose_index + 1]
            else:
                next_angles = None
            
            # Вычисляем количество публикаций для текущей позы
            num_publications = max(1, int(time_to_next * self.base_rate))
            publish_period = time_to_next / num_publications
            
            # Время начала текущей позы
            pose_start_time = time.perf_counter()
            
            # Публикуем позу с нужной частотой
            for pub_index in range(num_publications):
                # Проверка на отмену
                if goal_handle.is_cancel_requested:
                    self.get_logger().info('Воспроизведение отменено')
                    goal_handle.canceled()
                    result = PlayDance.Result()
                    result.success = False
                    result.message = 'Воспроизведение отменено пользователем'
                    return result
                
                # Вычисляем прогресс для интерполяции (0.0 - начало, 1.0 - конец)
                if interpolate and has_next and next_angles is not None:
                    alpha = pub_index / (num_publications - 1) if num_publications > 1 else 0.0
                    angles_to_publish = self.calculate_interpolated_pose(
                        current_angles, next_angles, alpha
                    )
                else:
                    angles_to_publish = current_angles
                
                # Публикуем команды
                self._publish_joint_command(angles_to_publish, joint_names)
                rclpy.spin_once(self, timeout_sec=0.0)  # Обработка ROS2 событий без блокировки
                
                # Вычисляем время следующей публикации
                next_pub_time = pose_start_time + (pub_index + 1) * publish_period
                current_time = time.perf_counter()
                
                # Ждем до времени следующей публикации
                if pub_index < num_publications - 1:
                    sleep_time = next_pub_time - current_time
                    if sleep_time > 0:
                        time.sleep(sleep_time)
            
            # Обновляем feedback
            feedback_msg.current_pose = pose_index + 1
            feedback_msg.progress = float(pose_index + 1) / len(poses)
            goal_handle.publish_feedback(feedback_msg)
            
            # Ждем до окончания времени текущей позы перед переходом к следующей
            if pose_index < len(poses) - 1:
                pose_end_time = pose_start_time + time_to_next
                current_time = time.perf_counter()
                remaining_time = pose_end_time - current_time
                if remaining_time > 0:
                    time.sleep(remaining_time)
        
        elapsed_time = time.perf_counter() - start_time
        self.get_logger().info(
            f'Воспроизведение завершено: {len(poses)} поз, '
            f'общее время: {total_time:.2f} сек, '
            f'реальное время: {elapsed_time:.2f} сек'
        )
        
        # Возвращаем результат
        goal_handle.succeed()
        result = PlayDance.Result()
        result.success = True
        result.message = f'Танец #{dance_number} успешно проигран ({len(poses)} поз, {elapsed_time:.2f} сек)'
        return result
    
    def _publish_joint_command(self, angles: np.ndarray, joint_names: list):
        """Публиковать команды суставов в /joint_commands."""
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "base_link"
        msg.name = joint_names
        msg.position = angles.tolist()
        msg.velocity = []  # Пустой список, как в inference_node
        msg.effort = []    # Пустой список, как в inference_node
        
        self.joint_commands_pub.publish(msg)
    
    def _scan_available_dances(self):
        """Сканирует папку animations/ и возвращает список доступных танцев."""
        available_dances = []
        
        if not self.animations_dir.exists():
            self.get_logger().warn(f'Папка анимаций не найдена: {self.animations_dir}')
            return available_dances
        
        # Ищем файлы animationN.csv
        pattern = re.compile(r'^animation(\d+)\.csv$')
        for file_path in self.animations_dir.iterdir():
            if file_path.is_file():
                match = pattern.match(file_path.name)
                if match:
                    dance_number = int(match.group(1))
                    available_dances.append(dance_number)
        
        available_dances.sort()
        return available_dances
    
    def _publish_dance_list(self):
        """Публикует список доступных танцев в JSON формате."""
        try:
            # Сканируем доступные танцы
            available_dances = self._scan_available_dances()
            
            if not available_dances:
                self.get_logger().warn('Не найдено доступных танцев')
                return
            
            # Формируем информацию о команде dance
            command_info = {
                'name': 'dance',
                'display_name': 'Танец',
                'action_name': '/dance/play',
                'action_type': 'rds_2p_dance/action/PlayDance',
                'parser': 'extract_number',
                'class': 'motors',
                'keywords': ['dance', 'play', 'танцуй', 'танец'],
                'parameters': {
                    'type': 'number',
                    'name': 'dance_number',
                    'min': min(available_dances),
                    'max': max(available_dances),
                    'available_values': available_dances,
                    'descriptions': {str(d): f'Танец {d}' for d in available_dances}
                }
            }
            
            # Формируем JSON сообщение
            message = {
                'server_name': 'dance_action_server',
                'server_namespace': '/',
                'commands': [command_info]
            }
            
            # Публикуем
            msg = String()
            msg.data = json.dumps(message, ensure_ascii=False)
            self._commands_publisher.publish(msg)
            
            self.get_logger().debug(
                f'Опубликован список танцев: {available_dances} в {self._commands_topic}'
            )
            
        except Exception as e:
            self.get_logger().error(f'Ошибка при публикации списка танцев: {e}')
            import traceback
            traceback.print_exc()


def main(args=None):
    """Главная функция для запуска узла."""
    rclpy.init(args=args)
    
    try:
        dance_action_server = DanceActionServer()
        rclpy.spin(dance_action_server)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'\nОшибка: {e}')
        import traceback
        traceback.print_exc()
    finally:
        # Безопасное завершение ROS2
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass  # Игнорируем ошибки при завершении


if __name__ == '__main__':
    main()

