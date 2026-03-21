#ifndef MTF02P_ROS__MICOLINK_PARSER_HPP_
#define MTF02P_ROS__MICOLINK_PARSER_HPP_

#include "mtf02p_ros/sensor_data.hpp"
#include <cstdint>
#include <cstddef>

class MicolinkParser {
public:
  MicolinkParser();
  
  bool parse_char(uint8_t data);
  SensorData* get_parsed_data();
  void reset();

private:
  static constexpr uint8_t STX = 0xEF;
  static constexpr uint8_t MSG_ID_RANGE_SENSOR = 0x51;
  static constexpr uint8_t PAYLOAD_LENGTH = 0x14;
  static constexpr size_t MAX_PAYLOAD_LEN = 64;
  
  bool check_sum();
  
  uint8_t status_;
  uint8_t head_;
  uint8_t dev_id_;
  uint8_t sys_id_;
  uint8_t msg_id_;
  uint8_t seq_;
  uint8_t len_;
  uint8_t payload_[MAX_PAYLOAD_LEN];
  size_t payload_cnt_;
  uint8_t checksum_;
  
  SensorData parsed_data_;
  bool has_parsed_data_;
};

#endif  // MTF02P_ROS__MICOLINK_PARSER_HPP_

