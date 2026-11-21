import unittest
from types import SimpleNamespace

import numpy as np
from rds_2p_vision.detector import YoloDetector, follow_command, image_to_rgb, select_blue, non_maximum_suppression


class DetectorContractTests(unittest.TestCase):
    def test_bush_ball_duplicate_labels_keep_stronger_class(self):
        green=dict(classId=6,label='green_ball',confidence=.92,x1=483,y1=250,x2=519,y2=284)
        false_bush=dict(classId=1,label='bush',confidence=.49,x1=482,y1=248,x2=521,y2=283)
        self.assertEqual(non_maximum_suppression([false_bush,green]),[green])
        bush=dict(false_bush,confidence=.95)
        self.assertEqual(non_maximum_suppression([green,bush]),[bush])
        nearby_bush=dict(bush,x1=510,x2=590)
        self.assertEqual(len(non_maximum_suppression([nearby_bush,green])),2)

    def test_native_rectangular_input_preserves_every_pixel(self):
        tensors = []
        detector = YoloDetector.__new__(YoloDetector)
        detector.width, detector.height = 640, 480
        detector.input = SimpleNamespace(name='images')
        detector.confidence = .35
        detector.session = SimpleNamespace(run=lambda _, feeds: (
            tensors.append(feeds['images']) or [np.zeros((1,11,1),np.float32)]))
        image = np.random.default_rng(17).integers(0,256,(480,640,3),dtype=np.uint8)
        self.assertEqual(detector.detect(image), [])
        np.testing.assert_array_equal(tensors[0],image.transpose(2,0,1)[None].astype(np.float32)/255)

    def test_neural_target_only(self):
        blue=dict(label='blue_ball',confidence=.9,x1=280,y1=200,x2=360,y2=280)
        self.assertIsNone(select_blue([dict(blue,label='red_ball')],640,480))
        self.assertIsNone(select_blue([dict(blue,confidence=.1)],640,480))
        target=select_blue([blue],640,480)
        self.assertEqual(target['centerX'],.5)
        self.assertGreater(follow_command(target,.1)[0],0)
        self.assertLess(follow_command(dict(target,centerX=.7),.1)[2],0)
        self.assertGreater(follow_command(dict(target,centerX=.3),.1)[2],0)

    def test_stop_for_lost_stale_or_close_target(self):
        target=dict(centerX=.5,relativeWidth=.1)
        self.assertEqual(follow_command(None,.1),[0.,0.,0.])
        self.assertEqual(follow_command(target,.701),[0.,0.,0.])
        self.assertEqual(follow_command(dict(target,relativeWidth=.2),.1),[0.,0.,0.])

    def test_actual_ros_image_channel_order_and_padding(self):
        # Two BGR pixels plus two padding bytes per row.
        msg=SimpleNamespace(encoding='bgr8',width=2,height=1,step=8,data=bytes([255,0,0,0,0,255,77,88]))
        rgb=image_to_rgb(msg)
        np.testing.assert_array_equal(rgb,np.array([[[0,0,255],[255,0,0]]],dtype=np.uint8))
        msg.encoding='mono8';msg.step=3;msg.data=bytes([40,80,99])
        np.testing.assert_array_equal(image_to_rgb(msg),[[[40]*3,[80]*3]])
        msg.encoding='yuv422'
        with self.assertRaises(ValueError):
            image_to_rgb(msg)


if __name__=='__main__':
    unittest.main()
