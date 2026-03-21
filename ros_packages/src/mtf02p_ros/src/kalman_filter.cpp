#include "mtf02p_ros/kalman_filter.hpp"
#include <cmath>

KalmanFilter::KalmanFilter(double process_variance, double measurement_variance)
  : process_variance_(process_variance)
  , measurement_variance_(measurement_variance)
  , estimate_(0.0)
  , error_covariance_(1.0)
{
}

double KalmanFilter::update(double measurement)
{
  // Prediction
  double predicted_estimate = estimate_;
  double predicted_error_covariance = error_covariance_ + process_variance_;
  
  // Update
  double kalman_gain = predicted_error_covariance / 
                       (predicted_error_covariance + measurement_variance_);
  
  estimate_ = predicted_estimate + kalman_gain * (measurement - predicted_estimate);
  error_covariance_ = (1.0 - kalman_gain) * predicted_error_covariance;
  
  return estimate_;
}

double KalmanFilter::get_value() const
{
  return estimate_;
}

void KalmanFilter::reset()
{
  estimate_ = 0.0;
  error_covariance_ = 1.0;
}

