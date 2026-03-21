#!/usr/bin/env python3
"""ROS2 узел для запуска танцев по комбинации кнопок джойстика.

Отслеживает комбинации:
- Кнопка Options (buttons[6]) + D-pad:
  - buttons[11] = 1 (вверх) -> танец 1
  - buttons[12] = 1 (вправо) -> танец 2
  - buttons[13] = 1 (вниз) -> танец 3
  - buttons[14] = 1 (влево) -> танец 4
- Кнопка Share (buttons[4]) + D-pad:
  - buttons[11] = 1 (вверх) -> танец 5
  - buttons[12] = 1 (вправо) -> танец 6
  - buttons[13] = 1 (вниз) -> танец 7
  - buttons[14] = 1 (влево) -> танец 8
"""

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from sensor_msgs.msg import Joy
from rds_2p_dance.action import PlayDance


class DanceJoyController(Node):
    """Узел для управления танцами через джойстик."""
    
    def __init__(self):
        super().__init__('dance_joy_controller')
        
        # Состояние кнопок для edge detection
        self.options_pressed_prev = False
        self.share_pressed_prev = False
        self.dpad_up_prev = False
        self.dpad_right_prev = False
        self.dpad_down_prev = False
        self.dpad_left_prev = False
        
        # Флаг для отслеживания активного танца
        self.dance_in_progress = False
        
        # Создаем Action клиент для отправки запросов на танец
        self._action_client = ActionClient(self, PlayDance, '/dance/play')
        
        # Подписка на /joy
        self.joy_sub = self.create_subscription(
            Joy,
            '/joy',
            self.joy_callback,
            10
        )
        
        self.get_logger().info('Dance Joy Controller запущен')
        self.get_logger().info('Комбинации для запуска танцев:')
        self.get_logger().info('  Options + Вверх (D-pad) -> Танец 1')
        self.get_logger().info('  Options + Вправо (D-pad) -> Танец 2')
        self.get_logger().info('  Options + Вниз (D-pad) -> Танец 3')
        self.get_logger().info('  Options + Влево (D-pad) -> Танец 4')
        self.get_logger().info('  Share + Вверх (D-pad) -> Танец 5')
        self.get_logger().info('  Share + Вправо (D-pad) -> Танец 6')
        self.get_logger().info('  Share + Вниз (D-pad) -> Танец 7')
        self.get_logger().info('  Share + Влево (D-pad) -> Танец 8')
    
    def joy_callback(self, msg: Joy):
        """Обработка сообщений от джойстика."""
        # Проверяем размер массива buttons
        if len(msg.buttons) < 15:
            return
        
        # Читаем состояние кнопок
        options_pressed = (msg.buttons[6] == 1)
        share_pressed = (msg.buttons[4] == 1)
        dpad_up = (msg.buttons[11] == 1)
        dpad_right = (msg.buttons[12] == 1)
        dpad_down = (msg.buttons[13] == 1)
        dpad_left = (msg.buttons[14] == 1)
        
        # Если танец уже выполняется, игнорируем новые комбинации
        if self.dance_in_progress:
            # Обновляем предыдущие состояния для следующего цикла
            self.options_pressed_prev = options_pressed
            self.share_pressed_prev = share_pressed
            self.dpad_up_prev = dpad_up
            self.dpad_right_prev = dpad_right
            self.dpad_down_prev = dpad_down
            self.dpad_left_prev = dpad_left
            return
        
        # Edge detection: проверяем переход кнопок из 0 в 1
        options_just_pressed = options_pressed and not self.options_pressed_prev
        share_just_pressed = share_pressed and not self.share_pressed_prev
        dpad_up_just_pressed = dpad_up and not self.dpad_up_prev
        dpad_right_just_pressed = dpad_right and not self.dpad_right_prev
        dpad_down_just_pressed = dpad_down and not self.dpad_down_prev
        dpad_left_just_pressed = dpad_left and not self.dpad_left_prev
        
        # Проверяем комбинации: Options + одна из стрелочек
        dance_number = None
        
        if options_pressed:
            if dpad_up_just_pressed:
                dance_number = 1
            elif dpad_right_just_pressed:
                dance_number = 2
            elif dpad_down_just_pressed:
                dance_number = 3
            elif dpad_left_just_pressed:
                dance_number = 4
        elif share_pressed:
            if dpad_up_just_pressed:
                dance_number = 5
            elif dpad_right_just_pressed:
                dance_number = 6
            elif dpad_down_just_pressed:
                dance_number = 7
            elif dpad_left_just_pressed:
                dance_number = 8
        
        # Если обнаружена комбинация, запускаем танец
        if dance_number is not None:
            button_name = "Options" if options_pressed else "Share"
            self.get_logger().info(f'Обнаружена комбинация: {button_name} + D-pad -> Запуск танца #{dance_number}')
            self.send_dance_request(dance_number)
        
        # Обновляем предыдущие состояния
        self.options_pressed_prev = options_pressed
        self.share_pressed_prev = share_pressed
        self.dpad_up_prev = dpad_up
        self.dpad_right_prev = dpad_right
        self.dpad_down_prev = dpad_down
        self.dpad_left_prev = dpad_left
    
    def send_dance_request(self, dance_number: int):
        """Отправить запрос на проигрывание танца через Action."""
        # Ждем, пока Action сервер станет доступен
        if not self._action_client.wait_for_server(timeout_sec=1.0):
            self.get_logger().warn('Action сервер /dance/play недоступен')
            return
        
        # Создаем goal
        goal_msg = PlayDance.Goal()
        goal_msg.dance_number = dance_number
        goal_msg.interpolate = True  # Используем интерполяцию
        goal_msg.speed_multiplier = 0.0  # Используем значение по умолчанию из параметров сервера
        
        # Отправляем goal асинхронно
        self.get_logger().info(f'Отправка запроса на танец #{dance_number}')
        self._send_goal_future = self._action_client.send_goal_async(
            goal_msg,
            feedback_callback=self.feedback_callback
        )
        self._send_goal_future.add_done_callback(self.goal_response_callback)
        
        # Устанавливаем флаг, что танец выполняется
        self.dance_in_progress = True
    
    def goal_response_callback(self, future):
        """Обработка ответа на goal."""
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warn('Запрос на танец отклонен')
            self.dance_in_progress = False
            return
        
        self.get_logger().info('Запрос на танец принят, начинается воспроизведение')
        
        # Ждем завершения выполнения
        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.result_callback)
    
    def feedback_callback(self, feedback_msg):
        """Обработка feedback от Action сервера."""
        feedback = feedback_msg.feedback
        progress = feedback.progress * 100.0
        self.get_logger().debug(
            f'Прогресс танца: {feedback.current_pose}/{feedback.total_poses} '
            f'({progress:.1f}%)'
        )
    
    def result_callback(self, future):
        """Обработка результата выполнения Action."""
        result = future.result().result
        if result.success:
            self.get_logger().info(f'Танец завершен успешно: {result.message}')
        else:
            self.get_logger().warn(f'Танец завершен с ошибкой: {result.message}')
        
        # Сбрасываем флаг выполнения танца
        self.dance_in_progress = False


def main(args=None):
    """Главная функция для запуска узла."""
    rclpy.init(args=args)
    
    try:
        dance_joy_controller = DanceJoyController()
        rclpy.spin(dance_joy_controller)
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


