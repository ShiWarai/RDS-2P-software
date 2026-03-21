#ifndef MTF02P_ROS__UART_READER_HPP_
#define MTF02P_ROS__UART_READER_HPP_

#include "mtf02p_ros/micolink_parser.hpp"
#include "mtf02p_ros/sensor_data.hpp"
#include <string>
#include <thread>
#include <mutex>
#include <queue>
#include <termios.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/select.h>

class UARTReader {
public:
  UARTReader();
  ~UARTReader();
  
  bool connect(const std::string& port, int baudrate);
  void disconnect();
  bool get_data(SensorData& data);
  
private:
  void read_loop();
  void init_command_loop();
  bool send_micolink_command(uint8_t dev_id, uint8_t sys_id, uint8_t msg_id, 
                            const uint8_t* payload = nullptr, size_t payload_len = 0, uint8_t seq = 0);
  bool send_init_command();
  static speed_t get_baudrate_speed(int baudrate);
  
  std::string port_;
  int baudrate_;
  int fd_;
  struct termios orgopt_;
  bool running_;
  
  std::thread read_thread_;
  std::thread init_thread_;
  
  MicolinkParser parser_;
  
  std::queue<SensorData> data_queue_;
  std::mutex queue_mutex_;
  
  uint8_t init_seq_;
};

#endif  // MTF02P_ROS__UART_READER_HPP_

