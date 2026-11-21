#include <rclcpp/rclcpp.hpp>
#include <rclcpp/qos.hpp>
#include <ftservo_ros/msg/motor_commands.hpp>
#include <ftservo_ros/msg/motor_states.hpp>
#include <chrono>
#include <map>
#include <string>
#include <vector>
#include <algorithm>
#include <numeric>
#include <cmath>

class PingNode : public rclcpp::Node {
public:
    PingNode() : Node("ping_node"), sequence_counter_(0), sent_count_(0), finished_(false), stats_printed_(false) {
        // Declare parameters
        declare_parameter("publish_rate", 50.0);
        declare_parameter("max_measurements", 100);
        
        double publish_rate = get_parameter("publish_rate").as_double();
        max_measurements_ = get_parameter("max_measurements").as_int();
        
        RCLCPP_INFO(get_logger(), "Ping node started with publish rate: %.1f Hz, max measurements: %d", 
                    publish_rate, max_measurements_);
        
        // Create publisher for /ping topic
        auto sensor_qos = rclcpp::SensorDataQoS();
        sensor_qos.keep_last(1);
        
        ping_pub_ = create_publisher<ftservo_ros::msg::MotorCommands>(
            "/ping", sensor_qos);
        
        // Create subscriber for /pong topic
        pong_sub_ = create_subscription<ftservo_ros::msg::MotorStates>(
            "/pong", sensor_qos,
            std::bind(&PingNode::pongCallback, this, std::placeholders::_1));
        
        // Create timer for periodic publishing
        timer_ = create_wall_timer(
            std::chrono::duration<double>(1.0 / publish_rate),
            std::bind(&PingNode::publishPing, this)
        );
    }

private:
    void publishPing() {
        // Check if we've reached the limit
        if (sent_count_ >= max_measurements_) {
            if (!finished_) {
                finished_ = true;
                timer_->cancel();
                RCLCPP_INFO(get_logger(), "Reached maximum measurements limit (%d). Waiting for remaining responses...", max_measurements_);
                
                // Create a timer to wait for remaining responses, then print statistics and shutdown
                wait_timer_ = create_wall_timer(
                    std::chrono::seconds(2),  // Wait 2 seconds for remaining responses
                    [this]() {
                        if (!stats_printed_) {
                            printStatistics();
                            stats_printed_ = true;
                        }
                        rclcpp::shutdown();
                    }
                );
            }
            return;
        }
        
        auto msg = ftservo_ros::msg::MotorCommands();
        
        // Set header with unique sequence identifier
        msg.header.stamp = this->now();
        msg.header.frame_id = "seq_" + std::to_string(sequence_counter_);
        
        // Create 12 motor commands with test values
        for (uint8_t i = 0; i < 12; ++i) {
            ftservo_ros::msg::MotorCommand cmd;
            cmd.motor_id = i;
            cmd.target_position = 0.5 * static_cast<double>(i);  // Test position
            cmd.target_velocity = 1.0 + 0.1 * static_cast<double>(i);  // Test velocity
            cmd.target_acceleration = 0.5 + 0.05 * static_cast<double>(i);  // Test acceleration
            msg.commands.push_back(cmd);
        }
        
        // Record send time with sequence number
        auto send_time = std::chrono::steady_clock::now();
        send_times_[sequence_counter_] = send_time;
        
        // Publish message
        ping_pub_->publish(msg);
        
        // Increment counters
        sequence_counter_++;
        sent_count_++;
    }
    
