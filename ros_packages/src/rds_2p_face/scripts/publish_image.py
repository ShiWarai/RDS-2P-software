#!/usr/bin/env python3
"""
Скрипт для публикации изображения в топик /face/image для тестирования ноды display_face.

Использование:
    python3 publish_image.py <путь_к_изображению>
    
Пример:
    python3 publish_image.py /home/orangepi/face/image/smile3.png
"""

import sys
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from PIL import Image as PILImage


class ImagePublisher(Node):
    def __init__(self, image_path):
        super().__init__('image_publisher')
        
        # Публикатор изображений с Reliable QoS (совместимо с display_face)
        from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
        qos_profile = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,  # Changed from BEST_EFFORT
            history=HistoryPolicy.KEEP_LAST,
            durability=DurabilityPolicy.VOLATILE
        )
        
        self.image_pub = self.create_publisher(
            Image,
            '/face/raw_image',
            qos_profile
        )
        
        self.image_path = image_path
        
        # Загружаем и публикуем изображение
        self.publish_image()
    
    def publish_image(self):
        """Загружает изображение и публикует его в топик."""
        try:
            # Загружаем изображение с помощью PIL
            pil_image = PILImage.open(self.image_path)
            
            # Конвертируем в RGB если нужно
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            
            # Получаем данные изображения в виде байтов (RGB)
            rgb_data = list(pil_image.getdata())
            
            # Получаем размеры изображения
            image_width = pil_image.width
            image_height = pil_image.height
            
            # Преобразуем в плоский список байтов [R, G, B, R, G, B, ...]
            image_data = bytearray()
            for r, g, b in rgb_data:
                image_data.extend([r, g, b])
            
            # Создаём ROS сообщение
            image_msg = Image()
            image_msg.header.stamp = self.get_clock().now().to_msg()
            image_msg.header.frame_id = 'face_display'
            image_msg.height = image_height
            image_msg.width = image_width
            image_msg.encoding = 'rgb8'
            image_msg.is_bigendian = False
            image_msg.step = image_width * 3  # 3 байта на пиксель (RGB)
            image_msg.data = bytes(image_data)
            
            # Публикуем изображение
            self.image_pub.publish(image_msg)
            
        except Exception as e:
            self.get_logger().error(f'Ошибка при публикации изображения: {str(e)}')
            import traceback
            traceback.print_exc()


def main(args=None):
    if len(sys.argv) < 2:
        print('Использование: python3 publish_image.py <путь_к_изображению>')
        print('Пример: python3 publish_image.py /home/orangepi/face/image/smile3.png')
        sys.exit(1)
    
    image_path = sys.argv[1]
    
    rclpy.init(args=args)
    
    try:
        node = ImagePublisher(image_path)
        
        # Ждём немного для DDS discovery и отправки сообщения
        import time
        time.sleep(0.5)  # Минимальное время для DDS discovery
        
        # Делаем несколько spin_once для гарантии отправки сообщения
        for i in range(10):  # Сокращено до 1 секунды вместо 5
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()

