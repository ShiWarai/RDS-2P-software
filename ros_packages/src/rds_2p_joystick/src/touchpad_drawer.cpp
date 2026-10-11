#include "rds_2p_joystick/touchpad_drawer.hpp"
#include <cmath>
#include <algorithm>
#include <opencv2/opencv.hpp>
#include <opencv2/imgproc/imgproc.hpp>

using namespace std::chrono_literals;

TouchpadDrawerNode::TouchpadDrawerNode() : Node("touchpad_drawer") {
    // Константы
    constexpr int TOUCHPAD_WIDTH = 1920;
    constexpr int TOUCHPAD_HEIGHT = 943;
    constexpr int MAX_HISTORY = 500;
    constexpr int MIN_BRUSH_SIZE = 10;
    constexpr int MAX_BRUSH_SIZE = 100;
    constexpr int DEFAULT_BRUSH_SIZE = MIN_BRUSH_SIZE;
    constexpr double FAST_TOUCH_THRESHOLD = 0.7;
    constexpr double L2_DRAW_DEADZONE = 0.12;  // 12% хода курка
    
    // QoS профиль с увеличенной глубиной очереди
    rclcpp::QoS qos_profile(100);
    qos_profile.reliability(rclcpp::ReliabilityPolicy::BestEffort);
    qos_profile.history(rclcpp::HistoryPolicy::KeepLast);
    
    // Подписчик на тачпад
    touchpad_sub_ = this->create_subscription<geometry_msgs::msg::PointStamped>(
        "/joy/touchpad",
        qos_profile,
        std::bind(&TouchpadDrawerNode::touchpad_callback, this, std::placeholders::_1)
    );
    
    // Подписчик на джойстик
    joy_sub_ = this->create_subscription<sensor_msgs::msg::Joy>(
        "/joy",
        qos_profile,
        std::bind(&TouchpadDrawerNode::joy_callback, this, std::placeholders::_1)
    );
    
    // Публикатор изображения
    image_pub_ = this->create_publisher<sensor_msgs::msg::Image>(
        "/joy/drawing",
        10
    );
    touch_rate_pub_ = this->create_publisher<std_msgs::msg::Float32>(
        "/joy/touch_rate_hz",
        10
    );
    
    // Инициализация
    brush_size_.store(DEFAULT_BRUSH_SIZE);
    drawing_enabled_.store(false);
    last_touch_msg_time_ = 0.0;
    touch_rate_intervals_count_ = 0;
    touch_rate_intervals_sum_ = 0.0;
    // Используем OpenCV Mat для быстрой отрисовки
    image_ = cv::Mat::zeros(TOUCHPAD_HEIGHT, TOUCHPAD_WIDTH, CV_8UC1);
    touchpad_width_ = TOUCHPAD_WIDTH;
    touchpad_height_ = TOUCHPAD_HEIGHT;
    max_history_ = MAX_HISTORY;
    min_brush_size_ = MIN_BRUSH_SIZE;
    max_brush_size_ = MAX_BRUSH_SIZE;
    fast_touch_threshold_ = FAST_TOUCH_THRESHOLD;
    max_points_per_frame_ = 50;  // Лимит точек для обработки за кадр
    last_clear_time_ = 0.0;
    last_drawn_index_ = 0;
    dirty_.store(false);
    
    // Таймер для публикации изображения (~30 FPS)
    publish_timer_ = this->create_wall_timer(
        33ms,
        std::bind(&TouchpadDrawerNode::publish_image, this)
    );
    
    RCLCPP_INFO(this->get_logger(), "Touchpad drawer node started");
    RCLCPP_INFO(this->get_logger(), "Publishing to /joy/drawing at ~30 FPS");
    RCLCPP_INFO(this->get_logger(), "Publishing touch rate to /joy/touch_rate_hz");
    RCLCPP_INFO(this->get_logger(), "Brush size control: L2 axis (index 4, -1=max, 1=min)");
    RCLCPP_INFO(this->get_logger(), "Drawing enabled when L2 press > %.0f%%", L2_DRAW_DEADZONE * 100.0);
    RCLCPP_INFO(this->get_logger(), "Clear: L2==-1 and button 0 (X button)");
}

