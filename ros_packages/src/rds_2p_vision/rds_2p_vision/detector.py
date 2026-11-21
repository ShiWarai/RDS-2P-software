"""ONNX YOLOv8 inference on actual RGB images. No ROS or simulator dependencies."""
import ast
import cv2
import numpy as np
import onnxruntime as ort

NAMES = ['tree', 'bush', 'rock', 'flower', 'blue_ball', 'red_ball', 'green_ball']


class YoloDetector:
    def __init__(self, model_path, confidence=.35, threads=2):
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(model_path), options, providers=['CPUExecutionProvider'])
        self.input = self.session.get_inputs()[0]
        self.size = int(self.input.shape[2])
        metadata = self.session.get_modelmeta().custom_metadata_map
        names = ast.literal_eval(metadata.get('names', '{}'))
        labels = list(names.values()) if isinstance(names, dict) else names
        if labels != NAMES:
            raise ValueError(f'Wrong YOLO classes: {labels}; expected {NAMES}')
        self.confidence = confidence

    def detect(self, rgb):
        height, width = rgb.shape[:2]
        scale = min(self.size/width, self.size/height)
        rw, rh = max(1, round(width*scale)), max(1, round(height*scale))
        left, top = (self.size-rw)//2, (self.size-rh)//2
        image = np.full((self.size, self.size, 3), 114, np.uint8)
        image[top:top+rh, left:left+rw] = cv2.resize(rgb, (rw, rh), interpolation=cv2.INTER_NEAREST_EXACT)
        tensor = np.ascontiguousarray(image.transpose(2,0,1)[None], dtype=np.float32) / 255
        output = self.session.run(None, {self.input.name: tensor})[0]
        if output.ndim != 3 or output.shape[1] != 4+len(NAMES):
            raise ValueError(f'Unexpected YOLO output {output.shape}')
        predictions = output[0].T
        classes = predictions[:,4:].argmax(axis=1)
        scores = predictions[np.arange(len(predictions)), classes+4]
        candidates = []
        for i in np.flatnonzero(scores >= self.confidence):
            cx,cy,bw,bh = predictions[i,:4]
            coords = [(cx-bw/2-left)/(rw/width), (cy-bh/2-top)/(rh/height),
                      (cx+bw/2-left)/(rw/width), (cy+bh/2-top)/(rh/height)]
            x1,y1,x2,y2 = [float(np.clip(v,0,limit)) for v,limit in zip(coords,[width,height,width,height])]
            if x2<=x1 or y2<=y1:
                continue
            candidates.append(dict(x1=x1,y1=y1,x2=x2,y2=y2,confidence=float(scores[i]),
                                   classId=int(classes[i]),label=NAMES[int(classes[i])]))
        selected = []
        for box in sorted(candidates,key=lambda b:b['confidence'],reverse=True):
            if any(box['classId']==other['classId'] and iou(box,other)>.45 for other in selected):
                continue
            selected.append(box)
            if len(selected)>=50:
                break
        return selected


def iou(a,b):
    intersection = max(0,min(a['x2'],b['x2'])-max(a['x1'],b['x1'])) * max(0,min(a['y2'],b['y2'])-max(a['y1'],b['y1']))
    union = (a['x2']-a['x1'])*(a['y2']-a['y1'])+(b['x2']-b['x1'])*(b['y2']-b['y1'])-intersection
    return intersection/max(union,1e-9)


def select_blue(detections,width,height):
    boxes = [b for b in detections if b['label']=='blue_ball' and b['confidence']>=.35]
    if not boxes:
        return None
    box = max(boxes,key=lambda b:(b['x2']-b['x1'])*(b['y2']-b['y1']))
    return dict(box,centerX=(box['x1']+box['x2'])/(2*width),centerY=(box['y1']+box['y2'])/(2*height),
                relativeWidth=(box['x2']-box['x1'])/width,width=width,height=height)


def follow_command(target,age_sec,target_width=.18,max_forward=.55,max_yaw=.65,timeout=.7):
    if target is None or age_sec>timeout:
        return [0.,0.,0.]
    error = (target['centerX']-.5)*2
    yaw = 0. if abs(error)<.06 else max(-max_yaw,min(max_yaw,-error*1.4))
    forward = 0. if abs(error)>.55 else max(0.,min(max_forward,(target_width-target['relativeWidth'])*6))*(1-abs(error))
    return [forward,0.,yaw]


def image_to_rgb(msg):
    channels = {'rgb8':3,'bgr8':3,'rgba8':4,'bgra8':4,'mono8':1}.get(msg.encoding)
    if channels is None:
        raise ValueError(f'Unsupported image encoding: {msg.encoding}')
    rows = np.frombuffer(bytes(msg.data),dtype=np.uint8).reshape(msg.height,msg.step)
    image = rows[:,:msg.width*channels].reshape(msg.height,msg.width,channels)
    if msg.encoding=='mono8':
        return np.repeat(image,3,axis=2)
    image = image[:,:,:3]
    return image[:,:,::-1].copy() if msg.encoding.startswith('bgr') else image.copy()
