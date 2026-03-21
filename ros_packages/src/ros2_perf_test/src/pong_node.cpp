#include <rclcpp/rclcpp.hpp>
#include <rclcpp/qos.hpp>
#include <ftservo_ros/msg/motor_commands.hpp>
#include <ftservo_ros/msg/motor_states.hpp>
#include <memory>
#include <chrono>
#include <thread>
#include <optional>

class PongNode : public rclcpp::Node {
public:
    PongNode() : Node("pong_node") {
        // Declare parameters
        declare_parameter("processing_delay_us", 0);  // Default 0 microseconds
        declare_parameter("publish_rate", 50.0);  // Default 50 Hz
        declare_parameter("use_timer_publish", true);  // Default: publish via timer
        
        processing_delay_us_ = get_parameter("processing_delay_us").as_int();
        double publish_rate = get_parameter("publish_rate").as_double();
        use_timer_publish_ = get_parameter("use_timer_publish").as_bool();
        
        RCLCPP_INFO(get_logger(), "Pong node started with processing delay: %d microseconds per command, "
                    "publish mode: %s, publish rate: %.1f Hz", 
                    processing_delay_us_, 
                    use_timer_publish_ ? "timer" : "callback",
                    publish_rate);
        
        // Create subscriber for /ping topic
        auto sensor_qos = rclcpp::SensorDataQoS();
        sensor_qos.keep_last(1);
        
        ping_sub_ = create_subscription<ftservo_ros::msg::MotorCommands>(
            "/ping", sensor_qos,
            std::bind(&PongNode::pingCallback, this, std::placeholders::_1));
        
        // Create publisher for /pong topic
        pong_pub_ = create_publisher<ftservo_ros::msg::MotorStates>(
            "/pong", sensor_qos);
        
        // Create timer for periodic publishing only if timer mode is enabled
        if (use_timer_publish_) {
            publish_timer_ = create_wall_timer(
                std::chrono::duration<double>(1.0 / publish_rate),
                std::bind(&PongNode::publishTimerCallback, this)
            );
        }
    }

private:
    ftservo_ros::msg::MotorState processCommand(
        const ftservo_ros::msg::MotorCommand& cmd) {
        
        ftservo_ros::msg::MotorState state;
        state.motor_id = cmd.motor_id;
        state.position = cmd.target_position;      // target_position → position
        state.velocity = cmd.target_velocity;      // target_velocity → velocity
        state.load = 0.0;                          // Default load
        state.enabled = true;                      // Default enabled
        state.error = false;                       // Default no error

        // Simulate processing delay per command
        std::this_thread::sleep_for(std::chrono::microseconds(processing_delay_us_));
        
        return state;
    }
    
    ftservo_ros::msg::MotorStates processCommands(
        const ftservo_ros::msg::MotorCommands::SharedPtr commands_msg) {
        
        auto states_msg = ftservo_ros::msg::MotorStates();
        
        // Preserve header frame_id for identification
        states_msg.header.stamp = this->now();
        states_msg.header.frame_id = commands_msg->header.frame_id;
        
        // Process each motor command
        for (const auto& cmd : commands_msg->commands) {
            auto state = processCommand(cmd);
            states_msg.states.push_back(state);
        }
        
        return states_msg;
    }
    
    void pingCallback(const ftservo_ros::msg::MotorCommands::SharedPtr msg) {
        // Process commands array to states array (with processing delay)
        auto states_msg = processCommands(msg);
        
        if (use_timer_publish_) {
            // Store result for publication by timer
            pending_states_msg_ = states_msg;
        } else {
            // Publish immediately in callback mode
            pong_pub_->publish(states_msg);
        }
    }
    
    void publishTimerCallback() {
        // Publish latest processed states if available
        if (pending_states_msg_) {
            // Update timestamp to current time before publishing
            pending_states_msg_->header.stamp = this->now();
            pong_pub_->publish(*pending_states_msg_);
        }
    }
    
    rclcpp::Subscription<ftservo_ros::msg::MotorCommands>::SharedPtr ping_sub_;
    rclcpp::Publisher<ftservo_ros::msg::MotorStates>::SharedPtr pong_pub_;
    rclcpp::TimerBase::SharedPtr publish_timer_;
    
    int processing_delay_us_;  // Processing delay per command in microseconds
    bool use_timer_publish_;  // If true, publish via timer; if false, publish in callback
    std::optional<ftservo_ros::msg::MotorStates> pending_states_msg_;  // Latest processed states to publish (timer mode only)
};

int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    
    auto node = std::make_shared<PongNode>();
    
    rclcpp::spin(node);
    
    rclcpp::shutdown();
    return 0;
}

