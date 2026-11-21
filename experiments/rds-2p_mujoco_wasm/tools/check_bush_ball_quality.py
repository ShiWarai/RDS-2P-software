#!/usr/bin/env python3
"""Measure bush <-> ball swaps on precise instance-mask ground truth."""
import argparse
import json
import sys
from pathlib import Path

import cv2
from ultralytics.utils import YAML

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parents[1]/'ros_packages/src/rds_2p_vision'))
from rds_2p_vision.detector import YoloDetector, iou


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--split', choices=['val','test'], default='test')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-no-swaps', action='store_true')
    args = parser.parse_args()
    cfg = YAML.load(str(args.data))
    dataset = Path(cfg['path'])
    detector = YoloDetector(args.model,threads=4)
    counts = dict(frames=0,no_ball_frames=0,bushes=0,balls=0,bushes_found=0,balls_found=0,
                  bush_as_ball=0,ball_as_bush=0,false_balls_in_no_ball_frames=0)
    failures, false_ball_predictions = [], []
    for file in sorted((dataset/cfg[args.split]).glob('*.jpg')):
        image = cv2.cvtColor(cv2.imread(str(file)),cv2.COLOR_BGR2RGB)
        h,w = image.shape[:2]
        truth=[]
        for line in (dataset/'labels'/args.split/file.with_suffix('.txt').name).read_text().splitlines():
            c,x,y,bw,bh=map(float,line.split())
            truth.append(dict(classId=int(c),x1=(x-bw/2)*w,y1=(y-bh/2)*h,x2=(x+bw/2)*w,y2=(y+bh/2)*h))
        predictions=detector.detect(image)
        no_balls=not any(gt['classId']>=4 for gt in truth)
        counts['frames']+=1
        counts['no_ball_frames']+=int(no_balls)
        if no_balls:
            counts['false_balls_in_no_ball_frames']+=sum(p['classId']>=4 for p in predictions)
            for prediction in predictions:
                if prediction['classId']>=4:
                    overlap,index=max(((iou(prediction,gt),i) for i,gt in enumerate(truth)),default=(0,-1))
                    false_ball_predictions.append(dict(frame=file.name,prediction=prediction,
                        nearest_ground_truth=truth[index] if index>=0 else None,overlap=overlap))
        for gt in truth:
            cls=gt['classId']
            if cls!=1 and cls<4:
                continue
            key='bushes' if cls==1 else 'balls'
            counts[key]+=1
            counts[key+'_found']+=int(any(p['classId']==cls and iou(p,gt)>=.5 for p in predictions))
        for pred in predictions:
            overlap,index=max(((iou(pred,gt),i) for i,gt in enumerate(truth)),default=(0,-1))
            if overlap<.5:
                continue
            actual=truth[index]['classId']
            wrong=(actual==1 and pred['classId']>=4) or (actual>=4 and pred['classId']==1)
            if wrong:
                key='bush_as_ball' if actual==1 else 'ball_as_bush'
                counts[key]+=1
                failures.append(dict(frame=file.name,expected=actual,prediction=pred))
    report=dict(model=str(args.model),split=args.split,confidence=.35,matching_iou=.5,
                counts=counts,bush_recall=counts['bushes_found']/max(1,counts['bushes']),
                ball_recall=counts['balls_found']/max(1,counts['balls']),failures=failures,
                false_ball_predictions=false_ball_predictions)
    report['passed']=not failures and report['bush_recall']>=.8 and report['ball_recall']>=.8
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['failures','false_ball_predictions']}),flush=True)
    if args.require_no_swaps and not report['passed']:
        raise SystemExit('Bush/ball regression: swaps or insufficient positive detections')


if __name__=='__main__':
    main()
