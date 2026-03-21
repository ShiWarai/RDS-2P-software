#!/usr/bin/env python3
"""
Скрипт для проверки микрофона на desktop (без ROS2).
Захватывает аудио напрямую с микрофона и сохраняет в WAV файл или показывает уровень сигнала.

Настройка для WSL2:
  Для работы микрофона в WSL2 необходимо настроить аудио:
  
  1. Установите PulseAudio в WSL2:
     sudo apt-get update
     sudo apt-get install -y pulseaudio pulseaudio-utils
  
  2. Создайте конфигурацию PulseAudio:
     mkdir -p ~/.config/pulse
     cat > ~/.config/pulse/client.conf << 'EOF'
     default-server = tcp:localhost:4713
     autospawn = no
     daemon-binary = /usr/bin/pulseaudio
     EOF
  
  3. Настройте аудио в Windows (выберите один из вариантов):
  
     ВАРИАНТ 1 (Рекомендуется): PulseAudio для Windows
     - Скачайте и установите: https://www.freedesktop.org/wiki/Software/PulseAudio/Ports/Windows/Support/
     - Или используйте установщик: https://github.com/mklement0/pulseaudio-windows-installer
     - PulseAudio должен автоматически запускаться и слушать на порту 4713
     
     ВАРИАНТ 2: WSL Audio
     - Установите WSL Audio в Windows
     - Следуйте инструкциям: https://github.com/dorssel/usbipd-win
     
     ВАРИАНТ 3: PulseAudio через TCP (если уже установлен)
     - Убедитесь, что PulseAudio запущен в Windows на порту 4713
     - В WSL2 установите переменную окружения:
       export PULSE_SERVER=tcp:localhost:4713
     - Или добавьте в ~/.bashrc для постоянной настройки
  
  4. После настройки перезапустите WSL2 и проверьте устройства:
     python3 test_microphone_desktop.py --list-devices
"""

import argparse
import sys
import numpy as np
import wave
import time

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    print("Ошибка: sounddevice не установлен. Установите: pip3 install sounddevice")
    print("Для работы в WSL2 также может потребоваться настроить PulseAudio.")
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


def list_audio_devices():
    """Показать список доступных аудио устройств."""
    print("\nДоступные аудио устройства:")
    print("=" * 80)
    devices = sd.query_devices()
    
    input_devices = []
    output_devices = []
    
    for i, device in enumerate(devices):
        device_type = []
        if device['max_input_channels'] > 0:
            device_type.append('INPUT')
            input_devices.append(i)
        if device['max_output_channels'] > 0:
            device_type.append('OUTPUT')
            output_devices.append(i)
        
        print(f"  [{i}] {device['name']}")
        print(f"      Тип: {', '.join(device_type) if device_type else 'N/A'}")
        print(f"      Частота: {device['default_samplerate']} Hz")
        print(f"      Каналы: {device['max_input_channels']} входных, {device['max_output_channels']} выходных")
        print()
    
    # Попытка получить устройства по умолчанию с обработкой ошибок
    try:
        default_input = sd.query_devices(kind='input')
        print(f"Устройство по умолчанию (вход): [{default_input['index']}] {default_input['name']}")
    except Exception as e:
        print(f"⚠ Устройство по умолчанию (вход): не найдено ({e})")
        if input_devices:
            print(f"   Доступные устройства входа: {input_devices}")
    
    try:
        default_output = sd.query_devices(kind='output')
        print(f"Устройство по умолчанию (выход): [{default_output['index']}] {default_output['name']}")
    except Exception as e:
        print(f"⚠ Устройство по умолчанию (выход): не найдено ({e})")
        if output_devices:
            print(f"   Доступные устройства выхода: {output_devices}")
    
    if not input_devices:
        print("\n⚠ ВНИМАНИЕ: Не найдено устройств для захвата аудио (микрофон)!")
        print("   Для работы в WSL2 необходимо настроить аудио:")
        print("   1. Установите PulseAudio в WSL2: sudo apt-get install pulseaudio")
        print("   2. Или используйте WSL Audio для Windows")
        print("   3. Проверьте настройки аудио в Windows")
    
    print()


