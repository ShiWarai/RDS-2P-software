#ifndef RDS_2P_FACE__DISPLAY_FACE_HPP_
#define RDS_2P_FACE__DISPLAY_FACE_HPP_

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <rclcpp/qos.hpp>
#include <vector>
#include <string>
#include <stdint.h>
#include <gpiod.h>
#include <linux/spi/spidev.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>

// Настройки GPIO (маппинг с wiringPi на gpiod)
// wiringPi 5 → GPIO 138 → gpiochip4, line 10 (CAN1_RX)
// wiringPi 7 → GPIO 139 → gpiochip4, line 11 (CAN1_TX)
// wiringPi 18 → GPIO 35 → gpiochip1, line 3 (SCL.4)
#define RES_PIN_CHIP "gpiochip4"
#define RES_PIN_LINE 10   // GPIO 138 (wiringPi 5)
#define DC_PIN_CHIP "gpiochip4"
#define DC_PIN_LINE 11    // GPIO 139 (wiringPi 7)
#define CS_PIN_CHIP "gpiochip1"
#define CS_PIN_LINE 3     // GPIO 35 (wiringPi 18)

// Настройки SPI
#define SPI_DEVICE "/dev/spidev4.0"  // SPI устройство
#define SPI_SPEED 20000000  // Скорость SPI (20 MHz)
#define SPI_MODE 0          // SPI режим (CPOL=0, CPHA=0)

// Команды для ST7789
#define ST7789_SWRESET 0x01
#define ST7789_SLPOUT 0x11
#define ST7789_DISPON 0x29
#define ST7789_CASET 0x2A
#define ST7789_RASET 0x2B
#define ST7789_RAMWR 0x2C
#define ST7789_MADCTL 0x36
#define ST7789_COLMOD 0x3A
#define ST7789_INVOFF 0x20
#define ST7789_INVON 0x21

#define IMAGE_WIDTH 280
#define IMAGE_HEIGHT 240

class DisplayFaceNode : public rclcpp::Node {
public:
    DisplayFaceNode();
    ~DisplayFaceNode();

private:
    void image_callback(const sensor_msgs::msg::Image::SharedPtr msg);
    void send_command(uint8_t cmd);
    void send_data(const std::vector<uint8_t>& data);
    void reset_display();
    void init_display();
    void draw_image(const std::vector<uint16_t>& image);
    uint16_t rgb8_to_rgb565(uint8_t r, uint8_t g, uint8_t b);
    std::vector<uint16_t> convert_rgb8_to_rgb565(const std::vector<uint8_t>& rgb8_data, size_t width, size_t height);
    
    // Подписчик на изображения
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr image_sub_;
    
    // GPIO структуры для gpiod (разные чипы для разных пинов)
    struct gpiod_chip* res_chip_;
    struct gpiod_chip* dc_chip_;
    struct gpiod_chip* cs_chip_;
    struct gpiod_line* res_line_;
    struct gpiod_line* dc_line_;
    struct gpiod_line* cs_line_;
    
    // SPI файловый дескриптор
    int spi_fd_;
    
    // Конфигурация SPI/GPIO из параметров (фолбэк на #define по умолчанию)
    std::string spi_device_;
    int spi_mode_;
    int spi_speed_;
    std::string res_chip_name_;
    int res_line_idx_;
    std::string dc_chip_name_;
    int dc_line_idx_;
    std::string cs_chip_name_;
    int cs_line_idx_;
    
    // Флаг инициализации дисплея
    bool display_initialized_;
};

#endif  // RDS_2P_FACE__DISPLAY_FACE_HPP_

