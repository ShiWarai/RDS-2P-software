#include "mtf02p_ros/uart_reader.hpp"
#include <cstring>
#include <chrono>
#include <thread>
#include <sys/ioctl.h>
#include <errno.h>

UARTReader::UARTReader()
  : baudrate_(115200)
  , fd_(-1)
  , running_(false)
  , init_seq_(0x0A)
{
}

UARTReader::~UARTReader()
{
  disconnect();
}

speed_t UARTReader::get_baudrate_speed(int baudrate)
{
  switch (baudrate) {
    case 9600: return B9600;
    case 19200: return B19200;
    case 38400: return B38400;
    case 57600: return B57600;
    case 115200: return B115200;
    case 230400: return B230400;
    case 500000: return B500000;
    case 1000000: return B1000000;
    default: return B115200;
  }
}

bool UARTReader::connect(const std::string& port, int baudrate)
{
  disconnect();
  
  port_ = port;
  baudrate_ = baudrate;
  
  fd_ = open(port.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
  if (fd_ < 0) {
    return false;
  }
  
  struct termios tty;
  if (tcgetattr(fd_, &orgopt_) != 0) {
    close(fd_);
    fd_ = -1;
    return false;
  }
  
  tty = orgopt_;
  
  speed_t speed = get_baudrate_speed(baudrate);
  cfsetispeed(&tty, speed);
  cfsetospeed(&tty, speed);
  
  tty.c_cflag &= ~PARENB;
  tty.c_cflag &= ~CSTOPB;
  tty.c_cflag &= ~CSIZE;
  tty.c_cflag |= CS8;
  tty.c_cflag |= CREAD | CLOCAL;
  tty.c_cflag &= ~CRTSCTS;
  
  tty.c_iflag &= ~(IXON | IXOFF | IXANY | IGNBRK | BRKINT | PARMRK | ISTRIP | INLCR | IGNCR | ICRNL);
  tty.c_oflag &= ~OPOST;
  tty.c_lflag = 0;
  
  tty.c_cc[VMIN] = 0;
  tty.c_cc[VTIME] = 1;
  
  if (tcsetattr(fd_, TCSANOW, &tty) != 0) {
    close(fd_);
    fd_ = -1;
    return false;
  }
  
  tcflush(fd_, TCIOFLUSH);
  parser_.reset();
  
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  send_init_command();
  std::this_thread::sleep_for(std::chrono::milliseconds(200));
  
  running_ = true;
  read_thread_ = std::thread(&UARTReader::read_loop, this);
  init_thread_ = std::thread(&UARTReader::init_command_loop, this);
  
  return true;
}

void UARTReader::disconnect()
{
  running_ = false;
  
  if (read_thread_.joinable()) {
    read_thread_.join();
  }
  
  if (init_thread_.joinable()) {
    init_thread_.join();
  }
  
  if (fd_ >= 0) {
    tcsetattr(fd_, TCSANOW, &orgopt_);
    close(fd_);
    fd_ = -1;
  }
  
  parser_.reset();
}

bool UARTReader::get_data(SensorData& data)
{
  std::lock_guard<std::mutex> lock(queue_mutex_);
  if (data_queue_.empty()) {
    return false;
  }
  data = data_queue_.front();
  data_queue_.pop();
  return true;
}

bool UARTReader::send_micolink_command(uint8_t dev_id, uint8_t sys_id, uint8_t msg_id,
                                       const uint8_t* payload, size_t payload_len, uint8_t seq)
{
  if (fd_ < 0) {
    return false;
  }
  
  uint8_t packet[256];
  size_t idx = 0;
  
  packet[idx++] = 0xEF;
  packet[idx++] = dev_id;
  packet[idx++] = sys_id;
  packet[idx++] = msg_id;
  packet[idx++] = seq & 0xFF;
  packet[idx++] = payload_len & 0xFF;
  
  if (payload && payload_len > 0) {
    memcpy(&packet[idx], payload, payload_len);
    idx += payload_len;
  }
  
  uint8_t checksum = 0;
  for (size_t i = 0; i < idx; ++i) {
    checksum = (checksum + packet[i]) & 0xFF;
  }
  packet[idx++] = checksum;
  
  ssize_t written = write(fd_, packet, idx);
  return written == static_cast<ssize_t>(idx);
}

bool UARTReader::send_init_command()
{
  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
    std::chrono::system_clock::now().time_since_epoch()).count();
  uint32_t timestamp_ms = static_cast<uint32_t>(now_ms) & 0xFFFFFF;
  
  uint8_t payload[13] = {
    static_cast<uint8_t>(timestamp_ms & 0xFF),
    static_cast<uint8_t>((timestamp_ms >> 8) & 0xFF),
    static_cast<uint8_t>((timestamp_ms >> 16) & 0xFF),
    0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00
  };
  
  init_seq_ = (init_seq_ + 1) & 0xFF;
  return send_micolink_command(0x01, 0x00, 0x01, payload, sizeof(payload), init_seq_);
}

void UARTReader::init_command_loop()
{
  while (running_ && fd_ >= 0) {
    std::this_thread::sleep_for(std::chrono::milliseconds(600));
    if (running_) {
      send_init_command();
    }
  }
}

void UARTReader::read_loop()
{
  uint8_t buffer[256];
  
  while (running_ && fd_ >= 0) {
    fd_set readfds;
    FD_ZERO(&readfds);
    FD_SET(fd_, &readfds);
    
    struct timeval timeout;
    timeout.tv_sec = 0;
    timeout.tv_usec = 100000;  // 100ms
    
    int result = select(fd_ + 1, &readfds, nullptr, nullptr, &timeout);
    
    if (result > 0 && FD_ISSET(fd_, &readfds)) {
      ssize_t n = read(fd_, buffer, sizeof(buffer));
      
      if (n > 0) {
        for (ssize_t i = 0; i < n; ++i) {
          if (parser_.parse_char(buffer[i])) {
            SensorData* data = parser_.get_parsed_data();
            if (data) {
              std::lock_guard<std::mutex> lock(queue_mutex_);
              if (data_queue_.size() < 100) {
                data_queue_.push(*data);
              }
            }
          }
        }
      } else if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
        break;
      }
    } else if (result < 0) {
      break;
    }
  }
}

