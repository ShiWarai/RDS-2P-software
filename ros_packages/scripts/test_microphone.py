#!/usr/bin/env python3
"""
Скрипт для проверки микрофона через ROS2 топики.
Подписывается на топик /audio/input (который публикует audio_capturer_node)
и сохраняет полученные данные в WAV файл.
"""

import argparse
import sys
import numpy as np
import wave
import time

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
    from audio_common_msgs.msg import AudioStamped
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False
    print("Ошибка: rclpy или audio_common_msgs не установлены. Установите: pip3 install rclpy audio_common_msgs")
    sys.exit(1)


def save_to_wav(audio_data, filename, sample_rate, channels):
    """Сохранить аудио данные в WAV файл."""
    audio_data = np.clip(audio_data, -1.0, 1.0)
    audio_int16 = (audio_data * 32767).astype(np.int16)
    
    if channels > 1:
        audio_int16 = audio_int16.reshape(-1, channels)
    
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())


def extract_audio_data(audio_data_msg):
    """Извлечь аудио данные из сообщения в numpy array."""
    if hasattr(audio_data_msg, 'float32_data') and len(audio_data_msg.float32_data) > 0:
        return np.array(audio_data_msg.float32_data, dtype=np.float32)
    elif hasattr(audio_data_msg, 'int16_data') and len(audio_data_msg.int16_data) > 0:
        return np.array(audio_data_msg.int16_data, dtype=np.int16).astype(np.float32) / 32768.0
    elif hasattr(audio_data_msg, 'int32_data') and len(audio_data_msg.int32_data) > 0:
        return np.array(audio_data_msg.int32_data, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif hasattr(audio_data_msg, 'int8_data') and len(audio_data_msg.int8_data) > 0:
        return np.array(audio_data_msg.int8_data, dtype=np.int8).astype(np.float32) / 128.0
    elif hasattr(audio_data_msg, 'uint8_data') and len(audio_data_msg.uint8_data) > 0:
        return (np.array(audio_data_msg.uint8_data, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    return None


class AudioSubscriber(Node):
    """ROS2 узел для подписки на аудио топик и сохранения в WAV файл."""
    
    def __init__(self, topic='/audio/input', output_file=None, duration=10.0, monitor=False):
        super().__init__('test_microphone_subscriber')
        self.output_file = output_file
        self.duration = duration
        self.monitor = monitor
        self.start_time = time.time()
        self.finished = False
        self.audio_data = []
        self.sample_rate = None
        self.channels = None
        
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        self.subscription = self.create_subscription(
            AudioStamped,
            topic,
            self.audio_callback,
            sensor_qos
        )
        
        self.get_logger().info(f'Подписка на топик {topic}')
        if output_file:
            self.get_logger().info(f'Сохранение в файл: {output_file}')
        if monitor:
            self.get_logger().info('Режим мониторинга уровня сигнала')
        
        self.timer = self.create_timer(0.1, self.check_duration)
    
    def check_duration(self):
        """Проверка длительности записи."""
        if time.time() - self.start_time >= self.duration:
            self.finished = True
            self.timer.cancel()
    
    def audio_callback(self, msg):
        """Обработка входящих аудио сообщений."""
        if self.finished:
            return
        
        try:
            audio_info = msg.audio.info
            if self.sample_rate is None:
                self.sample_rate = audio_info.rate
                self.channels = audio_info.channels
            
            data = extract_audio_data(msg.audio.audio_data)
            if data is None or len(data) == 0:
                return
            
            if audio_info.channels > 1 and len(data) % audio_info.channels == 0:
                data = data.reshape(-1, audio_info.channels)
            
            if self.output_file:
                self.audio_data.append(data.flatten())
            
            if self.monitor:
                level = np.max(np.abs(data))
                rms = np.sqrt(np.mean(data**2))
                bar_length = 50
                filled = min(int(level * bar_length * 10), bar_length)
                bar = '█' * filled + '░' * (bar_length - filled)
                print(f"\rУровень: {level:.4f} |{bar}| RMS: {rms:.4f}   ", end='', flush=True)
        except Exception as e:
            self.get_logger().error(f'Ошибка обработки аудио: {e}')
    
    def save_to_file(self):
        """Сохранить накопленные данные в WAV файл."""
        if not self.output_file or not self.audio_data:
            return False
        
        try:
            combined_audio = np.concatenate(self.audio_data)
            save_to_wav(combined_audio, self.output_file, self.sample_rate, self.channels)
            return True
        except Exception as e:
            self.get_logger().error(f'Ошибка сохранения в WAV: {e}')
            return False


def subscribe_and_save(topic='/audio/input', output_file=None, duration=10.0, monitor=False):
    """Подписаться на топик и сохранить в WAV файл."""
    print(f"Подписка на топик: {topic}")
    if output_file:
        print(f"Сохранение в файл: {output_file}")
    print(f"Длительность записи: {duration} сек")
    if monitor:
        print("Режим мониторинга уровня сигнала")
    print("\nОжидание аудио данных из топика... (Ctrl+C для остановки)\n")
    
    rclpy.init()
    subscriber = None
    try:
        subscriber = AudioSubscriber(topic=topic, output_file=output_file, duration=duration, monitor=monitor)
        
        while rclpy.ok() and not subscriber.finished:
            rclpy.spin_once(subscriber, timeout_sec=0.1)
        
        if output_file and subscriber.save_to_file():
            print(f"\n✓ Запись сохранена в: {output_file}")
        
    except KeyboardInterrupt:
        print("\n\nОстановка записи...")
        if subscriber and output_file and subscriber.audio_data:
            subscriber.save_to_file()
            print(f"✓ Запись сохранена в: {output_file}")
    except Exception as e:
        print(f"\n✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if rclpy.ok():
            rclpy.shutdown()
    
    print("✓ Запись завершена")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Скрипт для проверки микрофона через ROS2 топики',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Подписаться на топик и сохранить в файл
  %(prog)s --output recording.wav

  # Записать на определенное время
  %(prog)s --output recording.wav --duration 5

  # Мониторинг уровня сигнала (без сохранения)
  %(prog)s --monitor
        """
    )
    
    parser.add_argument('--topic', type=str, default='/audio/input', metavar='TOPIC',
                       help='ROS2 топик для подписки (по умолчанию: /audio/input)')
    parser.add_argument('--output', '-o', type=str, metavar='FILE',
                       help='Сохранить запись в WAV файл')
    parser.add_argument('--monitor', action='store_true',
                       help='Мониторинг уровня сигнала в реальном времени')
    parser.add_argument('--duration', type=float, default=10.0, metavar='SEC',
                       help='Длительность записи/мониторинга в секундах (по умолчанию: 10.0)')
    
    args = parser.parse_args()
    
    if not args.output and not args.monitor:
        parser.error("Необходимо указать либо --output для сохранения в файл, либо --monitor для мониторинга")
    
    success = subscribe_and_save(
        topic=args.topic,
        output_file=args.output,
        duration=args.duration,
        monitor=args.monitor
    )
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
