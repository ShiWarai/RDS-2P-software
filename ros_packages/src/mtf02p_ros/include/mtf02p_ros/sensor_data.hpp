#ifndef MTF02P_ROS__SENSOR_DATA_HPP_
#define MTF02P_ROS__SENSOR_DATA_HPP_

#include <cstdint>

struct SensorData {
  uint8_t dev_id;
  uint8_t sys_id;
  uint8_t seq;
  uint32_t system_time;
  uint32_t distance;
  uint8_t distance_strength;
  uint8_t distance_precision;
  uint8_t distance_status;
  uint8_t reserved1;
  int16_t flow_vel_x;
  int16_t flow_vel_y;
  uint8_t flow_quality;
  uint8_t flow_status;
  uint16_t reserved2;
};

#endif  // MTF02P_ROS__SENSOR_DATA_HPP_

