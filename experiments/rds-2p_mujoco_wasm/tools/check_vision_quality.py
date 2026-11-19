#!/usr/bin/env python3
"""Compare every class on a labelled split at deployment confidence/IoU settings."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from ultralytics.utils import YAML
from ultralytics.utils.metrics import ap_per_class

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]/'ros_packages/src/rds_2p_vision'))
from rds_2p_vision.detector import NAMES, YoloDetector, iou


def match(predictions, truth, threshold):
    matched = set()
    correct = []
    for box in predictions:
        matches = [(iou(box, gt), index) for index, gt in enumerate(truth)
                   if index not in matched and gt['classId'] == box['classId']]
        overlap, index = max(matches, default=(0., -1))
        correct.append(overlap >= threshold)
        if overlap >= threshold:
            matched.add(index)
    return np.array(correct, dtype=bool)


def evaluate(model, frames):
    detector = YoloDetector(model, confidence=.001, threads=4)
    total = np.zeros(len(NAMES), int)
    tp, fp = total.copy(), total.copy()
    true_positive, scores, predicted_classes, target_classes, timings = [], [], [], [], []
    for image, truth in frames:
        started = time.perf_counter()
        predictions = detector.detect(image)
        timings.append((time.perf_counter()-started)*1000)
        deployed = [box for box in predictions if box['confidence'] >= .35]
        correct = match(deployed, truth, .5)
        for box, found in zip(deployed, correct):
            (tp if found else fp)[box['classId']] += 1
        for gt in truth:
            total[gt['classId']] += 1
        if predictions:
            true_positive.append(np.stack([match(predictions, truth, threshold)
                                           for threshold in np.linspace(.5, .95, 10)], axis=1))
            scores.extend(box['confidence'] for box in predictions)
            predicted_classes.extend(box['classId'] for box in predictions)
        target_classes.extend(gt['classId'] for gt in truth)
    correctness = np.concatenate(true_positive) if true_positive else np.zeros((0, 10), bool)
    metrics = ap_per_class(correctness, np.array(scores), np.array(predicted_classes),
                           np.array(target_classes), names=dict(enumerate(NAMES)))
    average_precision = {int(cls): values for cls, values in zip(metrics[6], metrics[5])}
    classes = {}
    for index, name in enumerate(NAMES):
        ap = average_precision.get(index, np.zeros(10))
        classes[name] = dict(precision=float(tp[index]/max(1, tp[index]+fp[index])),
                             recall=float(tp[index]/max(1, total[index])),
                             map50=float(ap[0]), map50_95=float(ap.mean()),
                             true_positive=int(tp[index]), false_positive=int(fp[index]),
                             ground_truth=int(total[index]))
    return dict(sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
                input_shape=detector.input.shape, frames=len(frames),
                median_ms=float(np.median(timings)), classes=classes,
                map50=float(np.mean([row['map50'] for row in classes.values()])))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, action='append', required=True)
    parser.add_argument('--data', type=Path, default=ROOT/'.test/vision_training/dataset/data.yaml')
    parser.add_argument('--split', choices=['val', 'test'], default='test')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-no-regression', action='store_true',
                        help='Require every AP50 and scenery recall to match/exceed the first model')
    args = parser.parse_args()
    data = YAML.load(str(args.data))
    dataset = Path(data['path'])
    image_dir = dataset/data[args.split]
    frames = []
    fingerprint = hashlib.sha256()
    for file in sorted(image_dir.glob('*.jpg')):
        image = cv2.cvtColor(cv2.imread(str(file)), cv2.COLOR_BGR2RGB)
        height, width = image.shape[:2]
        label = dataset/'labels'/args.split/file.with_suffix('.txt').name
        fingerprint.update(file.name.encode('utf-8'))
        fingerprint.update(file.read_bytes())
        fingerprint.update(label.read_bytes())
        truth = []
        for row in label.read_text().splitlines():
            cls, x, y, w, h = map(float, row.split())
            truth.append(dict(classId=int(cls), x1=(x-w/2)*width, y1=(y-h/2)*height,
                              x2=(x+w/2)*width, y2=(y+h/2)*height))
        frames.append((image, truth))
    if not frames:
        raise ValueError(f'No labelled frames in {image_dir}')
    provenance_path = dataset/'provenance.json'
    provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else {}
    report = dict(split=args.split, dataset_sha256=fingerprint.hexdigest(),
                  confidence=.35, matching_iou=.5, nms_iou=.45, max_detections=50,
                  labels=provenance.get('labels', 'Synthetic labels; not real-camera ground truth.'), models={})
    for model in args.model:
        report['models'][str(model)] = evaluate(model, frames)
        print(model, json.dumps(report['models'][str(model)]), flush=True)
    failures = []
    if args.require_no_regression:
        if len(args.model) < 2:
            raise ValueError('A baseline and candidate are required for the regression gate')
        baseline = report['models'][str(args.model[0])]['classes']
        candidate = report['models'][str(args.model[-1])]['classes']
        for name in NAMES:
            if candidate[name]['map50']+1e-9 < baseline[name]['map50']:
                failures.append(f'{name}: AP50 below baseline')
            if name in NAMES[:4] and candidate[name]['recall']+1e-9 < baseline[name]['recall']:
                failures.append(f'{name}: scenery recall below baseline')
        report['regression_gate'] = dict(passed=not failures, failures=failures)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    if failures:
        raise SystemExit('; '.join(failures))


if __name__ == '__main__':
    main()
