#!/usr/bin/env python3
"""Exercise all seven classes in the real browser scene across fixed camera headings."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

NAMES = {'tree', 'bush', 'rock', 'flower', 'blue_ball', 'red_ball', 'green_ball'}
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:8085')
    parser.add_argument('--model', type=Path)
    args = parser.parse_args()
    output = ROOT/'.test/vision_regression/browser'
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        if args.model:
            page.route('**/models/vision/yolov8n_balls.onnx*', lambda route: route.fulfill(
                path=str(args.model.resolve()), content_type='application/octet-stream'))
        page.goto(args.url+'/?backend=wasm', wait_until='domcontentloaded')
        page.wait_for_function('window.__panda?.depthMap', timeout=60000)
        page.evaluate('''() => {const s=__panda.sim;s.setPaused(true);
          s.renderer.shadowMap.enabled=false;s.renderer.setSize(400,300,false);}''')
        page.locator('#tab-btn-cv').click()
        page.wait_for_function('window.__visionPipeline?.ready||window.__visionPipeline?.modelError', timeout=120000)
        assert page.evaluate('__visionPipeline.ready'), page.evaluate('String(__visionPipeline.modelError)')
        assert page.locator('.camera-specs').count() == 0, 'Camera information banner must be removed'
        seen, frames = set(), []
        for heading in [0, -.6, .6, -1.2, 1.2]:
            changed_at = page.evaluate('''yaw => {const s=__panda.sim;
              s.data.qpos[3]=Math.cos(yaw/2);s.data.qpos[4]=0;s.data.qpos[5]=0;s.data.qpos[6]=Math.sin(yaw/2);
              s.mujoco.mj_forward(s.model,s.data);return performance.now();}''', heading)
            page.wait_for_function('time => __panda.sim.ballFollower.capturedAt>time+100', arg=changed_at, timeout=30000)
            detections = page.evaluate('__visionPipeline.latestDetections')
            labels = sorted({box['label'] for box in detections})
            seen.update(labels)
            frames.append(dict(heading=heading, labels=labels, detections=detections))
            print('SCENE', heading, labels, flush=True)
            page.evaluate("document.querySelectorAll('.toast').forEach(n=>n.remove())")
            page.screenshot(path=str(output/f'heading-{heading}.png'))
        report = dict(seen=sorted(seen), missing=sorted(NAMES-seen), frames=frames, errors=errors)
        (output/'scene-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        assert not report['missing'], report
        assert not errors, errors
        assert page.evaluate('JSON.stringify(__visionPipeline.inputShape)==="[1,3,480,640]"')
        browser.close()
    print('PASS all seven classes in real browser scene at 640x480', flush=True)


if __name__ == '__main__':
    main()
