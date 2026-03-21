#include "rds_2p_face/display_face.hpp"
#include <algorithm>
#include <cstring>
#include <cerrno>
#include <cstdlib>
#include <csignal>
#include <rclcpp/executors.hpp>

using namespace std::chrono_literals;

// Глобальный указатель на ноду для обработки сигналов
static std::shared_ptr<DisplayFaceNode> g_node = nullptr;

void signal_handler(int /*signal*/) {
    if (g_node) {
        // Принудительно завершаем ROS2 для корректного вызова деструктора
        rclcpp::shutdown();
    }
}

DisplayFaceNode::DisplayFaceNode() : Node("display_face"),
    res_chip_(nullptr), dc_chip_(nullptr), cs_chip_(nullptr),
    res_line_(nullptr), dc_line_(nullptr), cs_line_(nullptr), 
    spi_fd_(-1), display_initialized_(false) {
    // Инициализация GPIO через gpiod (разные чипы для разных пинов)
    res_chip_ = gpiod_chip_open_by_name(RES_PIN_CHIP);
    dc_chip_ = gpiod_chip_open_by_name(DC_PIN_CHIP);
    cs_chip_ = gpiod_chip_open_by_name(CS_PIN_CHIP);
    
    if (!res_chip_ || !dc_chip_ || !cs_chip_) {
        RCLCPP_FATAL(this->get_logger(), "Ошибка открытия GPIO чипов: %s", std::strerror(errno));
        if (res_chip_) gpiod_chip_close(res_chip_);
        if (dc_chip_) gpiod_chip_close(dc_chip_);
        if (cs_chip_) gpiod_chip_close(cs_chip_);
        std::exit(1);
    }
    
    // Получаем GPIO линии
    res_line_ = gpiod_chip_get_line(res_chip_, RES_PIN_LINE);
    dc_line_ = gpiod_chip_get_line(dc_chip_, DC_PIN_LINE);
    cs_line_ = gpiod_chip_get_line(cs_chip_, CS_PIN_LINE);
    
    if (!res_line_ || !dc_line_ || !cs_line_) {
        RCLCPP_FATAL(this->get_logger(), "Ошибка получения GPIO линий: %s", std::strerror(errno));
        if (res_chip_) gpiod_chip_close(res_chip_);
        if (dc_chip_) gpiod_chip_close(dc_chip_);
        if (cs_chip_) gpiod_chip_close(cs_chip_);
        std::exit(1);
    }
    
    // Запрашиваем линии как выходы
    if (gpiod_line_request_output(res_line_, "display_face_res", 1) < 0 ||
        gpiod_line_request_output(dc_line_, "display_face_dc", 0) < 0 ||
        gpiod_line_request_output(cs_line_, "display_face_cs", 1) < 0) {
        RCLCPP_FATAL(this->get_logger(), "Ошибка запроса GPIO линий: %s", std::strerror(errno));
        if (res_chip_) gpiod_chip_close(res_chip_);
        if (dc_chip_) gpiod_chip_close(dc_chip_);
        if (cs_chip_) gpiod_chip_close(cs_chip_);
        std::exit(1);
    }
    
    RCLCPP_INFO(this->get_logger(), "GPIO инициализирован успешно");

    // Инициализация SPI через стандартный Linux интерфейс
    spi_fd_ = open(SPI_DEVICE, O_RDWR);
    if (spi_fd_ < 0) {
        RCLCPP_FATAL(this->get_logger(), "Ошибка открытия SPI устройства %s: %s", SPI_DEVICE, std::strerror(errno));
        RCLCPP_FATAL(this->get_logger(), "Добавьте пользователя в группу spidev: sudo usermod -a -G spidev $USER");
        RCLCPP_FATAL(this->get_logger(), "Затем перелогиньтесь или выполните: newgrp spidev");
        if (res_chip_) gpiod_chip_close(res_chip_);
        if (dc_chip_) gpiod_chip_close(dc_chip_);
        if (cs_chip_) gpiod_chip_close(cs_chip_);
        std::exit(1);
    }
    
    // Настройка SPI режима
    uint8_t mode = SPI_MODE;
    if (ioctl(spi_fd_, SPI_IOC_WR_MODE, &mode) < 0) {
        RCLCPP_ERROR(this->get_logger(), "Ошибка установки SPI режима: %s", std::strerror(errno));
        close(spi_fd_);
        if (res_chip_) gpiod_chip_close(res_chip_);
        if (dc_chip_) gpiod_chip_close(dc_chip_);
        if (cs_chip_) gpiod_chip_close(cs_chip_);
        return;
    }
    
    // Настройка скорости SPI
    uint32_t speed = SPI_SPEED;
    if (ioctl(spi_fd_, SPI_IOC_WR_MAX_SPEED_HZ, &speed) < 0) {
        RCLCPP_ERROR(this->get_logger(), "Ошибка установки скорости SPI: %s", std::strerror(errno));
        close(spi_fd_);
        if (res_chip_) gpiod_chip_close(res_chip_);
        if (dc_chip_) gpiod_chip_close(dc_chip_);
        if (cs_chip_) gpiod_chip_close(cs_chip_);
        return;
    }
    
    RCLCPP_INFO(this->get_logger(), "SPI инициализирован успешно");

    // Инициализация дисплея
    init_display();
    display_initialized_ = true;

    // QoS профиль
    // Используем RELIABLE для более надёжной доставки между процессами под разными пользователями
    rclcpp::QoS qos_profile(10);
    qos_profile.reliability(rclcpp::ReliabilityPolicy::Reliable);  // Changed from BestEffort
    qos_profile.history(rclcpp::HistoryPolicy::KeepLast);
    qos_profile.durability(rclcpp::DurabilityPolicy::Volatile);

    // Подписчик на изображения
    image_sub_ = this->create_subscription<sensor_msgs::msg::Image>(
        "/face/image",
        qos_profile,
        std::bind(&DisplayFaceNode::image_callback, this, std::placeholders::_1)
    );

    RCLCPP_INFO(this->get_logger(), "Display face node started, subscribing to /face/image (rgb8, 280x240)");
}

