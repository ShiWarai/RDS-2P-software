#!/usr/bin/env python3
"""Browser integration: real ONNX inference, hidden CV tab, pursuit and target loss."""
import argparse
import base64
import json
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://localhost:8085')
    parser.add_argument('--model',type=Path,help='Optional checkpoint export to exercise before deployment')
    parser.add_argument('--software-renderer',action='store_true')
    args=parser.parse_args()
    output=Path(__file__).resolve().parents[1]/'.test/vision_training/browser'
    output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        chrome=shutil.which('google-chrome') or shutil.which('chromium')
        windows=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        if windows.exists():
            chrome=str(windows)
        browser=p.chromium.launch(headless=True,**({'executable_path':chrome} if chrome else {}),
            args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'] if args.software_renderer else ['--enable-webgl'])
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        if args.model:
            page.route('**/models/vision/yolov8n_balls.onnx*',lambda route:route.fulfill(
                path=str(args.model.resolve()),content_type='application/octet-stream'))
        page.goto(args.url+'/?backend=wasm',wait_until='domcontentloaded')
        page.wait_for_function('window.__panda?.sim?.ballFollower',timeout=60000)
        page.evaluate('''() => {const s=window.__panda.sim;s.renderer.shadowMap.enabled=false;s.renderer.setSize(400,300,false);}''')
        page.locator('#tab-btn-cv').click()
        page.wait_for_function('window.__visionPipeline?.ready || window.__visionPipeline?.modelError',timeout=120000)
        assert page.evaluate('window.__visionPipeline.ready'),page.evaluate('String(window.__visionPipeline.modelError)')
        assert page.evaluate('JSON.stringify(__visionPipeline.inputShape)==="[1,3,480,640]"'), 'YOLO must use native 640x480 input'
        # With Astra's narrower FOV, the default ball is already at the stop size.
        # Start farther away to exercise actual pursuit instead of a correct stop.
        page.evaluate('''() => {const s=__panda.sim;s.data.qpos[19]=.95;s.data.qvel.fill(0,18,24);
            s.mujoco.mj_forward(s.model,s.data);}''')
        page.wait_for_function('window.__panda.sim.ballFollower.detection?.label === "blue_ball"',timeout=30000)
        page.wait_for_function('__panda.sim.ballFollower.detection?.relativeWidth<.16',timeout=30000)
        print('YOLO',json.dumps(page.evaluate('''() => ({detection:window.__panda.sim.ballFollower.detection,
            metrics:window.__visionPipeline.metrics,backend:window.__visionPipeline.backend})''')),flush=True)
        raw=page.evaluate('''() => {const v=window.__visionPipeline,c=document.createElement('canvas');
            c.width=v.previewCanvas.width;c.height=v.previewCanvas.height;
            c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(v.displayPixels),c.width,c.height),0,0);
            return c.toDataURL('image/png').split(',')[1];}''')
        (output/'camera_raw.png').write_bytes(base64.b64decode(raw))
        page.screenshot(path=str(output/'yolo-camera.png'))
        page.locator('#btn-follow-blue').click()
        page.wait_for_function('window.__panda.sim.ballFollower.active',timeout=60000)
        page.locator('#tab-btn-osm').click()
        assert not page.evaluate('window.__visionPipeline.paused'),'YOLO must continue with CV tab hidden'
        page.wait_for_function('window.__panda.sim.data.qpos[0] > .08',timeout=45000)
        print('FOLLOW',json.dumps(page.evaluate('''() => ({pose:Array.from(window.__panda.sim.data.qpos.slice(0,3)),
            cmd:window.__panda.sim.player.policyCmd,target:window.__panda.sim.ballFollower.detection})''')),flush=True)
        page.evaluate('''() => {const s=window.__panda.sim;s.data.qpos[19]=s.data.qpos[0]-.7;
            s.data.qpos[20]=s.data.qpos[1];s.data.qvel.fill(0,18,24);s.mujoco.mj_forward(s.model,s.data);}''')
        page.wait_for_function('!window.__panda.sim.ballFollower.detection && window.__panda.sim.player.policyCmd.every(v=>v===0)',timeout=15000)
        page.keyboard.press('Escape')
        assert not page.evaluate('window.__panda.sim.ballFollower.active')
        page.locator('#btn-reset').click()
        assert page.evaluate('Math.abs(window.__panda.sim.data.qpos[19]-.75)<.001')
        assert not errors,errors
        print('YOLO camera, hidden-tab pursuit, loss stop, Esc and reset passed',flush=True)
        browser.close()


if __name__=='__main__':
    main()
