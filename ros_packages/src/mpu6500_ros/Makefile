# Makefile for MPU6500 ROS package
# This Makefile provides convenient targets for building and testing

.PHONY: all build clean test install help

# Default target
all: build

# Build the package
build:
	@echo "Building MPU6500 ROS package..."
	colcon build --packages-select mpu6500_ros

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	colcon build --packages-select mpu6500_ros --cmake-clean-cache
	rm -rf build/ install/ log/

# Run tests
test: build
	@echo "Running tests..."
	colcon test --packages-select mpu6500_ros

# Install the package
install: build
	@echo "Installing package..."
	colcon build --packages-select mpu6500_ros --install

# Source the workspace
source:
	@echo "Sourcing workspace..."
	@echo "Run: source install/setup.bash"

# Check I2C devices
check-i2c:
	@echo "Checking I2C devices..."
	python3 scripts/check_i2c.py

# Run the IMU node
run:
	@echo "Running MPU6500 IMU node..."
	ros2 launch mpu6500_ros mpu6500_imu.launch.py

# Run test launch
test-run:
	@echo "Running test launch..."
	ros2 launch mpu6500_ros test_imu.launch.py

# Check topic
check-topic:
	@echo "Checking /imu topic..."
	ros2 topic list | grep imu || echo "No IMU topic found"
	ros2 topic info /imu 2>/dev/null || echo "Topic /imu not available"

# Echo IMU data
echo-imu:
	@echo "Echoing IMU data (press Ctrl+C to stop)..."
	ros2 topic echo /imu

# Show help
help:
	@echo "Available targets:"
	@echo "  build      - Build the package"
	@echo "  clean      - Clean build artifacts"
	@echo "  test       - Run tests"
	@echo "  install    - Install the package"
	@echo "  source     - Show source command"
	@echo "  check-i2c  - Check I2C devices"
	@echo "  run        - Run the IMU node"
	@echo "  test-run   - Run test launch"
	@echo "  check-topic- Check IMU topic"
	@echo "  echo-imu   - Echo IMU data"
	@echo "  help       - Show this help"

# Development targets
dev-build:
	@echo "Building in development mode..."
	colcon build --packages-select mpu6500_ros --cmake-args -DCMAKE_BUILD_TYPE=Debug

dev-run: dev-build
	@echo "Running in development mode..."
	ros2 launch mpu6500_ros mpu6500_imu.launch.py

# Quick build and run
quick: build run

# Quick test
quick-test: build test-run
