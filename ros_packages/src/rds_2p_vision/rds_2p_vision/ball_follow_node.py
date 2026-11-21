"""Real camera -> YOLO -> /cmd_vel/ball_follow; enable heartbeat is mandatory."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import cv2

import rclpy
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from sensor_msgs.msg import Image, CompressedImage
from std_msgs.msg import Bool, String

from .detector import YoloDetector, image_to_rgb, select_blue, follow_command


class BallFollowNode(Node):
    def __init__(self):
        super().__init__('ball_follow')
        defaults = dict(model_path=str(Path(get_package_share_directory('rds_2p_vision'))/'models/yolov8n_balls.onnx'),
                        image_topic='/camera/color/image_raw',cmd_topic='/cmd_vel/ball_follow',
                        enable_topic='/ball_follow/enable',status_topic='/ball_follow/status',confidence=.35,
                        frame_timeout_sec=.7,heartbeat_timeout_sec=.7,target_width=.18,max_forward=.55,max_yaw=.65,
                        inference_threads=2)
        for key,value in defaults.items():
            self.declare_parameter(key,value)
        self.cfg = {key:self.get_parameter(key).value for key in defaults}
        self.detector = YoloDetector(self.cfg['model_path'],self.cfg['confidence'],self.cfg['inference_threads'])
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._future = None
        self._enabled = False
        self._last_enable = -float('inf')
        self._captured_at = -float('inf')
        self._target = None
        self._detections = []
        self._error = None
        self._next_status = 0
        self._inference_ms = 0
        self._manual_source = ''
        self.pub = self.create_publisher(Twist,self.cfg['cmd_topic'],1)
        self.status = self.create_publisher(String,self.cfg['status_topic'],1)
        self.preview = self.create_publisher(CompressedImage,'/ball_follow/image/compressed',1)
        self.create_subscription(Image,self.cfg['image_topic'],self.on_image,qos_profile_sensor_data)
        self.create_subscription(Bool,self.cfg['enable_topic'],self.on_enable,1)
        qos = QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String,'/cmd_vel_mux/state',self.on_mux,qos)
        self.create_timer(.05,self.tick)
        self.get_logger().info(f"YOLO ready: {self.cfg['image_topic']} -> {self.cfg['cmd_topic']}; following disabled")

    def on_enable(self,msg):
        self._last_enable = time.monotonic()
        if msg.data and not self._manual_source:
            self._enabled = True
        else:
            self.disable()

    def on_mux(self,msg):
        try:
            state = json.loads(msg.data)
        except (ValueError,TypeError):
            return
        source = state.get('selected_source','')
        self._manual_source = source if source and source!='ball_follow' else ''
        if self._enabled and self._manual_source:
            self.disable()

    def disable(self):
        if self._enabled:
            self.pub.publish(Twist())
        self._enabled = False

    def on_image(self,msg):
        if self._future is not None:
            return
        # Include transport delay in the freshness deadline when the camera stamps frames.
        stamp = msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
        age = max(0.,self.get_clock().now().nanoseconds*1e-9-stamp) if stamp else 0.
        if age>self.cfg['frame_timeout_sec']:
            return
        received = time.monotonic()-age
        self._future = self._pool.submit(self.process_image,msg,received)

    def process_image(self,msg,received):
        started = time.monotonic()
        rgb = image_to_rgb(msg)
        boxes = self.detector.detect(rgb)
        if self.preview.get_subscription_count():
            bgr=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
            for box in boxes:
                color=(255,100,20) if box['label']=='blue_ball' else (50,210,50)
                a=(int(box['x1']),int(box['y1']));b=(int(box['x2']),int(box['y2']))
                cv2.rectangle(bgr,a,b,color,2)
                cv2.putText(bgr,f"{box['label']} {box['confidence']:.2f}",(a[0],max(15,a[1]-5)),
                            cv2.FONT_HERSHEY_SIMPLEX,.45,color,1)
            ok,encoded=cv2.imencode('.jpg',bgr,[cv2.IMWRITE_JPEG_QUALITY,75])
            if ok:
                preview=CompressedImage();preview.header=msg.header;preview.format='jpeg';preview.data=encoded.tobytes()
                self.preview.publish(preview)
        return boxes,select_blue(boxes,msg.width,msg.height),received,(time.monotonic()-started)*1000

    def tick(self):
        now = time.monotonic()
        if self._future is not None and self._future.done():
            try:
                self._detections,self._target,self._captured_at,self._inference_ms = self._future.result()
                self._error = None
            except Exception as error:
                self._target = None
                self._error = str(error)
            self._future = None
        if now-self._last_enable>self.cfg['heartbeat_timeout_sec']:
            self.disable()
        age = now-self._captured_at
        if self._enabled:
            cmd = follow_command(self._target,age,self.cfg['target_width'],self.cfg['max_forward'],
                                 self.cfg['max_yaw'],self.cfg['frame_timeout_sec'])
            twist = Twist();twist.linear.x=cmd[0];twist.angular.z=cmd[2]
            self.pub.publish(twist)
        if now>=self._next_status:
            self._next_status=now+.2
            msg=String();msg.data=json.dumps(dict(ready=True,enabled=self._enabled,
                target=self._target if age<=self.cfg['frame_timeout_sec'] else None,
                detections=self._detections if age<=self.cfg['frame_timeout_sec'] else [],
                age_sec=age if age<float('inf') else None,inference_ms=self._inference_ms,
                error=self._error,manual_source=self._manual_source))
            self.status.publish(msg)

    def destroy_node(self):
        self.disable()
        self._pool.shutdown(wait=True,cancel_futures=True)
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node=BallFollowNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
