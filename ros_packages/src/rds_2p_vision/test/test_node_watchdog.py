"""Exercise the ROS callback contract using message/transport stubs, without a robot."""
import importlib
import json
import sys
import types
import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import patch


class Twist:
    def __init__(self):
        self.linear=SimpleNamespace(x=0.,y=0.,z=0.)
        self.angular=SimpleNamespace(x=0.,y=0.,z=0.)


def stub_module(**values):
    module=types.ModuleType('stub')
    module.__dict__.update(values)
    return module


stubs={
    'rclpy':stub_module(), 'rclpy.node':stub_module(Node=object),
    'rclpy.qos':stub_module(qos_profile_sensor_data=None,QoSProfile=object,
                           DurabilityPolicy=SimpleNamespace(TRANSIENT_LOCAL=1)),
    'ament_index_python':stub_module(),
    'ament_index_python.packages':stub_module(get_package_share_directory=lambda _:'.'),
    'geometry_msgs':stub_module(),'geometry_msgs.msg':stub_module(Twist=Twist),
    'sensor_msgs':stub_module(),'sensor_msgs.msg':stub_module(Image=object,CompressedImage=object),
    'std_msgs':stub_module(),'std_msgs.msg':stub_module(Bool=object,String=SimpleNamespace),
}
with patch.dict(sys.modules,stubs):
    module=importlib.import_module('rds_2p_vision.ball_follow_node')


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.sent=[]
        self.node=module.BallFollowNode.__new__(module.BallFollowNode)
        self.node.cfg=dict(heartbeat_timeout_sec=.7,frame_timeout_sec=.7,
                           target_width=.18,max_forward=.55,max_yaw=.65)
        self.node._enabled=False;self.node._last_enable=-float('inf')
        self.node._captured_at=99.9;self.node._future=None
        self.node._target=dict(centerX=.65,relativeWidth=.08)
        self.node._detections=[];self.node._error=None
        self.node._next_status=float('inf');self.node._manual_source=''
        self.node.pub=SimpleNamespace(publish=self.sent.append)

    def tick_at(self,now):
        with patch.object(module.time,'monotonic',return_value=now):
            self.node.tick()

    def enable_at(self,now):
        with patch.object(module.time,'monotonic',return_value=now):
            self.node.on_enable(SimpleNamespace(data=True))

    def test_disabled_until_heartbeat_then_expires(self):
        self.tick_at(100)
        self.assertFalse(self.sent)
        self.enable_at(100);self.tick_at(100)
        self.assertGreater(self.sent[-1].linear.x,0)
        self.assertLess(self.sent[-1].angular.z,0)
        self.tick_at(100.71)
        self.assertFalse(self.node._enabled)
        self.assertEqual(self.sent[-1].linear.x,0)
        self.assertEqual(self.sent[-1].angular.z,0)

    def test_slow_inference_cannot_block_stale_frame_stop(self):
        self.enable_at(100)
        self.node._future=Future()  # unfinished inference
        self.node._captured_at=99.
        self.tick_at(100)
        self.assertEqual(self.sent[-1].linear.x,0)
        self.assertEqual(self.sent[-1].angular.z,0)

    def test_manual_mux_command_disables_following(self):
        self.enable_at(100)
        self.node.on_mux(SimpleNamespace(data=json.dumps({'selected_source':'joy'})))
        self.assertFalse(self.node._enabled)
        self.assertEqual(self.sent[-1].linear.x,0)
        self.enable_at(100.1)
        self.assertFalse(self.node._enabled)

    def test_inference_error_clears_target_and_stops(self):
        self.enable_at(100)
        self.node._future=Future();self.node._future.set_exception(RuntimeError('model failed'))
        self.tick_at(100)
        self.assertIsNone(self.node._target)
        self.assertEqual(self.node._error,'model failed')
        self.assertEqual(self.sent[-1].linear.x,0)


if __name__=='__main__':
    unittest.main()
