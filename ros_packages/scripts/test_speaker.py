#!/usr/bin/env python3
"""
Скрипт для проверки динамика через ROS2 топики.
Читает WAV файл и публикует в топик /audio/output (который слушает audio_player_node).
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
    from audio_common_msgs.msg import AudioStamped, Audio, AudioData, AudioInfo
    from std_msgs.msg import Header
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False
    print("Ошибка: rclpy или audio_common_msgs не установлены. Установите: pip3 install rclpy audio_common_msgs")
    sys.exit(1)


def read_wav_file(file_path):
    """Прочитать WAV файл и вернуть данные как numpy array."""
    with wave.open(file_path, 'rb') as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        frames = wf.getnframes()
        data = wf.readframes(frames)
    
    # Конвертируем в numpy array
    if sample_width == 1:
        data_array = np.frombuffer(data, dtype=np.uint8)
        data_array = (data_array.astype(np.float32) - 128) / 128.0
    elif sample_width == 2:
        data_array = np.frombuffer(data, dtype=np.int16)
        data_array = data_array.astype(np.float32) / 32768.0
    elif sample_width == 4:
        data_array = np.frombuffer(data, dtype=np.int32)
        data_array = data_array.astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Неподдерживаемый размер сэмпла: {sample_width}")
    
    if channels > 1:
        data_array = data_array.reshape(-1, channels)
    
    return data_array, sample_rate, channels


def resample_audio(data_array, sample_rate, target_rate, channels):
    """Ресемплировать аудио данные."""
    try:
        import scipy.signal
    except ImportError:
        raise ImportError("scipy не установлен. Установите: pip3 install scipy")
    
    num_samples = int(len(data_array) * target_rate / sample_rate)
    
    if channels > 1:
        resampled = np.zeros((num_samples, channels), dtype=np.float32)
        for ch in range(channels):
            resampled[:, ch] = scipy.signal.resample(data_array[:, ch], num_samples)
        return resampled
    else:
        return scipy.signal.resample(data_array, num_samples)


class AudioPublisher(Node):
    """ROS2 узел для публикации аудио в топик."""
    
    def __init__(self, topic='/audio/output', sample_rate=48000, channels=1):
        super().__init__('test_speaker_publisher')
        
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )
        self.publisher = self.create_publisher(AudioStamped, topic, sensor_qos)
        self.sample_rate = sample_rate
        self.channels = channels
        
        self.get_logger().info(f'Публикация в топик: {topic}, Частота: {sample_rate} Hz, Каналы: {channels}')
    
    def publish_chunk(self, audio_data):
        """Публикует чанк аудио данных."""
        msg = AudioStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'speaker'
        
        msg.audio.info.format = 1  # paFloat32
        msg.audio.info.channels = self.channels
        msg.audio.info.rate = self.sample_rate
        msg.audio.info.chunk = len(audio_data) // self.channels if self.channels > 1 else len(audio_data)
        
        msg.audio.audio_data.float32_data = audio_data.tolist()
        self.publisher.publish(msg)


def publish_wav_to_topic(file_path, topic='/audio/output', chunk_size=512, target_sample_rate=44100):
    """Прочитать WAV файл и опубликовать в ROS2 топик."""
    print(f"Чтение файла: {file_path}")
    print(f"Публикация в топик: {topic}")
    
    try:
        data_array, sample_rate, channels = read_wav_file(file_path)
    except Exception as e:
        print(f"✗ Ошибка чтения файла: {e}")
        return False
    
    print(f"Параметры файла: Частота: {sample_rate} Hz, Каналы: {channels}")
    
    # Ресемплинг, если нужно
    if sample_rate != target_sample_rate:
        try:
            print(f"Ресемплинг: {sample_rate} Hz -> {target_sample_rate} Hz...")
            data_array = resample_audio(data_array, sample_rate, target_sample_rate, channels)
            sample_rate = target_sample_rate
            print("✓ Ресемплинг завершен")
        except ImportError as e:
            print(f"⚠ {e}")
            print("Продолжение без ресемплинга (может не работать)...")
    
    rclpy.init()
    try:
        publisher = AudioPublisher(topic=topic, sample_rate=sample_rate, channels=channels)
        
        print("\nПубликация в топик...\n")
        for i in range(0, len(data_array), chunk_size):
            chunk = data_array[i:i+chunk_size]
            publisher.publish_chunk(chunk.flatten())
            rclpy.spin_once(publisher, timeout_sec=0.0)
            time.sleep(chunk_size / sample_rate)
        
        print("✓ Файл опубликован в топик")
        
    except Exception as e:
        print(f"✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        rclpy.shutdown()
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Скрипт для проверки динамика через ROS2 топики',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Прочитать WAV файл и опубликовать в топик
  %(prog)s --file recording.wav

  # Указать другую частоту для ресемплинга
  %(prog)s --file recording.wav --sample-rate 48000
        """
    )
    
    parser.add_argument('--file', type=str, required=True, metavar='PATH',
                       help='Путь к WAV файлу для публикации в топик')
    parser.add_argument('--topic', type=str, default='/audio/output', metavar='TOPIC',
                       help='ROS2 топик для публикации (по умолчанию: /audio/output)')
    parser.add_argument('--chunk-size', type=int, default=512, metavar='SIZE',
                       help='Размер чанка для публикации (по умолчанию: 512)')
    parser.add_argument('--sample-rate', type=int, default=44100, metavar='HZ',
                       help='Целевая частота дискретизации для ресемплинга (по умолчанию: 44100 Hz)')
    
    args = parser.parse_args()
    
    success = publish_wav_to_topic(
        args.file,
        topic=args.topic,
        chunk_size=args.chunk_size,
        target_sample_rate=args.sample_rate
    )
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
