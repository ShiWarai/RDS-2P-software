#!/usr/bin/env python3
"""Recover the existing fused YOLOv8n ONNX weights, extend 4 -> 7 classes, train.

The original .pt checkpoint is unavailable. Every fused convolution is restored
with identity BatchNorm; parity against the source ONNX is verified before training.
BN statistics stay frozen because the original running statistics were fused away.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
import onnx
from onnx import numpy_helper
import onnxruntime as ort
import torch
import yaml
from ultralytics import YOLO
from ultralytics.models.yolo.detect import DetectionTrainer
from ultralytics.nn.modules import Conv
from ultralytics.nn.tasks import DetectionModel

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['tree','bush','rock','flower','blue_ball','red_ball','green_ball']


def restore(source):
    initializers = {item.name:torch.from_numpy(numpy_helper.to_array(item).copy())
                    for item in onnx.load(str(source)).graph.initializer}
    model = DetectionModel('yolov8n.yaml',nc=4,verbose=False)
    # The source retained COCO's 80-wide classification branches after fine-tuning.
    head=model.model[-1]
    hidden=int(initializers['model.22.cv3.0.0.conv.weight'].shape[0])
    head.cv3=torch.nn.ModuleList(torch.nn.Sequential(Conv(int(branch[0].conv.in_channels),hidden,3),
        Conv(hidden,hidden,3),torch.nn.Conv2d(hidden,4,1)) for branch in head.cv3)
    copied = 0
    with torch.no_grad():
        for name,module in model.named_modules():
            if isinstance(module,torch.nn.Conv2d):
                weight = initializers.get(name+'.weight')
                if weight is None or weight.shape!=module.weight.shape:
                    raise ValueError(f'Cannot restore {name}: ONNX architecture mismatch')
                module.weight.copy_(weight);copied+=1
                if module.bias is not None:
                    module.bias.copy_(initializers[name+'.bias'])
            if isinstance(module,Conv) and hasattr(module,'bn'):
                module.bn.running_mean.zero_();module.bn.running_var.fill_(1)
                module.bn.weight.fill_(math.sqrt(1+module.bn.eps))
                module.bn.bias.copy_(initializers[name+'.conv.bias'])
    model.names=dict(enumerate(NAMES[:4]))
    model.eval()
    print(f'Restored {copied} convolutions from the existing ONNX',flush=True)
    return model


class FrozenBNTrainer(DetectionTrainer):
    def get_model(self,cfg=None,weights=None,verbose=True):
        model=DetectionModel(cfg,nc=self.data['nc'],ch=3,verbose=verbose)
        if weights:
            model.load(weights)
            # Retain the four learned scenery classifier rows when adding classes.
            with torch.no_grad():
                for old,new in zip(weights.model[-1].cv3,model.model[-1].cv3):
                    new[-1].weight[:4].copy_(old[-1].weight[:4])
                    new[-1].bias[:4].copy_(old[-1].bias[:4])
        return model

    def _model_train(self):
        super()._model_train()
        for module in self.model.modules():
            if isinstance(module,torch.nn.BatchNorm2d):
                module.eval()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--epochs',type=int,default=35)
    parser.add_argument('--batch',type=int,default=16)
    parser.add_argument('--threads',type=int,default=6)
    parser.add_argument('--resume',type=Path)
    parser.add_argument('--data',type=Path,default=ROOT/'.test/vision_training/dataset/data.yaml')
    args=parser.parse_args()
    torch.set_num_threads(args.threads)
    source=ROOT/'models/vision/yolov8n_final.onnx'
    dataset=args.data.resolve()
    names=yaml.safe_load(dataset.read_text(encoding='utf-8')).get('names',[])
    if isinstance(names,dict):
        names=[names[key] for key in sorted(names,key=int)]
    if names!=NAMES:
        raise ValueError(f'Dataset must use this class order: {NAMES}; got {names}')
    restored=restore(source)
    # Parity is independent of the training dataset and its directory layout.
    rng=np.random.default_rng(317123)
    image=rng.integers(0,256,size=(480,640,3),dtype=np.uint8)
    rgb=np.full((640,640,3),114,np.uint8);rgb[80:560]=image
    tensor=np.ascontiguousarray(rgb.transpose(2,0,1)[None],dtype=np.float32)/255
    options=ort.SessionOptions();options.intra_op_num_threads=4
    session=ort.InferenceSession(str(source),options,providers=['CPUExecutionProvider'])
    reference=session.run(None,{'images':tensor})[0]
    with torch.no_grad():
        actual=restored(torch.from_numpy(tensor))[0].numpy()
    parity=float(np.max(np.abs(actual-reference)))
    print('Recovered PyTorch/ONNX max absolute difference:',parity,flush=True)
    if parity>.1:
        raise ValueError('Source model reconstruction failed parity check')
    yolo=YOLO(str(args.resume)) if args.resume else YOLO('yolov8n.yaml')
    if not args.resume:
        yolo.model=restored
        yolo.ckpt={'model':restored}
    yolo.train(trainer=FrozenBNTrainer,resume=str(args.resume) if args.resume else False,
               data=str(dataset),epochs=args.epochs,imgsz=320,batch=args.batch,
               device='cpu',workers=0,freeze=10,optimizer='AdamW',lr0=.002,lrf=.1,warmup_epochs=2,warmup_bias_lr=.002,
               patience=12,hsv_h=0.,hsv_s=.25,hsv_v=.3,mosaic=.5,close_mosaic=8,
               degrees=4,translate=.1,scale=.25,fliplr=.5,cache=True,amp=False,
               project=str(ROOT/'.test/vision_training/runs'),name='balls_recovered',exist_ok=True,
               seed=317123,deterministic=True,plots=True)
    trained=YOLO(str(yolo.trainer.best))
    results=trained.val(data=str(dataset),split='test',imgsz=320,device='cpu',workers=0,plots=True,
                        project=str(ROOT/'.test/vision_training'),name='holdout_validation')
    exported=trained.export(format='onnx',imgsz=(480,640),opset=17,simplify=False,dynamic=False,nms=False)
    destination=ROOT.parents[1]/'ros_packages/src/rds_2p_vision/models/yolov8n_balls.onnx'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(Path(exported).read_bytes())
    per_class={NAMES[int(class_id)]:dict(precision=float(results.box.p[i]),recall=float(results.box.r[i]),
        map50=float(results.box.ap50[i]),map50_95=float(results.box.ap[i]))
        for i,class_id in enumerate(results.box.ap_class_index)}
    provenance=dataset.parent/'provenance.json'
    report=dict(source_model_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                model_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                names=NAMES,imgsz=320,export_imgsz=[480,640],epochs=args.epochs,reconstruction_max_absolute_error=parity,
                test=results.results_dict,per_class=per_class,
                dataset=json.loads(provenance.read_text()) if provenance.exists() else {'path':str(dataset)},
                limitation='Synthetic camera only. Real camera accuracy is not validated; collect and label real frames before deployment claims.')
    (destination.parent/'training_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Exported trained model:',destination,flush=True)


if __name__=='__main__':
    main()
