#!/usr/bin/env python3
"""Export the trained checkpoint for full 640x480 RGB frames, without retraining."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT.parents[1] / 'ros_packages/src/rds_2p_vision/models/yolov8n_balls.onnx'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    torch.set_num_threads(4)
    checkpoint = args.checkpoint.resolve()
    output = args.output.resolve()
    work = ROOT / '.test/vision_export'
    work.mkdir(parents=True, exist_ok=True)
    copied = work / checkpoint.name
    shutil.copy2(checkpoint, copied)
    model = YOLO(str(copied))
    training_imgsz = model.ckpt.get('train_args', {}).get('imgsz')
    exported = Path(model.export(format='onnx', imgsz=(480, 640), opset=17,
                                 simplify=False, dynamic=False, nms=False, device='cpu'))
    onnx.checker.check_model(onnx.load(str(exported)))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(exported), options, providers=['CPUExecutionProvider'])
    shape = session.get_inputs()[0].shape
    if shape != [1, 3, 480, 640]:
        raise ValueError(f'Unexpected model input: {shape}')
    # Compare the real ONNX graph with the same checkpoint at the new resolution.
    tensor = np.random.default_rng(317123).random(shape, dtype=np.float32)
    actual = session.run(None, {session.get_inputs()[0].name: tensor})[0]
    model.model.eval()
    with torch.no_grad():
        prediction = model.model(torch.from_numpy(tensor))
        expected = (prediction[0] if isinstance(prediction, tuple) else prediction).numpy()
    if actual.shape != expected.shape:
        raise ValueError(f'Checkpoint / ONNX output mismatch: {expected.shape} vs {actual.shape}')
    error = float(np.max(np.abs(actual - expected)))
    if error > .1:
        raise ValueError(f'Checkpoint / ONNX parity failed: {error}')
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exported, output)
    report_path = output.parent / 'training_report.json'
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report['model_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
        report['export_imgsz'] = [480, 640]
        report['export'] = dict(input_shape=shape, output_shape=list(actual.shape),
                                checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                                checkpoint_training_imgsz=training_imgsz,
                                checkpoint_onnx_max_absolute_error=error,
                                note='Export preserves checkpoint weights. Quality must be checked at the exported input shape.')
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(output=str(output), input_shape=shape, output_shape=list(actual.shape),
                          checkpoint_onnx_max_absolute_error=error)), flush=True)


if __name__ == '__main__':
    main()