void DisplayFaceNode::send_command(uint8_t cmd) {
    gpiod_line_set_value(dc_line_, 0);  // DC = LOW для команды
    gpiod_line_set_value(cs_line_, 0);  // CS = LOW
    
    struct spi_ioc_transfer transfer = {};
    transfer.tx_buf = reinterpret_cast<unsigned long>(&cmd);
    transfer.len = 1;
    transfer.speed_hz = SPI_SPEED;
    transfer.bits_per_word = 8;
    
    if (ioctl(spi_fd_, SPI_IOC_MESSAGE(1), &transfer) < 0) {
        RCLCPP_ERROR(this->get_logger(), "Ошибка отправки SPI команды: %s", std::strerror(errno));
    }
    
    gpiod_line_set_value(cs_line_, 1);  // CS = HIGH
}

void DisplayFaceNode::send_data(const std::vector<uint8_t>& data) {
    gpiod_line_set_value(dc_line_, 1);  // DC = HIGH для данных
    gpiod_line_set_value(cs_line_, 0);  // CS = LOW
    
    struct spi_ioc_transfer transfer = {};
    transfer.tx_buf = reinterpret_cast<unsigned long>(data.data());
    transfer.len = data.size();
    transfer.speed_hz = SPI_SPEED;
    transfer.bits_per_word = 8;
    
    if (ioctl(spi_fd_, SPI_IOC_MESSAGE(1), &transfer) < 0) {
        RCLCPP_ERROR(this->get_logger(), "Ошибка отправки SPI данных: %s", std::strerror(errno));
    }
    
    gpiod_line_set_value(cs_line_, 1);  // CS = HIGH
}

void DisplayFaceNode::reset_display() {
    gpiod_line_set_value(res_line_, 0);  // RES = LOW
    usleep(100000); // 0.1 секунда
    gpiod_line_set_value(res_line_, 1);  // RES = HIGH
    usleep(100000); // 0.1 секунда
}

void DisplayFaceNode::init_display() {
    reset_display();
    send_command(ST7789_SWRESET);
    send_command(ST7789_SLPOUT);
    usleep(100000); // 0.1 секунда

    send_command(ST7789_COLMOD);
    send_data({0x05});  // Устанавливаем цветовую модель на 16-битный формат

    send_command(ST7789_MADCTL);
    send_data({0x60});  // Устанавливаем ориентацию дисплея с инверсией
    
    send_command(ST7789_INVON);  // Включаем инверсию цветов

    send_command(ST7789_RASET);
    send_data({0x00, 0x00, 0x00, 0xEF});

    send_command(ST7789_CASET);
    send_data({0x00, 0x14, 0x01, 0xCF});

    send_command(ST7789_DISPON);
    usleep(100000); // 0.1 секунда
}

uint16_t DisplayFaceNode::rgb8_to_rgb565(uint8_t r, uint8_t g, uint8_t b) {
    // Формула из старого кода display_uwu.cpp: ((px[0] & 0xF8) << 8) | ((px[1] & 0xFC) << 3) | (px[2] >> 3)
    // где px[0]=R, px[1]=G, px[2]=B
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}

std::vector<uint16_t> DisplayFaceNode::convert_rgb8_to_rgb565(const std::vector<uint8_t>& rgb8_data, size_t width, size_t height) {
    std::vector<uint16_t> rgb565_data;
    rgb565_data.reserve(width * height);

    // Проверка размера данных
    size_t expected_size = width * height * 3;
    if (rgb8_data.size() < expected_size) {
        RCLCPP_ERROR(this->get_logger(), 
                    "Недостаточно данных для преобразования: %zu байт (ожидается %zu)", 
                    rgb8_data.size(), expected_size);
        return rgb565_data; // Возвращаем пустой вектор
    }

    for (size_t y = 0; y < height; y++) {
        for (size_t x = 0; x < width; x++) {
            size_t idx = y * width * 3 + x * 3;
            uint8_t r = rgb8_data[idx];
            uint8_t g = rgb8_data[idx + 1];
            uint8_t b = rgb8_data[idx + 2];
            rgb565_data.push_back(rgb8_to_rgb565(r, g, b));
        }
    }

    return rgb565_data;
}

