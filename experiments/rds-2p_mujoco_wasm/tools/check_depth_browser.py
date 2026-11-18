#!/usr/bin/env python3
"""Depth GPU/UI/lifecycle regression and optional 30s performance runs. No robot hardware."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.test/depth'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:8085')
    parser.add_argument('--perf', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results = {'checks': []}

    def check(condition, name):
        assert condition, name
        results['checks'].append(name)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome', args=['--enable-webgl'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url + '/tools/check_depth_map.html')
        page.wait_for_function('window.depthResults')
        results['gpu'] = page.evaluate('window.depthResults')
        check(results['gpu']['passed'], 'independent GPU fixture')
        page.goto(args.url + '/?backend=wasm', wait_until='domcontentloaded')
        page.wait_for_function('window.__panda?.depthMap', timeout=90000)
        results['environment'] = page.evaluate('''() => {
          const gl=__panda.sim.renderer.getContext(), ext=gl.getExtension('WEBGL_debug_renderer_info');
          return {browser:navigator.userAgent, gpu:ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER),
            viewport:[innerWidth,innerHeight],hardwareConcurrency:navigator.hardwareConcurrency};
        }''')
        page.locator('#btn-depth-map').click()
        page.wait_for_function('__panda.depthMap.metrics.frameCount>2')
        check(page.evaluate('!window.__visionPipeline'), 'map works before YOLO initialization')
        check(page.evaluate('[...__panda.depthMap.depthMeters].some(z=>z>0&&z<=2)'), 'real scene contains measurable surfaces')
        check(page.evaluate('''() => {const d=__panda.depthMap, c=d.camera;
          return c.far===3 && c.fov===90 && c.aspect===4/3 && c.parent.name==='base_link';}'''), 'separate central camera parameters')
        resize_handle = page.locator('[data-depth-resize]')

        def resize_mouse(delta):
            box = resize_handle.bounding_box()
            page.mouse.move(box['x']+box['width']/2, box['y']+box['height']/2)
            page.mouse.down()
            page.mouse.move(box['x']+box['width']/2+delta, box['y']+box['height']/2, steps=8)
            page.mouse.up()

        initial_width = page.locator('#depth-window').bounding_box()['width']
        resize_mouse(-100)
        check(page.locator('#depth-window').bounding_box()['width'] < initial_width-80, 'corner drag visually shrinks window')
        page.evaluate('''() => {window.resizeKeyBubbled=false;window.resizeKeySpy=e=>{if(e.key==='ArrowLeft')window.resizeKeyBubbled=true;};
          document.addEventListener('keydown',window.resizeKeySpy);}''')
        key_width = page.locator('#depth-window').bounding_box()['width']
        resize_handle.focus()
        page.keyboard.press('ArrowLeft')
        check(abs(page.locator('#depth-window').bounding_box()['width']-(key_width-20))<1 and not page.evaluate('window.resizeKeyBubbled'),
              'keyboard resizes window without driving robot')
        page.evaluate("document.removeEventListener('keydown',window.resizeKeySpy)")
        resize_mouse(1000)
        check(page.locator('#depth-window').bounding_box()['width'] == 640, 'visual width maximum 640px')
        resize_mouse(-1000)
        check(page.locator('#depth-window').bounding_box()['width'] == 260, 'visual width minimum 260px')
        check(page.evaluate('''() => {const c=document.querySelector('#depth-canvas'),r=c.getBoundingClientRect();
          return c.width===320&&c.height===240&&Math.abs(r.width/r.height-4/3)<.01;}'''), 'resizing preserves 4:3 and 320x240 sensor resolution')
        page.evaluate('__panda.depthMap.close();__panda.depthMap.open()')
        check(page.locator('#depth-window').bounding_box()['width'] == 260, 'reopen retains chosen visual size')
        box = resize_handle.bounding_box()
        page.mouse.move(box['x']+10,box['y']+10)
        page.mouse.down()
        page.evaluate('__panda.depthMap.close()')
        page.mouse.up()
        check(page.evaluate('!__panda.depthMap.panelResize'), 'closing window releases resize capture')
        page.locator('#btn-depth-map').click()
        page.evaluate('__panda.depthMap.sizePanel(440)')
        # Drag only the window header: camera transform must stay attached to the robot.
        original_camera = page.evaluate('__panda.depthMap.camera.position.toArray().concat(__panda.depthMap.camera.quaternion.toArray())')
        header = page.locator('.depth-heading')
        rect = page.locator('#depth-window').bounding_box()
        handle = header.bounding_box()
        page.mouse.move(handle['x'] + 30, handle['y'] + 15)
        page.mouse.down()
        page.mouse.move(handle['x'] - 170, handle['y'] + 65, steps=8)
        page.mouse.up()
        moved = page.locator('#depth-window').bounding_box()
        check(moved['x'] < rect['x'] - 100 and moved['y'] > rect['y'], 'mouse drag moves depth window')
        check(page.evaluate('__panda.depthMap.camera.position.toArray().concat(__panda.depthMap.camera.quaternion.toArray())') == original_camera,
              'window drag preserves camera pose')
        handle = header.bounding_box()
        page.mouse.move(handle['x'] + 30, handle['y'] + 15)
        page.mouse.down()
        page.mouse.move(0, 0, steps=8)
        check(page.evaluate('''() => {const r=document.querySelector('#depth-window').getBoundingClientRect();return r.left>=12&&r.top>=12;}'''),
              'drag clamps top and left edges')
        page.mouse.move(1439, 999, steps=8)
        page.mouse.up()
        check(page.evaluate('''() => {const r=document.querySelector('#depth-window').getBoundingClientRect();return r.right<=innerWidth-11&&r.bottom<=innerHeight-11;}'''),
              'drag clamps bottom and right edges')
        # Real touch events exercise pointer capture, touch-action and pointercancel in Chromium.
        cdp = page.context.new_cdp_session(page)
        cdp.send('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 1})
        handle = header.bounding_box()
        x, y = handle['x'] + 30, handle['y'] + 15
        before_touch = page.locator('#depth-window').bounding_box()
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': x - 120, 'y': y - 80}]})
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        page.wait_for_timeout(100)
        after_touch = page.locator('#depth-window').bounding_box()
        check(after_touch['x'] < before_touch['x'] and after_touch['y'] < before_touch['y'], 'touch drag moves window')
        box = resize_handle.bounding_box()
        touch_width = page.locator('#depth-window').bounding_box()['width']
        cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':box['x']+10,'y':box['y']+10}]})
        cdp.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':box['x']-50,'y':box['y']+10}]})
        cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
        page.wait_for_timeout(100)
        check(page.locator('#depth-window').bounding_box()['width'] < touch_width-40, 'touch corner resize shrinks window')
        box = resize_handle.bounding_box()
        cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':box['x']+10,'y':box['y']+10}]})
        cdp.send('Input.dispatchTouchEvent', {'type':'touchCancel','touchPoints':[]})
        check(page.evaluate('!__panda.depthMap.panelResize'), 'pointercancel ends corner resize')
        handle = header.bounding_box()
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': handle['x']+25, 'y': handle['y']+15}]})
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchCancel', 'touchPoints': []})
        check(page.evaluate('!__panda.depthMap.panelDrag'), 'pointercancel ends window drag')
        cdp.send('Emulation.setTouchEmulationEnabled', {'enabled': False})
        cdp.detach()
        handle = header.bounding_box()
        page.mouse.move(handle['x']+25, handle['y']+15)
        page.mouse.down()
        page.evaluate('__panda.depthMap.close()')
        page.mouse.up()
        check(page.evaluate('!__panda.depthMap.panelDrag'), 'close releases active drag')
        saved_position = page.evaluate("({left:document.querySelector('#depth-window').style.left,top:document.querySelector('#depth-window').style.top})")
        page.locator('#btn-depth-map').click()
        check(page.evaluate("({left:document.querySelector('#depth-window').style.left,top:document.querySelector('#depth-window').style.top})") == saved_position,
              'reopen preserves dragged window position')
        handle = header.bounding_box()
        page.mouse.move(handle['x']+25, handle['y']+15)
        page.mouse.down()
        page.evaluate('''() => {const d=__panda.depthMap;d.dragHandle.releasePointerCapture(d.panelDrag.pointerId);}''')
        page.mouse.move(handle['x']+35, handle['y']+20)
        page.mouse.up()
        check(page.evaluate('!__panda.depthMap.panelDrag'), 'lost pointer capture ends window drag')
        page.evaluate('''() => {const d=__panda.depthMap; for(let i=0;i<20;i++){d.close();d.open();}}''')
        check(page.evaluate('''() => {let n=0;__panda.sim.scene.traverse(o=>{if(o.name==='robot-depth-camera')n++;});return n===1;}'''), '20 reopen cycles retain one camera')
        page.locator('[data-depth-close]').click()
        count = page.evaluate('__panda.depthMap.metrics.frameCount')
        page.wait_for_timeout(400)
        check(page.evaluate('__panda.depthMap.metrics.frameCount') == count, 'closed window stops capture')
        check(page.evaluate("document.activeElement.id==='btn-depth-map'"), 'close returns keyboard focus')
        check(page.evaluate('!__panda.depthMap.panelDrag'), 'close button does not begin drag')
        page.locator('#btn-depth-map').click()
        page.keyboard.press('Escape')
        check(page.locator('#depth-window').is_hidden(), 'Escape closes focused depth window')
        page.locator('#btn-depth-map').click()
        page.evaluate('__panda.sim.setPaused(true)')
        page.wait_for_timeout(200)
        old = page.evaluate('Array.from(__panda.depthMap.camera.matrixWorld.elements)')
        page.evaluate('''() => {const s=__panda.sim;s.data.qpos[0]+=.2;
          s.data.qpos[3]=Math.cos(.1);s.data.qpos[4]=0;s.data.qpos[5]=0;s.data.qpos[6]=Math.sin(.1);
          s.mujoco.mj_forward(s.model,s.data);}''')
        page.wait_for_timeout(300)
        check(page.evaluate('Array.from(__panda.depthMap.camera.matrixWorld.elements)') != old, 'depth camera follows position and rotation on pause')
        # Deterministic pause-drag: move the same free-joint data path used by paused dragging.
        before = page.evaluate('Array.from(__panda.depthMap.image.data)')
        page.evaluate('''() => {const s=__panda.sim;const j=Array.from(s.model.jnt_type).findIndex((t,i)=>i>0&&t===0);
          const a=s.model.jnt_qposadr[j];s.data.qpos[a]+=.25;s.mujoco.mj_forward(s.model,s.data);}''')
        page.wait_for_timeout(300)
        check(page.evaluate('Array.from(__panda.depthMap.image.data)') != before, 'paused object movement updates depth')
        page.evaluate('''() => {document.querySelector('#btn-reset').click();window.resetInvalidated=__panda.depthMap.canvas.style.visibility==='hidden';}''')
        check(page.evaluate('window.resetInvalidated'), 'reset invalidates old image immediately')
        page.wait_for_function('__panda.depthMap.canvas.style.visibility==="visible"')
        page.evaluate('__panda.sim.setPaused(false)')
        page.locator('[data-depth-close]').click()
        # Test narrow view with an open window; programmatic click avoids unrelated page layout.
        page.set_viewport_size({'width': 390, 'height': 650})
        page.evaluate("document.querySelector('#btn-depth-map').click()")
        check(page.evaluate('''() => {const r=document.querySelector('#depth-window').getBoundingClientRect();
          const c=document.querySelector('#depth-canvas').getBoundingClientRect();
          return r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&Math.abs(c.width/c.height-4/3)<.01;}'''), 'narrow viewport preserves window and 4:3 image')
        page.evaluate('__panda.depthMap.sizePanel(640)')
        check(page.evaluate('''() => {const r=document.querySelector('[data-depth-resize]').getBoundingClientRect();
          return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;}'''), 'resize handle stays on screen with constrained height')
        page.set_viewport_size({'width': 1440, 'height': 450})
        page.evaluate('__panda.depthMap.sizePanel(640)')
        check(page.evaluate('''() => {const p=document.querySelector('#depth-window'),r=document.querySelector('[data-depth-resize]').getBoundingClientRect();
          return p.scrollHeight>p.clientHeight&&r.top>=0&&r.bottom<=innerHeight;}'''), 'resize handle visible when window content scrolls')
        page.set_viewport_size({'width': 390, 'height': 650})
        page.screenshot(path=str(OUT / 'depth-mobile.png'))
        page.locator('[data-depth-close]').click()
        page.set_viewport_size({'width': 1440, 'height': 1000})
        # Document hidden state is normally controlled by the browser. Override only in this test.
        page.evaluate('''() => {__panda.depthMap.open();Object.defineProperty(document,'hidden',{configurable:true,value:true});
          document.dispatchEvent(new Event('visibilitychange'));}''')
        count = page.evaluate('__panda.depthMap.metrics.frameCount')
        page.wait_for_timeout(300)
        check(page.evaluate('__panda.depthMap.metrics.frameCount') == count, 'hidden document stops measurements')
        page.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_function(f'__panda.depthMap.metrics.frameCount>{count}')
        # Expected readback failure must be caught by the component, not the animation loop.
        page.evaluate('''() => {const r=__panda.sim.renderer;window.savedRead=r.readRenderTargetPixels;
          r.readRenderTargetPixels=()=>{throw Error('injected GPU failure');};__panda.depthMap.invalidate();}''')
        page.wait_for_function('__panda.depthMap.state==="error"')
        check(page.locator('[data-depth-status]').inner_text().startswith('Карта глубины недоступна'), 'readback failure shows recoverable error')
        page.evaluate('''() => {__panda.sim.renderer.readRenderTargetPixels=window.savedRead;__panda.depthMap.close();__panda.depthMap.open();}''')
        page.wait_for_function('__panda.depthMap.state==="open"&&__panda.depthMap.canvas.style.visibility==="visible"')
        # Real WebGL loss/restoration, using the browser testing extension.
        page.evaluate('''() => {__panda.depthMap.close();window.contextLoss=__panda.sim.renderer.getContext().getExtension('WEBGL_lose_context');
          if(!window.contextLoss)throw Error('WEBGL_lose_context unavailable');window.contextLoss.loseContext();}''')
        page.wait_for_function('__panda.depthMap.contextLost')
        check(page.locator('#depth-window').is_hidden(), 'context loss does not open closed window')
        page.evaluate('window.contextLoss.restoreContext()')
        page.wait_for_function('!__panda.depthMap.contextLost', timeout=15000)
        page.locator('#btn-depth-map').click()
        page.wait_for_function('__panda.depthMap.canvas.style.visibility==="visible"')
        # Browser lifecycle events exercise this component without navigating the test harness away.
        page.evaluate('__panda.depthMap.placePanel(innerWidth,innerHeight)')
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}))")
        check(page.evaluate('__panda.depthMap.state==="disposed"&&__panda.sim.onDepthFrame===null'), 'pagehide disposes depth component')
        page.set_viewport_size({'width': 390, 'height': 650})
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
        check(page.evaluate('__panda.depthMap.state==="closed"'), 'pageshow recreates closed depth controller')
        page.evaluate("document.querySelector('#btn-depth-map').click()")
        page.wait_for_function('__panda.depthMap.metrics.frameCount>2')
        check(page.evaluate('''() => {const r=document.querySelector('#depth-window').getBoundingClientRect();
          return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;}'''), 'restored controller clamps retained coordinates after resize')
        page.set_viewport_size({'width': 1440, 'height': 1000})
        # Capture clean screenshot before starting YOLO.
        page.evaluate("document.querySelectorAll('.toast').forEach(n=>n.remove())")
        page.screenshot(path=str(OUT / 'depth-desktop.png'))
        page.locator('[data-depth-close]').click()

        # Failure to load YOLO cannot disable depth. Keep this separate from the live-YOLO page.
        failed = browser.new_page(viewport={'width': 1440, 'height': 1000})
        failed.route('**/models/vision/yolov8n_balls.onnx*', lambda route: route.fulfill(status=503, body='test model unavailable'))
        failed.goto(args.url + '/?backend=wasm', wait_until='domcontentloaded')
        failed.wait_for_function('window.__panda?.depthMap', timeout=90000)
        failed.locator('#tab-btn-cv').click()
        failed.wait_for_function('window.__visionPipeline?.modelError', timeout=90000)
        failed.locator('#btn-depth-map').click()
        failed.wait_for_function('__panda.depthMap.metrics.frameCount>2')
        check(failed.evaluate('__panda.depthMap.state==="open"'), 'depth survives YOLO model download failure')
        failed.close()

        # Use a fresh production page: lifecycle dispatch above also disposes the existing YOLO bootstrap.
        page.goto(args.url + '/?backend=wasm', wait_until='domcontentloaded')
        page.wait_for_function('window.__panda?.depthMap', timeout=90000)
        if args.perf:
            results['performance'] = []
            for yolo in [False, True]:
                if yolo:
                    page.locator('#tab-btn-cv').click()
                    page.wait_for_function('__visionPipeline?.ready||__visionPipeline?.modelError', timeout=120000)
                    check(page.evaluate('!!__visionPipeline.ready'), 'real YOLO ready for performance run')
                for opened in [False, True]:
                    page.evaluate('(v)=>v?__panda.depthMap.open():__panda.depthMap.close()', opened)
                    page.wait_for_timeout(2000)
                    measured = page.evaluate('''() => new Promise(resolve=>{
                      const s=__panda.sim,d=__panda.depthMap,start=performance.now(),initial=d.metrics.frameCount;
                      const frames=[],costs=[],capture=[],color=[];let last=null;const original=s.render;
                      s.render=function(t){const begin=performance.now(),before=d.metrics.frameCount;original.call(this,t);
                        const end=performance.now();if(last!==null)frames.push(t-last);last=t;costs.push(end-begin);
                        if(d.metrics.frameCount>before){capture.push(d.metrics.captureMs);color.push(d.metrics.colorizeMs);}
                        if(end-start>=30000){s.render=original;
                          const q=(a,p)=>a.length?[...a].sort((x,y)=>x-y)[Math.min(a.length-1,Math.floor(a.length*p))]:null;
                          resolve({seconds:(end-start)/1000,medianFps:1000/q(frames,.5),p95FrameMs:q(costs,.95),
                            medianCaptureMs:q(capture,.5),p95CaptureMs:q(capture,.95),medianColorizeMs:q(color,.5),
                            depthHz:(d.metrics.frameCount-initial)*1000/(end-start),resolution:[d.width,d.height]});}
                      };
                    })''')
                    measured.update({'yolo': yolo, 'depth': opened})
                    results['performance'].append(measured)
                    print('PERF', json.dumps(measured), flush=True)
        else:
            page.locator('#tab-btn-cv').click()
            page.wait_for_function('__visionPipeline?.ready||__visionPipeline?.modelError', timeout=120000)
            check(page.evaluate('!!__visionPipeline.ready'), 'real YOLO ready')
        page.locator('#btn-depth-map').click() if page.locator('#depth-window').is_hidden() else None
        page.wait_for_function('__panda.depthMap.metrics.frameCount>2')
        page.wait_for_function('__visionPipeline.metrics.detections>0', timeout=30000)
        check(page.evaluate('__panda.depthMap.state==="open"&&__visionPipeline.camera.far===100'), 'depth and RGB/YOLO work together without changing RGB range')
        page.screenshot(path=str(OUT / 'depth-yolo.png'))
        check(not errors, 'no uncaught browser errors: ' + str(errors))
        if args.perf:
            for i in [0, 2]:
                baseline, active = results['performance'][i:i+2]
                check(active['depthHz'] >= 10, f'depth >=10Hz with yolo={active["yolo"]}')
                check(active['medianFps'] >= baseline['medianFps'] * .8, f'FPS degradation <=20% with yolo={active["yolo"]}')
        browser.close()
    (OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
