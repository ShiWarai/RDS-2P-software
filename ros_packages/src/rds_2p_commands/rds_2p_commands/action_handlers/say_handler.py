#!/usr/bin/env python3
"""Обработчик для Say Action - пример кастомного действия.

Это простой пример кастомного действия, которое выводит текст в лог и публикует в топик.
"""

import time
from rclpy.node import Node
from std_msgs.msg import String

from rds_2p_commands.action import Say


class SayHandler:
    """Обработчик для Say Action - пример кастомного действия."""

    def __init__(self, node: Node):
        """
        Инициализация обработчика.

        Args:
            node: ROS2 нода для доступа к параметрам и публикаторам
        """
        self.node = node
        
        # Создаем публикатор для вывода текста (опционально)
        self.text_publisher = self.node.create_publisher(
            String,
            '/robot/say',
            10
        )
        
        self.node.get_logger().info('SayHandler инициализирован')
    
    def execute_callback(self, goal_handle):
        """
        Callback для выполнения Action goal.
        
        Это простой пример - просто выводит текст в лог и публикует в топик.
        В реальном действии здесь может быть любая логика.
        """
        text = goal_handle.request.text
        
        self.node.get_logger().info(f'[Say Action] Получен текст: "{text}"')
        
        # Публикуем feedback
        feedback_msg = Say.Feedback()
        feedback_msg.status = f'Обработка текста: {text}'
        goal_handle.publish_feedback(feedback_msg)
        
        # Имитация обработки (можно убрать для мгновенного выполнения)
        time.sleep(0.5)
        
        # Публикуем текст в топик (опционально)
        msg = String()
        msg.data = text
        self.text_publisher.publish(msg)
        
        # Обновляем feedback
        feedback_msg.status = 'Текст обработан и опубликован'
        goal_handle.publish_feedback(feedback_msg)
        
        # Завершаем успешно
        goal_handle.succeed()
        result = Say.Result()
        result.success = True
        result.message = f'Текст "{text}" успешно обработан'
        
        self.node.get_logger().info(f'[Say Action] Завершено: {result.message}')
        return result