void TouchpadDrawerNode::touchpad_callback(const geometry_msgs::msg::PointStamped::SharedPtr msg) {
    constexpr double TOUCH_RATE_RESET_TIMEOUT = 0.7;  // Пауза, после которой начинаем новую сессию частоты
    const double now_time = this->now().seconds();

    // Публикуем среднюю частоту входящих touch-сообщений в пределах одной сессии касания.
    // Если была длинная пауза, считаем, что началась новая сессия и сбрасываем статистику.
    if (last_touch_msg_time_ > 0.0) {
        const double dt = now_time - last_touch_msg_time_;
        if (dt > TOUCH_RATE_RESET_TIMEOUT) {
            touch_rate_intervals_count_ = 0;
            touch_rate_intervals_sum_ = 0.0;
        } else if (dt > 0.0) {
            touch_rate_intervals_sum_ += dt;
            ++touch_rate_intervals_count_;
            if (touch_rate_intervals_sum_ > 0.0) {
                std_msgs::msg::Float32 rate_msg;
                rate_msg.data = static_cast<float>(
                    static_cast<double>(touch_rate_intervals_count_) / touch_rate_intervals_sum_
                );
                touch_rate_pub_->publish(rate_msg);
            }
        }
    }
    last_touch_msg_time_ = now_time;

    if (!drawing_enabled_.load()) {
        return;
    }

    double received_time = now_time;
    double x = msg->point.x;
    double y = msg->point.y;
    
    // Проверяем валидность координат
    if (x >= 0 && x <= touchpad_width_ && y >= 0 && y <= touchpad_height_) {
        double timestamp = static_cast<double>(msg->header.stamp.sec) + 
                          static_cast<double>(msg->header.stamp.nanosec) / 1e9;
        
        // Сохраняем текущий размер кисти вместе с точкой (atomic, без блокировки)
        int current_brush_size = brush_size_.load();
        
        TouchPoint point;
        point.x = x;
        point.y = y;
        point.timestamp = timestamp;
        point.received_time = received_time;
        point.brush_size = current_brush_size;
        
        // Удаляем старые точки (старше 5 секунд)
        {
            std::lock_guard<std::mutex> lock(data_mutex_);
            while (!touch_history_.empty() && 
                   received_time - touch_history_.front().received_time > 5.0) {
                touch_history_.pop_front();
                if (last_drawn_index_ > 0) {
                    --last_drawn_index_;
                }
            }
            
            touch_history_.push_back(point);
            
            // Ограничиваем размер истории (deque - быстрый pop_front)
            while (touch_history_.size() > max_history_) {
                touch_history_.pop_front();
                if (last_drawn_index_ > 0) {
                    --last_drawn_index_;
                }
            }
            
            dirty_.store(true);
        }
    }
}

void TouchpadDrawerNode::joy_callback(const sensor_msgs::msg::Joy::SharedPtr msg) {
    auto current_time = this->now().seconds();
    
    // Управление толщиной через L2 (ось 4)
    if (msg->axes.size() > 4) {
        double l2_value = msg->axes[4];  // L2 ось (от -1 до 1)
        constexpr double L2_DRAW_DEADZONE = 0.12;  // 12% от отпущенного состояния (1.0)
        // 1.0 — отпущен. Включаем рисование, только когда ушли ниже 1.0 хотя бы на dead zone.
        const double l2_draw_threshold = 1.0 - L2_DRAW_DEADZONE;
        const bool zero_like_state = (l2_value == 0.0);  // Блокируем только строго 0.0
        const bool new_drawing_enabled = (l2_value <= l2_draw_threshold) && !zero_like_state;
        drawing_enabled_.store(new_drawing_enabled);

        // L2: -1 -> MAX (инвертировано), 1 -> MIN
        int new_brush_size = static_cast<int>(
            max_brush_size_ - 
            (l2_value + 1.0) / 2.0 * (max_brush_size_ - min_brush_size_)
        );
        new_brush_size = std::max(min_brush_size_, std::min(max_brush_size_, new_brush_size));
        brush_size_.store(new_brush_size);
    }
    
    // Стирание по комбинации L2==-1 и кнопка крестика (кнопка 0)
    if (msg->axes.size() > 4 && msg->buttons.size() > 0) {
        double l2_value = msg->axes[4];
        int x_button = msg->buttons[0];  // Кнопка крестика
        
        // Проверяем комбинацию: L2 полностью нажата (-1) и кнопка X нажата
        if (l2_value < -0.9 && x_button == 1) {
            // Защита от повторного срабатывания (минимум 0.3 секунды между очистками)
            if (current_time - last_clear_time_ > 0.3) {
                clear_image();
                last_clear_time_ = current_time;
            }
        }
    }
}

void TouchpadDrawerNode::clear_image() {
    {
        std::lock_guard<std::mutex> lock(data_mutex_);
        touch_history_.clear();
        image_.setTo(cv::Scalar(0));  // Заливаем черным (OpenCV)
        last_drawn_index_ = 0;
        dirty_.store(true);
    }
    RCLCPP_INFO(this->get_logger(), "Image cleared");
    
    // Немедленно публикуем очищенное изображение
    publish_image();
}

