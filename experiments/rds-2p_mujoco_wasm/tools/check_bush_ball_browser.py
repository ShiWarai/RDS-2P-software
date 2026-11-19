#!/usr/bin/env python3
"""Regression: a visible bush stays a bush with no balls or genuine balls nearby."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def iou(a,b):
    area=max(0,min(a['x2'],b['x2'])-max(a['x1'],b['x1']))*max(0,min(a['y2'],b['y2'])-max(a['y1'],b['y1']))
    union=(a['x2']-a['x1'])*(a['y2']-a['y1'])+(b['x2']-b['x1'])*(b['y2']-b['y1'])-area
    return area/max(union,1e-9)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://localhost:8085')
    parser.add_argument('--model',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'.test/bush_ball/browser')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chrome')
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        if args.model:
            page.route('**/models/vision/yolov8n_balls.onnx*',lambda route:route.fulfill(path=str(args.model.resolve()),content_type='application/octet-stream'))
        page.goto(args.url+'/?backend=wasm',wait_until='domcontentloaded')
        page.wait_for_function('window.__panda?.depthMap',timeout=60000)
        page.evaluate('''() => {const s=__panda.sim;s.setPaused(true);s.renderer.shadowMap.enabled=false;s.renderer.setSize(400,300,false);}''')
        page.locator('#tab-btn-cv').click()
        page.wait_for_function('window.__visionPipeline?.ready||window.__visionPipeline?.modelError',timeout=120000)
        assert page.evaluate('__visionPipeline.ready'),page.evaluate('String(__visionPipeline.modelError)')
        page.evaluate('''async () => {
          const THREE=await import('three'),s=__panda.sim;
          window.regressionBalls=['ball_blue','ball_red','ball_green'].map(name=>Object.values(s.bodies).find(b=>b.name===name));
          window.regressionBush=s.zoo.children.find(o=>o.geometry?.type==='SphereGeometry'&&Math.abs(o.position.x-1.4)<.01&&Math.abs(o.position.z-.3)<.01);
          if(!regressionBush)throw Error('Expected bush missing from scene');
          window.regressionBounds=obj=>{
            const camera=__visionPipeline.camera;camera.updateWorldMatrix(true,false);obj.updateWorldMatrix(true,true);
            let x1=640,y1=480,x2=0,y2=0;
            obj.traverse(o=>{if(!o.isMesh)return;const vertices=o.geometry.attributes.position;
              for(let i=0;i<vertices.count;i++){
                const v=new THREE.Vector3().fromBufferAttribute(vertices,i).applyMatrix4(o.matrixWorld);
                if(v.clone().applyMatrix4(camera.matrixWorldInverse).z>=0)continue;
                v.project(camera);const x=(v.x+1)*320,y=(1-v.y)*240;
                x1=Math.min(x1,x);x2=Math.max(x2,x);y1=Math.min(y1,y);y2=Math.max(y2,y);
              }});
            return {x1:Math.max(0,x1),y1:Math.max(0,y1),x2:Math.min(640,x2),y2:Math.min(480,y2)};
          };
        }''')
        cases=[]
        settings=[('original_scene',0,-2),('bush_only_center',0,-1),('bush_only_left',-.15,-1),('bush_only_right',.15,-1),
                  ('bush_and_blue',0,0),('bush_and_red',0,1),('bush_and_green',0,2)]
        for name,yaw,ball in settings:
            changed=page.evaluate('''args=>{
              const s=__panda.sim;regressionBalls.forEach((b,i)=>b.visible=args.ball===-2||i===args.ball);
              s.data.qpos[3]=Math.cos(args.yaw/2);s.data.qpos[4]=0;s.data.qpos[5]=0;s.data.qpos[6]=Math.sin(args.yaw/2);
              if(args.ball>=0){const body=regressionBalls[args.ball],joint=s.model.body_jntadr[body.bodyID],address=s.model.jnt_qposadr[joint];
                s.data.qpos[address]=.95;s.data.qpos[address+1]=.15;s.data.qpos[address+2]=.065;}
              s.mujoco.mj_forward(s.model,s.data);return performance.now();
            }''',dict(yaw=yaw,ball=ball))
            page.wait_for_function('time=>__panda.sim.ballFollower.capturedAt>time+100&&!__visionPipeline.workerBusy',arg=changed,timeout=30000)
            result=page.evaluate('''index=>({bush:regressionBounds(regressionBush),ball:index<0?null:regressionBounds(regressionBalls[index]),detections:__visionPipeline.latestDetections})''',ball)
            predictions=result['detections']
            found=any(d['label']=='bush' and iou(d,result['bush'])>=.4 for d in predictions)
            wrong=[d for d in predictions if d['label'].endswith('_ball') and iou(d,result['bush'])>=.3]
            real_ball=ball<0 or any(d['label']==['blue_ball','red_ball','green_ball'][ball] and iou(d,result['ball'])>=.4 for d in predictions)
            case=dict(name=name,bush_found=found,bush_as_ball=wrong,real_ball_found=real_ball,**result)
            cases.append(case)
            print(name,dict(bush_found=found,bush_as_ball=len(wrong),real_ball_found=real_ball),flush=True)
            page.evaluate("document.querySelectorAll('.toast').forEach(n=>n.remove())")
            page.screenshot(path=str(args.output/f'{name}.png'))
        passed=all(c['bush_found'] and not c['bush_as_ball'] and c['real_ball_found'] for c in cases) and not errors
        report=dict(passed=passed,cases=cases,errors=errors)
        (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        browser.close()
        assert passed,'Bush/ball confusion remains; inspect '+str(args.output/'report.json')
    print('PASS bush/ball distinction in all seven browser cases',flush=True)


if __name__=='__main__':
    main()
