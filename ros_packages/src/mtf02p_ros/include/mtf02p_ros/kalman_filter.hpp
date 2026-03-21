#ifndef MTF02P_ROS__KALMAN_FILTER_HPP_
#define MTF02P_ROS__KALMAN_FILTER_HPP_

class KalmanFilter {
public:
  KalmanFilter(double process_variance = 0.01, double measurement_variance = 0.1);
  
  double update(double measurement);
  double get_value() const;
  void reset();

private:
  double process_variance_;
  double measurement_variance_;
  double estimate_;
  double error_covariance_;
};

#endif  // MTF02P_ROS__KALMAN_FILTER_HPP_