    void pongCallback(const ftservo_ros::msg::MotorStates::SharedPtr msg) {
        // Extract sequence number from frame_id
        std::string frame_id = msg->header.frame_id;
        if (frame_id.find("seq_") == 0) {
            std::string seq_str = frame_id.substr(4);  // Remove "seq_" prefix
            try {
                uint64_t seq = std::stoull(seq_str);
                
                // Find corresponding send time
                auto it = send_times_.find(seq);
                if (it != send_times_.end()) {
                    auto recv_time = std::chrono::steady_clock::now();
                    auto duration = std::chrono::duration_cast<std::chrono::microseconds>(
                        recv_time - it->second);
                    double latency_ms = duration.count() / 1000.0;
                    
                    // Store latency for statistics
                    latencies_.push_back(latency_ms);
                    
                    RCLCPP_INFO(get_logger(), 
                        "Latency for sequence %lu: %.3f ms", seq, latency_ms);
                    
                    // Remove processed entry to prevent memory growth
                    send_times_.erase(it);
                    
                    // Check if we've received all responses and finished sending
                    // Statistics will be printed by wait_timer_ if active
                    if (finished_ && send_times_.empty() && wait_timer_ && !stats_printed_) {
                        wait_timer_->cancel();
                        printStatistics();
                        stats_printed_ = true;
                        rclcpp::shutdown();
                    }
                } else {
                    RCLCPP_WARN(get_logger(), 
                        "Received pong for unknown sequence: %lu", seq);
                }
            } catch (const std::exception& e) {
                RCLCPP_WARN(get_logger(), 
                    "Failed to parse sequence from frame_id: %s", frame_id.c_str());
            }
        } else {
            RCLCPP_WARN(get_logger(), 
                "Received pong with invalid frame_id format: %s", frame_id.c_str());
        }
    }
    
    void printStatistics() {
        if (latencies_.empty()) {
            RCLCPP_WARN(get_logger(), "No latency measurements collected.");
            return;
        }
        
        // Calculate statistics
        double min_latency = *std::min_element(latencies_.begin(), latencies_.end());
        double max_latency = *std::max_element(latencies_.begin(), latencies_.end());
        double avg_latency = std::accumulate(latencies_.begin(), latencies_.end(), 0.0) / latencies_.size();
        
        // Calculate median
        std::vector<double> sorted_latencies = latencies_;
        std::sort(sorted_latencies.begin(), sorted_latencies.end());
        double median_latency = sorted_latencies.size() % 2 == 0
            ? (sorted_latencies[sorted_latencies.size() / 2 - 1] + sorted_latencies[sorted_latencies.size() / 2]) / 2.0
            : sorted_latencies[sorted_latencies.size() / 2];
        
        // Calculate standard deviation
        double variance = 0.0;
        for (double latency : latencies_) {
            variance += (latency - avg_latency) * (latency - avg_latency);
        }
        double std_dev = std::sqrt(variance / latencies_.size());
        
        // Print statistics
        RCLCPP_INFO(get_logger(), "==========================================");
        RCLCPP_INFO(get_logger(), "Latency Statistics:");
        RCLCPP_INFO(get_logger(), "  Total measurements: %zu", latencies_.size());
        RCLCPP_INFO(get_logger(), "  Min latency:       %.3f ms", min_latency);
        RCLCPP_INFO(get_logger(), "  Max latency:       %.3f ms", max_latency);
        RCLCPP_INFO(get_logger(), "  Average latency:   %.3f ms", avg_latency);
        RCLCPP_INFO(get_logger(), "  Median latency:    %.3f ms", median_latency);
        RCLCPP_INFO(get_logger(), "  Std deviation:     %.3f ms", std_dev);
        RCLCPP_INFO(get_logger(), "==========================================");
    }
    
    rclcpp::Publisher<ftservo_ros::msg::MotorCommands>::SharedPtr ping_pub_;
    rclcpp::Subscription<ftservo_ros::msg::MotorStates>::SharedPtr pong_sub_;
    rclcpp::TimerBase::SharedPtr timer_;
    rclcpp::TimerBase::SharedPtr wait_timer_;
    
    uint64_t sequence_counter_;
    int max_measurements_;
    int sent_count_;
    bool finished_;
    bool stats_printed_;
    std::map<uint64_t, std::chrono::steady_clock::time_point> send_times_;
    std::vector<double> latencies_;
};

int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    
    auto node = std::make_shared<PingNode>();
    
    rclcpp::spin(node);
    
    rclcpp::shutdown();
    return 0;
}

