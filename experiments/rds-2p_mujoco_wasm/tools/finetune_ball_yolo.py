#!/usr/bin/env python3
"""Adapt the seven-class detector to actual 640x480 inputs; keep test data separate."""
import argparse
import json
from pathlib import Path

import torch
from ultralytics import YOLO

from train_ball_yolo import NativeFrameTrainer, NAMES

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', type=Path, default=ROOT/'.test/vision_training/runs/balls_recovered/weights/best.pt')
    parser.add_argument('--data', type=Path, default=ROOT/'.test/vision_training/dataset/data.yaml')
    parser.add_argument('--epochs', type=int, default=12)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--threads', type=int, default=6)
    parser.add_argument('--name', default='native_640x480')
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    model = YOLO(str(args.checkpoint.resolve()))
    if list(model.names.values()) != NAMES:
        raise ValueError('Checkpoint class order does not match the application')
    model.train(trainer=NativeFrameTrainer, data=str(args.data.resolve()),
                epochs=args.epochs, imgsz=640, rect=True, batch=args.batch,
                device='cpu', workers=0, freeze=10, optimizer='AdamW',
                lr0=.0005, lrf=.2, warmup_epochs=1, warmup_bias_lr=.0005,
                patience=args.epochs, hsv_h=0., hsv_s=.15, hsv_v=.2,
                mosaic=0., close_mosaic=0, mixup=0., degrees=2,
                translate=.05, scale=.15, fliplr=.5, cache=True, amp=False,
                project=str(ROOT/'.test/vision_regression/runs'), name=args.name,
                exist_ok=False, seed=317123, deterministic=True, plots=True,
                save_period=1)
    print(json.dumps(dict(best=str(model.trainer.best), last=str(model.trainer.last),
                          save_dir=str(model.trainer.save_dir))), flush=True)


if __name__ == '__main__':
    main()
