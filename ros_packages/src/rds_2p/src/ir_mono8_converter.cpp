#include <rclcpp/rclcpp.hpp>
#include <image_transport/image_transport.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <cv_bridge/cv_bridge.h>
#include <opencv2/core.hpp>
#include <algorithm>
#include <cmath>
#include <memory>
#include <string>

class IrMonoConverter : public rclcpp::Node
{
public:
    IrMonoConverter() : Node("ir_mono_converter")
    {
        input_topic_ = this->declare_parameter<std::string>("input_topic", "/camera/ir/image_raw");
        output_topic_ = this->declare_parameter<std::string>("output_topic", "/camera/ir/image_mono");
        gamma_ = this->declare_parameter<double>("gamma", 0.5);
        use_auto_scale_ = this->declare_parameter<bool>("auto_scale", true);
        build_gamma_lut_();

        auto qos = rclcpp::QoS(rclcpp::KeepLast(4));
        qos.best_effort();
        sub_ = this->create_subscription<sensor_msgs::msg::Image>(
            input_topic_, qos, std::bind(&IrMonoConverter::callback, this, std::placeholders::_1));

        RCLCPP_INFO(this->get_logger(), "IR mono16 -> mono8 (gamma=%.2f, auto=%s): %s -> %s [+compressed]",
            gamma_, use_auto_scale_ ? "yes" : "no", input_topic_.c_str(), output_topic_.c_str());
    }

    public:
    void setup_publisher()
    {
        it_ = std::make_shared<image_transport::ImageTransport>(this->shared_from_this());
        pub_ = image_transport::create_publisher(this, output_topic_);
    }

    private:
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr sub_;
    std::shared_ptr<image_transport::ImageTransport> it_;
    image_transport::Publisher pub_;
    bool use_auto_scale_;
    double gamma_;
    std::string input_topic_;
    std::string output_topic_;

    void build_gamma_lut_()
    {
        cv::Mat lut(256, 1, CV_8U);
        for (int i = 0; i < 256; ++i)
        {
            double v = 255.0 * std::pow(static_cast<double>(i) / 255.0, gamma_);
            lut.at<uint8_t>(i) = static_cast<uint8_t>(std::min(255.0, std::max(0.0, v)));
        }
        gamma_lut_ = lut;
    }

    void callback(const sensor_msgs::msg::Image::ConstSharedPtr &msg)
    {
        cv_bridge::CvImageConstPtr shm;
        try
        {
            shm = cv_bridge::toCvShare(msg, "mono16");
        }
        catch (const cv_bridge::Exception &)
        {
            RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 5000,
                "Skip: input not mono16");
            return;
        }

        const cv::Mat &src = shm->image;
        if (src.empty() || src.type() != CV_16UC1)
        {
            return;
        }

        cv::Mat norm8;
        if (use_auto_scale_)
        {
            double minv = 0, maxv = 0;
            cv::minMaxLoc(src, &minv, &maxv);
            const float range = static_cast<float>(std::max(1.0, maxv - minv));
            cv::convertScaleAbs(src, norm8, 255.0f / range, -255.0f * minv / range);
        }
        else
        {
            cv::Mat f;
            src.convertTo(f, CV_32F);
            cv::Mat scaled;
            cv::convertScaleAbs(f, scaled, 255.0 / 65535.0);
            scaled.copyTo(norm8);
        }

        cv::Mat out;
        cv::LUT(norm8, gamma_lut_, out);

        cv_bridge::CvImage img;
        img.header = msg->header;
        img.encoding = "mono8";
        img.image = out;

        pub_.publish(img.toImageMsg());
    }

    cv::Mat gamma_lut_;
};

int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<IrMonoConverter>();
    node->setup_publisher();
    rclcpp::spin(node);
    rclcpp::shutdown();
    return 0;
}
