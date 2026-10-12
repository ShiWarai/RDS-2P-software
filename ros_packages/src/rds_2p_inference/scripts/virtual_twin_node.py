#!/usr/bin/env python3
"""ROS2 simulation node for RDS-2P robot using MuJoCo.

Uses MuJoCo callbacks for clean integration with ROS2 without threading.
This script is part of rds_2p_inference package and runs in headless mode by default.
"""

import sys
import os
import time
import argparse
from etils import epath

import numpy as np
import mujoco

# mujoco_playground — внешняя зависимость в ros_packages/deps (ставится build_for_desktop.sh).
# Основной путь: PYTHONPATH уже содержит deps/ после source install/setup.bash (ament env-hook).
# Резервные пути — для запуска без окружения.
try:
    import mujoco_playground  # noqa: F401
except ImportError:
    _this_dir = os.path.dirname(os.path.realpath(__file__))
    for _parent in (
        os.path.join(_this_dir, '..', '..', '..', '..', 'deps'),  # install/rds_2p_inference/lib/rds_2p_inference/..
        os.path.join(_this_dir, '..', '..', '..', 'deps'),        # src/rds_2p_inference/scripts/..
    ):
        if os.path.isdir(os.path.join(_parent, 'mujoco_playground')):
            sys.path.insert(0, os.path.abspath(_parent))
            break
    else:
        raise ImportError(
            "mujoco_playground не найден в ros_packages/deps (вендорный subset). "
            "Проверь, что deps/mujoco_playground закоммичен, и source install/setup.bash."
        )

# Add parent directory to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from mujoco_playground._src.locomotion.rds2p import robot_constants
from mujoco_playground._src.locomotion.rds2p.base import get_assets

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import JointState, Imu

_HERE = epath.Path(__file__).parent

# Try to import numba for JIT compilation
try:
    from numba import jit
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    # Fallback decorator that does nothing
    def jit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

# Performance tuning constants
SIMULATION_FREQUENCY = 250  # Hz (0.004s timestep) - physics stability
VIEWER_RENDER_RATE = 50  # Hz (smooth visuals, synced with data rate)
ROS_PUBLISH_RATE = 50  # Hz (synced with inference rate)


@jit(nopython=True)
def rotation_matrix_to_quaternion(R):
    """Convert rotation matrix to quaternion [w, x, y, z] - JIT compiled for speed."""
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    
    return np.array([w, x, y, z])


# Global variables for ROS2 integration
ros_node = None
sim_data_cache = {
    'imu_msg': None,
    'joint_states_msg': None
        }


class VirtualTwinNode(Node):
    """ROS2 node for virtual twin simulation."""

    def __init__(self, joint_names: list):
        super().__init__('rds2p_simulation')
        
        self.joint_names = joint_names
        self.joint_commands_received = np.zeros(12, dtype=np.float32)
        
        # Optimized QoS for minimal latency
        # BEST_EFFORT для IMU (высокая частота, допустима потеря данных)
        self.sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        # RELIABLE для joint_states (нужно для robot_state_publisher и других узлов)
        self.joint_states_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        self.command_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        # Subscriber for /joint_commands
        self.joint_commands_sub = self.create_subscription(
            JointState,
            '/joint_commands',
            self.joint_commands_callback,
            self.command_qos
        )
        
        # Publishers for sensor data
        self.imu_pub = self.create_publisher(
            Imu,
            '/imu',
            self.sensor_qos
        )
        
        # Joint states с RELIABLE QoS для совместимости с robot_state_publisher
        self.joint_states_pub = self.create_publisher(
            JointState,
            '/joint_states',
            self.joint_states_qos
        )
        
        self.get_logger().info('Simulation Node started')
        
        # Timer for publishing sensor data at control frequency
        self._publish_timer = self.create_timer(
            1.0 / ROS_PUBLISH_RATE,
            self.publish_timer_callback
        )

    def joint_commands_callback(self, msg: JointState):
        """Callback for /joint_commands messages."""
        if len(msg.position) >= 12:
            self.joint_commands_received = np.array(msg.position[:12], dtype=np.float32)

    def publish_timer_callback(self):
        """Publish sensor data from simulation cache."""
        if sim_data_cache['imu_msg'] is not None:
            # Обновляем временную метку IMU
            sim_data_cache['imu_msg'].header.stamp = self.get_clock().now().to_msg()
            self.imu_pub.publish(sim_data_cache['imu_msg'])
        if sim_data_cache['joint_states_msg'] is not None:
            # Обновляем временную метку joint_states (критично для robot_state_publisher!)
            sim_data_cache['joint_states_msg'].header.stamp = self.get_clock().now().to_msg()
            self.joint_states_pub.publish(sim_data_cache['joint_states_msg'])


