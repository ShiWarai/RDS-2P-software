#!/usr/bin/env python3
"""Exercise the real-robot UI against a mock rosbridge; never connects to hardware."""
import base64
import io
import json
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main():
    image=Image.open(ROOT/'.test/vision_training/browser/camera_raw.png').convert('RGB')
    encoded=io.BytesIO();image.save(encoded,format='JPEG')
    jpeg=base64.b64encode(encoded.getvalue()).decode()
    state=dict(enabled=False,manual_source='')
    target=dict(label='blue_ball',confidence=.95,relativeWidth=.08,centerX=.5)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        routes=[]

        def status(ws):
            ws.send(json.dumps(dict(op='publish',topic='/ball_follow/status',msg=dict(data=json.dumps(
                dict(ready=True,enabled=state['enabled'],target=target,inference_ms=20,error=None,manual_source=state['manual_source']))))))

        def frame(ws):
            ws.send(json.dumps(dict(op='publish',topic='/ball_follow/image/compressed',msg=dict(format='jpeg',data=jpeg))))

        def connect(ws):
            routes.append(ws)

            def receive(raw):
                message=json.loads(raw)
                if message['op']=='subscribe':
                    if message['topic']=='/ball_follow/status':
                        status(ws)
                    elif message['topic']=='/ball_follow/image/compressed':
                        frame(ws)
                if message['op']=='publish' and message['topic']=='/ball_follow/enable':
                    state['enabled']=message['msg']['data'] and not state['manual_source']
                    status(ws);frame(ws)
            ws.on_message(receive)

        page.route_web_socket(lambda url:'robot.test:9090' in url,connect)
        page.goto('http://localhost:8085/',wait_until='domcontentloaded')
        page.wait_for_function('window.__panda?.sim?.ballFollower')
        page.locator('#robot-connection summary').click()
        page.locator('#robot-rosbridge-url').fill('ws://robot.test:9090')
        page.locator('#btn-robot-connect').click()
        page.wait_for_function('window.__panda.sim.ballFollower.remote?.connected')
        assert not state['enabled'],'connection alone must not start the real robot'
        page.locator('#tab-btn-cv').click()
        page.locator('#btn-follow-blue').click()
        page.wait_for_function('window.__panda.sim.ballFollower.active')
        assert not page.evaluate('window.__panda.sim.player.policyOn'),'real mode must not drive simulation'
        assert state['enabled']
        page.wait_for_function("document.querySelector('#vision-mount img')?.naturalWidth>0")
        page.screenshot(path=str(ROOT/'.test/vision_training/browser/ros-preview.png'),full_page=True)
        state['manual_source']='joy';state['enabled']=False;status(routes[0])
        page.wait_for_function('!window.__panda.sim.ballFollower.active',timeout=4000)
        state['manual_source']='';status(routes[0])
        page.locator('#btn-follow-blue').click()
        page.wait_for_function('window.__panda.sim.ballFollower.active')
        page.keyboard.press('Escape')
        page.wait_for_function('!window.__panda.sim.ballFollower.active')
        assert not state['enabled']
        page.locator('#btn-robot-connect').click()
        page.wait_for_function('!window.__panda.sim.ballFollower.remote')
        assert not errors,errors
        browser.close()
    print('Mock ROS browser: connect without motion, real preview, robot-only command, manual override, Esc/disconnect passed')


if __name__=='__main__':
    main()