def record_audio(output_file=None, duration=10.0, sample_rate=48000, channels=1, device=None, monitor=False):
    """Записать аудио с микрофона."""
    # Проверка наличия устройств входа
    devices = sd.query_devices()
    input_devices = [i for i, d in enumerate(devices) if d['max_input_channels'] > 0]
    
    if not input_devices:
        print("✗ Ошибка: Не найдено устройств для захвата аудио (микрофон)!")
        print("\nДля работы в WSL2 необходимо настроить аудио:")
        print("  1. Установите PulseAudio в WSL2: sudo apt-get install pulseaudio")
        print("  2. Или используйте WSL Audio для Windows")
        print("  3. Проверьте настройки аудио в Windows")
        print("\nИспользуйте --list-devices для просмотра доступных устройств")
        return False
    
    print(f"Запись аудио...")
    print(f"  Частота дискретизации: {sample_rate} Hz")
    print(f"  Каналы: {channels}")
    print(f"  Длительность: {duration} сек")
    
    # Автоматический выбор устройства для WSL2
    try:
        if device is not None:
            device_info = sd.query_devices(device)
            if device_info['max_input_channels'] == 0:
                print(f"✗ Ошибка: Устройство [{device}] не поддерживает захват аудио!")
                print(f"   Доступные устройства входа: {input_devices}")
                return False
            print(f"  Устройство: [{device}] {device_info['name']}")
        else:
            # В WSL2 предпочитаем использовать PulseAudio напрямую
            pulse_device = None
            for dev_idx in input_devices:
                dev_info = sd.query_devices(dev_idx)
                if 'pulse' in dev_info['name'].lower():
                    pulse_device = dev_idx
                    break
            
            if pulse_device is not None:
                device = pulse_device
                device_info = sd.query_devices(device)
                print(f"  Устройство: [{device}] {device_info['name']} (PulseAudio, автоматически выбрано)")
            else:
                try:
                    device_info = sd.query_devices(kind='input')
                    device = device_info['index']
                    print(f"  Устройство: [{device}] {device_info['name']} (по умолчанию)")
                except Exception:
                    # Если нет устройства по умолчанию, используем первое доступное устройство входа
                    device = input_devices[0]
                    device_info = sd.query_devices(device)
                    print(f"  Устройство: [{device}] {device_info['name']} (первое доступное)")
            
            # Используем частоту дискретизации устройства, если она отличается
            if device_info['default_samplerate'] != sample_rate:
                print(f"  ⚠ Частота устройства: {device_info['default_samplerate']} Hz (используется {sample_rate} Hz)")
    except Exception as e:
        print(f"✗ Ошибка при получении информации об устройстве: {e}")
        return False
    
    if output_file:
        print(f"  Сохранение в: {output_file}")
    if monitor:
        print("  Режим мониторинга уровня сигнала")
    print("\nНачинаю запись... (Ctrl+C для остановки)\n")
    
    audio_data = []
    start_time = time.time()
    
    def audio_callback(indata, frames, time_info, status):
        """Callback функция для обработки аудио данных."""
        if status:
            print(f"⚠ Статус: {status}", file=sys.stderr)
        
        nonlocal audio_data, start_time
        
        if output_file:
            audio_data.append(indata.copy())
        
        if monitor:
            level = np.max(np.abs(indata))
            rms = np.sqrt(np.mean(indata**2))
            bar_length = 50
            filled = min(int(level * bar_length * 10), bar_length)
            bar = '█' * filled + '░' * (bar_length - filled)
            elapsed = time.time() - start_time
            print(f"\r[{elapsed:6.1f}с] Уровень: {level:.4f} |{bar}| RMS: {rms:.4f}   ", end='', flush=True)
    
    # Сохраняем оригинальное устройство для fallback
    original_device = device
    original_device_name = device_info.get('name', '') if device_info else ''
    
    try:
        with sd.InputStream(
            device=device,
            channels=channels,
            samplerate=sample_rate,
            callback=audio_callback,
            blocksize=int(sample_rate * 0.1),  # 100ms блоки
            latency='low'
        ):
            if monitor:
                # В режиме мониторинга работаем до Ctrl+C
                while True:
                    time.sleep(0.1)
            else:
                # В режиме записи ждем указанное время
                time.sleep(duration)
        
        if output_file and audio_data:
            print("\n\nСохранение в файл...")
            combined_audio = np.concatenate(audio_data, axis=0)
            if channels == 1:
                combined_audio = combined_audio.flatten()
            save_to_wav(combined_audio, output_file, sample_rate, channels)
            print(f"✓ Запись сохранена в: {output_file}")
        
        if monitor:
            print("\n✓ Мониторинг завершен")
        else:
            print("✓ Запись завершена")
        
        return True
        
    except sd.PortAudioError as e:
        # Если ошибка с устройством по умолчанию, пробуем PulseAudio
        if original_device is None or 'default' in str(original_device_name).lower():
            pulse_device = None
            for dev_idx in input_devices:
                dev_info = sd.query_devices(dev_idx)
                if 'pulse' in dev_info['name'].lower() and dev_idx != device:
                    pulse_device = dev_idx
                    break
            
            if pulse_device is not None:
                print(f"\n⚠ Ошибка с устройством по умолчанию. Пробую PulseAudio...")
                print(f"  Переключение на устройство: [{pulse_device}] {sd.query_devices(pulse_device)['name']}")
                device = pulse_device
                device_info = sd.query_devices(device)
                # Используем частоту устройства, если она поддерживается
                device_rate = int(device_info['default_samplerate'])
                if abs(device_rate - sample_rate) > 1000:
                    print(f"  Использование частоты устройства: {device_rate} Hz")
                    sample_rate = device_rate
                
                # Повторная попытка с PulseAudio
                audio_data = []  # Сброс данных
                with sd.InputStream(
                    device=device,
                    channels=channels,
                    samplerate=sample_rate,
                    callback=audio_callback,
                    blocksize=int(sample_rate * 0.1),
                    latency='low'
                ):
                    if monitor:
                        while True:
                            time.sleep(0.1)
                    else:
                        time.sleep(duration)
                
                if output_file and audio_data:
                    print("\n\nСохранение в файл...")
                    combined_audio = np.concatenate(audio_data, axis=0)
                    if channels == 1:
                        combined_audio = combined_audio.flatten()
                    save_to_wav(combined_audio, output_file, sample_rate, channels)
                    print(f"✓ Запись сохранена в: {output_file}")
                
                if monitor:
                    print("\n✓ Мониторинг завершен")
                else:
                    print("✓ Запись завершена")
                
                return True
            else:
                raise  # Если PulseAudio не найден, пробрасываем ошибку дальше
        else:
            raise  # Если устройство было указано явно, пробрасываем ошибку
        
    except KeyboardInterrupt:
        print("\n\nОстановка записи...")
        if output_file and audio_data:
            combined_audio = np.concatenate(audio_data, axis=0)
            if channels == 1:
                combined_audio = combined_audio.flatten()
            save_to_wav(combined_audio, output_file, sample_rate, channels)
            print(f"✓ Запись сохранена в: {output_file}")
        return True
    except Exception as e:
        print(f"\n✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Скрипт для проверки микрофона на desktop (без ROS2)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Показать список доступных устройств
  %(prog)s --list-devices

  # Записать аудио в файл
  %(prog)s --output recording.wav

  # Записать на определенное время
  %(prog)s --output recording.wav --duration 5

  # Мониторинг уровня сигнала (без сохранения)
  %(prog)s --monitor

  # Использовать конкретное устройство
  %(prog)s --output recording.wav --device 1

Примечание для WSL2:
  Для работы микрофона в WSL2 необходимо настроить аудио.
  Подробные инструкции см. в комментариях в начале файла.
  
  Дополнительная информация:
  - PulseAudio для Windows: https://www.freedesktop.org/wiki/Software/PulseAudio/
  - WSL Audio: https://github.com/dorssel/usbipd-win
        """
    )
    
    parser.add_argument('--output', '-o', type=str, metavar='FILE',
                       help='Сохранить запись в WAV файл')
    parser.add_argument('--monitor', action='store_true',
                       help='Мониторинг уровня сигнала в реальном времени')
    parser.add_argument('--duration', type=float, default=10.0, metavar='SEC',
                       help='Длительность записи/мониторинга в секундах (по умолчанию: 10.0)')
    parser.add_argument('--sample-rate', type=int, default=48000, metavar='HZ',
                       help='Частота дискретизации в Гц (по умолчанию: 48000)')
    parser.add_argument('--channels', type=int, default=1, choices=[1, 2], metavar='N',
                       help='Количество каналов: 1 (моно) или 2 (стерео) (по умолчанию: 1)')
    parser.add_argument('--device', type=int, metavar='ID',
                       help='ID устройства (используйте --list-devices для просмотра)')
    parser.add_argument('--list-devices', action='store_true',
                       help='Показать список доступных аудио устройств и выйти')
    
    args = parser.parse_args()
    
    if args.list_devices:
        list_audio_devices()
        sys.exit(0)
    
    if not args.output and not args.monitor:
        parser.error("Необходимо указать либо --output для сохранения в файл, либо --monitor для мониторинга")
    
    success = record_audio(
        output_file=args.output,
        duration=args.duration,
        sample_rate=args.sample_rate,
        channels=args.channels,
        device=args.device,
        monitor=args.monitor
    )
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