void TouchpadDrawerNode::draw_on_image() {
    std::deque<TouchPoint> touch_history;
    size_t current_last_drawn_index;
    
    {
        std::lock_guard<std::mutex> lock(data_mutex_);
        touch_history = touch_history_;
        current_last_drawn_index = last_drawn_index_;
    }
    
    // Если нет новых точек для отрисовки, выходим
    if (current_last_drawn_index >= touch_history.size()) {
        return;
    }
    
    // Лимит точек для обработки за кадр (предотвращает зависания)
    size_t end_index = std::min(touch_history.size(), 
                                current_last_drawn_index + max_points_per_frame_);
    
    // Если это первая точка, рисуем её как круг
    if (touch_history.size() == 1 && current_last_drawn_index == 0) {
        const auto& point = touch_history[0];
        draw_circle(static_cast<int>(point.x), static_cast<int>(point.y), point.brush_size);
        {
            std::lock_guard<std::mutex> lock(data_mutex_);
            last_drawn_index_ = 1;
            dirty_.store(true);
        }
        return;
    }
    
    // Инкрементальная отрисовка: рисуем только новые точки до лимита
    // Начинаем с last_drawn_index_ - 1, чтобы соединить с предыдущей точкой
    size_t start_index = (current_last_drawn_index > 0) ? current_last_drawn_index - 1 : 0;
    
    for (size_t i = start_index; i < end_index - 1 && i < touch_history.size() - 1; ++i) {
        const auto& point = touch_history[i];
        const auto& next_point = touch_history[i + 1];
        
        // Вычисляем время между точками (используем timestamp из сообщения)
        double time_diff = next_point.timestamp - point.timestamp;
        
        // FAST_TOUCH_THRESHOLD (0.4 сек): если время между точками меньше порога - 
        // это быстрое движение, рисуем линию. Иначе - медленное движение или пауза, рисуем точку.
        if (time_diff < fast_touch_threshold_) {
            // Используем размер кисти из следующей точки (или текущей, если они одинаковые)
            // Для плавности используем средний размер между точками
            int avg_brush_size = (point.brush_size + next_point.brush_size) / 2;
            draw_line(
                static_cast<int>(point.x), static_cast<int>(point.y),
                static_cast<int>(next_point.x), static_cast<int>(next_point.y),
                avg_brush_size
            );
        } else {
            // Большой разрыв - рисуем точку с размером кисти из точки
            draw_circle(static_cast<int>(point.x), static_cast<int>(point.y), point.brush_size);
        }
    }
    
    // Рисуем последнюю точку как круг с размером кисти из точки (если дошли до конца)
    if (end_index >= touch_history.size() && !touch_history.empty()) {
        const auto& last_point = touch_history.back();
        draw_circle(static_cast<int>(last_point.x), static_cast<int>(last_point.y), last_point.brush_size);
    }
    
    // Обновляем индекс последней отрисованной точки
    {
        std::lock_guard<std::mutex> lock(data_mutex_);
        last_drawn_index_ = end_index;
        // Устанавливаем dirty только если действительно что-то нарисовали
        if (end_index > start_index) {
            dirty_.store(true);
        }
    }
}

void TouchpadDrawerNode::draw_line(int x1, int y1, int x2, int y2, int width) {
    // Используем OpenCV для быстрого рисования толстых линий (оптимизировано с SSE/AVX)
    // width - это радиус кисти, но cv::line принимает thickness (диаметр), поэтому умножаем на 2
    cv::line(image_, 
             cv::Point(x1, y1), 
             cv::Point(x2, y2), 
             cv::Scalar(255), 
             width * 2,  // Преобразуем радиус в диаметр для толщины линии
             cv::LINE_AA);  // LINE_AA для сглаживания
}

void TouchpadDrawerNode::draw_circle(int cx, int cy, int radius) {
    // Ограничиваем радиус допустимыми значениями
    if (radius < 1 || radius > max_brush_size_) {
        return;
    }
    
    // Используем OpenCV для быстрого рисования заполненного круга (оптимизировано)
    cv::circle(image_, 
               cv::Point(cx, cy), 
               radius, 
               cv::Scalar(255), 
               -1,  // -1 для заполнения
               cv::LINE_AA);  // LINE_AA для сглаживания
}


void TouchpadDrawerNode::publish_image() {
    // Пропускаем публикацию, если нет изменений
    if (!dirty_.load()) {
        return;
    }
    
    // Отрисовываем новые точки
    draw_on_image();
    
    // Проверяем dirty снова после отрисовки
    if (!dirty_.load()) {
        return;
    }
    
    // Создаем ROS сообщение Image
    auto img_msg = std::make_shared<sensor_msgs::msg::Image>();
    img_msg->header.stamp = this->now();
    img_msg->header.frame_id = "touchpad";
    
    // Формат изображения: монохромное 8-битное
    img_msg->height = touchpad_height_;
    img_msg->width = touchpad_width_;
    img_msg->encoding = "mono8";
    img_msg->is_bigendian = false;
    img_msg->step = touchpad_width_;  // Байт на строку для mono8
    
    // Копируем данные изображения из OpenCV Mat
    {
        std::lock_guard<std::mutex> lock(data_mutex_);
        // Копируем данные из cv::Mat в std::vector
        img_msg->data.assign(image_.datastart, image_.dataend);
        dirty_.store(false);  // Сбрасываем флаг после публикации
    }
    
    // Публикуем
    image_pub_->publish(*img_msg);
}

int main(int argc, char * argv[]) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<TouchpadDrawerNode>());
    rclcpp::shutdown();
    return 0;
}