def setup_simulation():
    """Setup MuJoCo simulation model and data with control callback."""
    global ros_node
    
    # Load model and data
    model = mujoco.MjModel.from_xml_path(
        robot_constants.FEET_ONLY_FLAT_TERRAIN_XML.as_posix(),
        assets=get_assets(),
    )
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, 0)
    
    ctrl_dt = 0.02  # Control frequency
    sim_dt = 0.004  # Simulation timestep
    n_substeps = int(round(ctrl_dt / sim_dt))
    model.opt.timestep = sim_dt

    # Control callback that reads from ROS2 and writes to ROS2 cache
    def control_callback(model, data):
        global ros_node, sim_data_cache
        
        # Read joint commands from ROS2
        if ros_node is not None:
            data.ctrl[:] = ros_node.joint_commands_received
        
        # Extract and cache sensor data at control frequency (50 Hz)
        gyro = data.sensor("base_link_gyro").data
        imu_xmat = data.site_xmat[model.site("base_link_site").id].reshape(3, 3)
        
        # Convert rotation matrix to quaternion (JIT compiled)
        quat = rotation_matrix_to_quaternion(imu_xmat)
        
        # Compute gravity vector
        g = 9.81
        gravity_vec = imu_xmat[2, :] * g
        
        # Create IMU message
        imu_msg = Imu()
        imu_msg.header.frame_id = 'base_link'
        imu_msg.angular_velocity.x = float(gyro[0])
        imu_msg.angular_velocity.y = float(gyro[1])
        imu_msg.angular_velocity.z = float(gyro[2])
        imu_msg.orientation.w = float(quat[0])
        imu_msg.orientation.x = float(quat[1])
        imu_msg.orientation.y = float(quat[2])
        imu_msg.orientation.z = float(quat[3])
        imu_msg.linear_acceleration.x = float(gravity_vec[0])
        imu_msg.linear_acceleration.y = float(gravity_vec[1])
        imu_msg.linear_acceleration.z = float(gravity_vec[2])
        
        # Create joint states message
        joint_states_msg = JointState()
        joint_states_msg.header.frame_id = 'base_link'
        if ros_node is not None:
            joint_states_msg.name = ros_node.joint_names
        joint_states_msg.position = data.qpos[7:].tolist()  # Skip 7-DOF free joint
        joint_states_msg.velocity = data.qvel[6:].tolist()
        joint_states_msg.effort = []
        
        # Update cache (ROS2 timer will publish)
        sim_data_cache['imu_msg'] = imu_msg
        sim_data_cache['joint_states_msg'] = joint_states_msg
    
    mujoco.set_mjcb_control(control_callback)
    
    return model, data


def run_headless_simulation(model, data):
    """Run MuJoCo simulation in headless mode (no graphics)."""
    sim_dt = model.opt.timestep
    
    print(f"Running headless simulation at {1.0/sim_dt:.0f} Hz")
    print("Press Ctrl+C to exit.")
    
    try:
        while True:
            # Step simulation forward
            mujoco.mj_step(model, data)
            time.sleep(sim_dt)  # Real-time simulation
    except KeyboardInterrupt:
        print("\nSimulation stopped.")





def create_simulation_loader():
    """Create simulation loader callback for viewer.launch()."""
    def load_callback(model=None, data=None):
        return setup_simulation()
    return load_callback


def get_joint_names():
    """Get joint names from the robot model."""
    model = mujoco.MjModel.from_xml_path(
        robot_constants.FEET_ONLY_FLAT_TERRAIN_XML.as_posix(),
        assets=get_assets(),
    )
    
    # Get joint names from model
    joint_names = []
    for i in range(1, model.njnt):  # Start from 1 to skip freejoint
        joint_names.append(model.joint(i).name)
    
    return joint_names


def main():
    global ros_node
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='ROS2 MuJoCo simulation node for RDS-2P robot')
    parser.add_argument('--headless', action='store_true', default=False,
                        help='Run simulation without graphics (headless mode)')
    args = parser.parse_args()
    
    # Initialize ROS2
    rclpy.init()
    
    node = None
    
    try:
        # Get joint names
        print("Getting joint names from model...")
        joint_names = get_joint_names()
        
        # Create ROS node
        print("Creating ROS2 simulation node...")
        node = VirtualTwinNode(joint_names)
        ros_node = node
        
        # Start ROS2 in a separate thread (non-blocking)
        print("Starting ROS2 in background thread...")
        print(f"Subscribing to: /joint_commands")
        print(f"Publishing to: /imu, /joint_states at {ROS_PUBLISH_RATE} Hz")
        
        def ros_spinner():
            rclpy.spin(node)
        
        import threading
        ros_thread = threading.Thread(target=ros_spinner, daemon=True)
        ros_thread.start()
        
        # Give ROS2 a moment to initialize
        time.sleep(0.1)

        print(f"Headless mode: {args.headless}")
        
        if args.headless:
            # Run headless simulation
            print("Starting MuJoCo simulation in headless mode...")
            model, data = setup_simulation()
            run_headless_simulation(model, data)
        else:
            import mujoco.viewer as viewer

            # Start MuJoCo simulation with viewer
            print("Starting MuJoCo simulation with viewer...")
            print("Close viewer window or press Ctrl+C to exit.")
            
            loader = create_simulation_loader()
            viewer.launch(loader=loader)
        
    except KeyboardInterrupt:
        print("\n\nCtrl+C pressed, shutting down...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        print("\nCleaning up...")
        if node:
            try:
                node.destroy_node()
            except:
                pass
        try:
            rclpy.shutdown()
        except:
            pass


if __name__ == "__main__":
    sys.exit(main())