void DisplayFaceNode::draw_image(const std::vector<uint16_t>& image) {
    // Проверка размера изображения
    size_t expected_size = IMAGE_WIDTH * IMAGE_HEIGHT;
    if (image.size() != expected_size) {
        RCLCPP_ERROR(this->get_logger(), 
                    "Неверный размер изображения: %zu пикселей (ожидается %zu)", 
                    image.size(), expected_size);
        return;
    }
    
    // Дисплей имеет разрешение 320x240, а изображение 280x240
    // Нужно добавить padding справа (20 пикселей = 40 байт нулей) после каждой строки
    // Как в старом коде display_uwu.cpp
    const size_t PADDING_PIXELS = 20; // 20 пикселей справа
    
    std::vector<uint8_t> data;
    data.reserve((IMAGE_WIDTH + PADDING_PIXELS) * IMAGE_HEIGHT * 2);

    for (size_t h = 0; h < IMAGE_HEIGHT; h++) {
        // Данные изображения
        for (size_t w = 0; w < IMAGE_WIDTH; w++) {
            uint16_t color_n = image[h * IMAGE_WIDTH + w];
            // Порядок байтов: старший байт сначала (big-endian для SPI)
            data.push_back(static_cast<uint8_t>(color_n >> 8));
            data.push_back(static_cast<uint8_t>(color_n & 0xFF));
        }
        
        // Padding справа (20 пикселей = 40 байт нулей) - как в старом коде
        for (size_t p = 0; p < PADDING_PIXELS; p++) {
            data.push_back(0x00);
            data.push_back(0x00);
        }
    }

    const size_t block_size = 4096; // Отправка данных блоками по 4096 байт
    send_command(ST7789_RAMWR);
    
    for (size_t i = 0; i < data.size(); i += block_size) {
        size_t current_block_size = std::min(block_size, data.size() - i);
        std::vector<uint8_t> buffer(data.begin() + i, data.begin() + i + current_block_size);
        send_data(buffer);
    }
}

void DisplayFaceNode::image_callback(const sensor_msgs::msg::Image::SharedPtr msg) {
    if (!display_initialized_) {
        RCLCPP_WARN(this->get_logger(), "Дисплей не инициализирован, пропускаем изображение");
        return;
    }

    // Проверка формата изображения
    if (msg->encoding != "rgb8") {
        RCLCPP_WARN(this->get_logger(), 
                    "Неподдерживаемый формат изображения: %s (ожидается rgb8)", 
                    msg->encoding.c_str());
        return;
    }

    // Проверка разрешения
    if (msg->width != IMAGE_WIDTH || msg->height != IMAGE_HEIGHT) {
        RCLCPP_WARN(this->get_logger(),
                    "Неподдерживаемое разрешение: %ux%u (ожидается %dx%d)",
                    msg->width, msg->height, IMAGE_WIDTH, IMAGE_HEIGHT);
        return;
    }

    // Проверка размера данных
    size_t expected_size = IMAGE_WIDTH * IMAGE_HEIGHT * 3; // rgb8 = 3 байта на пиксель
    if (msg->data.size() < expected_size) {
        RCLCPP_WARN(this->get_logger(), 
                   "Недостаточно данных в изображении: %zu байт (ожидается %zu)", 
                   msg->data.size(), expected_size);
        return;
    }

    try {
        std::vector<uint16_t> rgb565_image = convert_rgb8_to_rgb565(msg->data, msg->width, msg->height);
        draw_image(rgb565_image);
    } catch (const std::exception& e) {
        RCLCPP_ERROR(this->get_logger(), "Ошибка при отображении изображения: %s", e.what());
    }
}

DisplayFaceNode::~DisplayFaceNode() {
    // Закрываем SPI
    if (spi_fd_ >= 0) {
        close(spi_fd_);
    }
    
    // Освобождаем GPIO линии
    if (res_line_) gpiod_line_release(res_line_);
    if (dc_line_) gpiod_line_release(dc_line_);
    if (cs_line_) gpiod_line_release(cs_line_);
    
    // Закрываем GPIO чипы
    if (res_chip_) gpiod_chip_close(res_chip_);
    if (dc_chip_) gpiod_chip_close(dc_chip_);
    if (cs_chip_) gpiod_chip_close(cs_chip_);
}

int main(int argc, char * argv[]) {
    rclcpp::init(argc, argv);
    
    // Регистрируем обработчики сигналов для корректного завершения
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    g_node = std::make_shared<DisplayFaceNode>();
    
    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(g_node);
    
    try {
        executor.spin();
    } catch (...) {
        // Игнорируем исключения при завершении
    }
    
    // Явно сбрасываем ноду для гарантированного вызова деструктора
    g_node.reset();
    
    rclcpp::shutdown();
    return 0;
}

