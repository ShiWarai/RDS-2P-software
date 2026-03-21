#include "mtf02p_ros/micolink_parser.hpp"
#include <cstring>

MicolinkParser::MicolinkParser()
  : status_(0)
  , head_(0)
  , dev_id_(0)
  , sys_id_(0)
  , msg_id_(0)
  , seq_(0)
  , len_(0)
  , payload_cnt_(0)
  , checksum_(0)
  , has_parsed_data_(false)
{
  memset(payload_, 0, sizeof(payload_));
  memset(&parsed_data_, 0, sizeof(parsed_data_));
}

void MicolinkParser::reset()
{
  status_ = 0;
  payload_cnt_ = 0;
  has_parsed_data_ = false;
}

bool MicolinkParser::check_sum()
{
  uint8_t checksum = 0;
  checksum = (head_ + dev_id_ + sys_id_ + msg_id_ + seq_ + len_) & 0xFF;
  
  for (size_t i = 0; i < len_; ++i) {
    checksum = (checksum + payload_[i]) & 0xFF;
  }
  
  return checksum == checksum_;
}

bool MicolinkParser::parse_char(uint8_t data)
{
  has_parsed_data_ = false;
  
  if (status_ == 0) {
    if (data == STX) {
      head_ = data;
      status_ = 1;
    }
    return false;
  } else if (status_ == 1) {
    dev_id_ = data;
    status_ = 2;
    return false;
  } else if (status_ == 2) {
    sys_id_ = data;
    status_ = 3;
    return false;
  } else if (status_ == 3) {
    msg_id_ = data;
    status_ = 4;
    return false;
  } else if (status_ == 4) {
    seq_ = data;
    status_ = 5;
    return false;
  } else if (status_ == 5) {
    len_ = data;
    if (len_ == 0) {
      status_ = 7;
    } else if (len_ > MAX_PAYLOAD_LEN) {
      reset();
    } else {
      status_ = 6;
    }
    return false;
  } else if (status_ == 6) {
    payload_[payload_cnt_] = data;
    payload_cnt_++;
    if (payload_cnt_ == len_) {
      payload_cnt_ = 0;
      status_ = 7;
    }
    return false;
  } else if (status_ == 7) {
    checksum_ = data;
    status_ = 0;
    if (check_sum()) {
      // Парсим данные
      if (msg_id_ == MSG_ID_RANGE_SENSOR && len_ == PAYLOAD_LENGTH) {
        parsed_data_.dev_id = dev_id_;
        parsed_data_.sys_id = sys_id_;
        parsed_data_.seq = seq_;
        
        // System time (uint32, little-endian)
        parsed_data_.system_time = 
          static_cast<uint32_t>(payload_[0]) |
          (static_cast<uint32_t>(payload_[1]) << 8) |
          (static_cast<uint32_t>(payload_[2]) << 16) |
          (static_cast<uint32_t>(payload_[3]) << 24);
        
        // Distance (uint32, little-endian)
        parsed_data_.distance = 
          static_cast<uint32_t>(payload_[4]) |
          (static_cast<uint32_t>(payload_[5]) << 8) |
          (static_cast<uint32_t>(payload_[6]) << 16) |
          (static_cast<uint32_t>(payload_[7]) << 24);
        
        parsed_data_.distance_strength = payload_[8];
        parsed_data_.distance_precision = payload_[9];
        parsed_data_.distance_status = payload_[10];
        parsed_data_.reserved1 = payload_[11];
        
        // Flow_vel_x (int16, little-endian, signed)
        uint16_t flow_vel_x_u = 
          static_cast<uint16_t>(payload_[12]) |
          (static_cast<uint16_t>(payload_[13]) << 8);
        parsed_data_.flow_vel_x = *reinterpret_cast<int16_t*>(&flow_vel_x_u);
        
        // Flow_vel_y (int16, little-endian, signed)
        uint16_t flow_vel_y_u = 
          static_cast<uint16_t>(payload_[14]) |
          (static_cast<uint16_t>(payload_[15]) << 8);
        parsed_data_.flow_vel_y = *reinterpret_cast<int16_t*>(&flow_vel_y_u);
        
        parsed_data_.flow_quality = payload_[16];
        parsed_data_.flow_status = payload_[17];
        
        // Reserved2 (uint16, little-endian)
        parsed_data_.reserved2 = 
          static_cast<uint16_t>(payload_[18]) |
          (static_cast<uint16_t>(payload_[19]) << 8);
        
        has_parsed_data_ = true;
        return true;
      }
    } else {
      reset();
    }
    return false;
  }
  
  reset();
  return false;
}

SensorData* MicolinkParser::get_parsed_data()
{
  if (has_parsed_data_) {
    return &parsed_data_;
  }
  return nullptr;
}

