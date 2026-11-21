#!/usr/bin/env python3
"""Render labelled robot-camera frames; scene IDs are used ONLY for training labels.

pip install playwright pillow numpy onnxruntime
python tools/collect_ball_dataset.py --url http://localhost:8085 --count 450
"""
import argparse
import base64
import io
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['tree', 'bush', 'rock', 'flower', 'blue_ball', 'red_ball', 'green_ball']


def teacher_labels(session, encoded):
    image = Image.open(io.BytesIO(encoded)).convert('RGB')
    w, h = image.size
    canvas = Image.new('RGB', (640, 640), (114, 114, 114))
    canvas.paste(image.resize((640, 480)), (0, 80))
    tensor = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255
    output = session.run(None, {session.get_inputs()[0].name: tensor})[0][0].T
    candidates = []
    for row in output:
        cls = int(np.argmax(row[4:]))
        score = float(row[4 + cls])
        if score < .45:
            continue
        cx, cy, bw, bh = row[:4]
        x1, x2 = np.clip([cx - bw / 2, cx + bw / 2], 0, w)
        y1, y2 = np.clip([cy - bh / 2 - 80, cy + bh / 2 - 80], 0, h)
        if x2 > x1 and y2 > y1:
            candidates.append((score, cls, float(x1), float(y1), float(x2), float(y2)))
    selected = []
    for box in sorted(candidates, reverse=True):
        _, cls, x1, y1, x2, y2 = box
        duplicate = False
        for other in selected:
            _, oc, a, b, c, d = other
            intersection = max(0, min(x2, c) - max(x1, a)) * max(0, min(y2, d) - max(y1, b))
            union = (x2 - x1) * (y2 - y1) + (c - a) * (d - b) - intersection
            if cls == oc and intersection / max(union, 1e-6) > .45:
                duplicate = True
                break
        if not duplicate:
            selected.append(box)
    return [[cls, (x1 + x2) / (2*w), (y1 + y2) / (2*h), (x2-x1)/w, (y2-y1)/h]
            for _, cls, x1, y1, x2, y2 in selected]


SETUP = """async () => {
  const THREE = await import('three');
  const s = window.__panda.sim;
  s.renderer.setAnimationLoop(null);
  s.renderer.shadowMap.enabled = false;
  s.ballFollower?.dispose();
  const camera = new THREE.PerspectiveCamera(90, 640/480, .005, 20);
  const target = new THREE.WebGLRenderTarget(640,480);
  const pixels = new Uint8Array(640*480*4);
  const canvas = document.createElement('canvas'); canvas.width=640; canvas.height=480;
  const ctx=canvas.getContext('2d');
  const black=new THREE.MeshBasicMaterial({color:0});
  const masks=[0xff0000,0x00ff00,0x0000ff].map(color=>new THREE.MeshBasicMaterial({color}));
  const balls=['ball_blue','ball_red','ball_green'].map(name=>Object.values(s.bodies).find(b=>b.name===name));
  const meshes=[];s.scene.traverse(o=>{if(o.isMesh)meshes.push({o,material:o.material, mask:masks[balls.findIndex(b=>b.bodyID===o.bodyID)]||black});});
  window.collectFrame = (seed) => {
    let state=seed>>>0;const rand=()=>{state=(Math.imul(1664525,state)+1013904223)>>>0;return state/4294967296;};
    const range=(a,b)=>a+(b-a)*rand();
    const yaw=range(-Math.PI,Math.PI),x=range(-.7,.7),z=range(-.7,.7),height=range(.12,.26);
    camera.fov=range(75,100);camera.updateProjectionMatrix();
    camera.position.set(x,height,z);camera.lookAt(x+Math.cos(yaw),height+range(-.20,.08),z-Math.sin(yaw));
    s.hemiLight.intensity=range(.4,1.4);s.ambientLight.intensity=range(.12,.7);s.spotlight.intensity=range(.8,3);
    s.spotlight.position.set(range(-3,3),range(1,4),range(-3,3));
    balls.forEach((b,i)=>{
      const distance=range(.25,1.6),bearing=yaw+range(-1.05,1.05),r=range(.045,.09);
      b.position.set(x+Math.cos(bearing)*distance,r,z-Math.sin(bearing)*distance);
      b.scale.setScalar(r/.065);
      b.visible=rand()>.13;
      b.children[0].material.color.setRGB(...(i===0?[range(.02,.13),range(.08,.28),range(.65,1)] : i===1?[range(.65,1),range(.02,.14),range(.02,.12)]:[range(.02,.15),range(.6,1),range(.04,.25)]));
    });
    s.scene.updateMatrixWorld(true);
    s.renderer.outputColorSpace=THREE.SRGBColorSpace;s.renderer.toneMapping=THREE.NoToneMapping;
    s.renderer.setRenderTarget(target);s.renderer.clear();s.renderer.render(s.scene,camera);
    s.renderer.readRenderTargetPixels(target,0,0,640,480,pixels);
    const top=new Uint8ClampedArray(pixels.length);
    for(let y=0;y<480;y++)top.set(pixels.subarray((479-y)*640*4,(480-y)*640*4),y*640*4);
    ctx.putImageData(new ImageData(top,640,480),0,0);
    const jpeg=canvas.toDataURL('image/jpeg',.94).split(',')[1];
    const background=s.scene.background,fog=s.scene.fog;s.scene.background=new THREE.Color(0);s.scene.fog=null;
    meshes.forEach(({o,mask})=>o.material=mask);
    s.renderer.clear();s.renderer.render(s.scene,camera);s.renderer.readRenderTargetPixels(target,0,0,640,480,pixels);
    const boxes=balls.map(()=>({x1:640,y1:480,x2:0,y2:0,area:0}));
    for(let i=0;i<640*480;i++){
      const p=i*4,cls=pixels[p]>200&&pixels[p+1]<20&&pixels[p+2]<20?0:pixels[p+1]>200&&pixels[p]<20&&pixels[p+2]<20?1:pixels[p+2]>200&&pixels[p]<20&&pixels[p+1]<20?2:-1;
      if(cls<0)continue;const b=boxes[cls],px=i%640,py=479-Math.floor(i/640);
      b.x1=Math.min(b.x1,px);b.y1=Math.min(b.y1,py);b.x2=Math.max(b.x2,px+1);b.y2=Math.max(b.y2,py+1);b.area++;
    }
    meshes.forEach(({o,material})=>o.material=material);s.scene.background=background;s.scene.fog=fog;
    const labels=boxes.flatMap((b,i)=>b.area>=25&&b.x2-b.x1>=5&&b.y2-b.y1>=5?[[i+4,(b.x1+b.x2)/1280,(b.y1+b.y2)/960,(b.x2-b.x1)/640,(b.y2-b.y1)/480]]:[]);
    return {jpeg,labels,seed};
  };
}"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:8085')
    parser.add_argument('--count', type=int, default=450)
    parser.add_argument('--output', type=Path, default=ROOT / '.test/vision_training/dataset')
    args = parser.parse_args()
    options = ort.SessionOptions(); options.intra_op_num_threads = 4
    teacher = ort.InferenceSession(str(ROOT/'models/vision/yolov8n_final.onnx'), options, providers=['CPUExecutionProvider'])
    root = args.output.resolve()
    counts = dict.fromkeys(NAMES, 0)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True,
            args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 800, 'height': 600})
        page.goto(args.url, wait_until='domcontentloaded')
        page.wait_for_function('window.__panda?.sim?.ballFollower', timeout=60000)
        page.evaluate(SETUP)
        for index in range(args.count):
            split = 'val' if index % 10 == 8 else 'test' if index % 10 == 9 else 'train'
            for kind in ['images', 'labels']:
                (root/kind/split).mkdir(parents=True, exist_ok=True)
            seed = 317123 + index * 7919
            result = page.evaluate('(seed) => window.collectFrame(seed)', seed)
            encoded = base64.b64decode(result['jpeg'])
            labels = teacher_labels(teacher, encoded) + result['labels']
            (root/'images'/split/f'{seed}.jpg').write_bytes(encoded)
            (root/'labels'/split/f'{seed}.txt').write_text(''.join(' '.join(map(str,row))+'\n' for row in labels))
            for row in labels:
                counts[NAMES[int(row[0])]] += 1
            if index % 25 == 0:
                print(f'{index}/{args.count}: {counts}', flush=True)
        browser.close()
    (root/'data.yaml').write_text(f'path: {root.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\nnames: '+json.dumps(NAMES)+'\n')
    (root/'provenance.json').write_text(json.dumps(dict(count=args.count,counts=counts,seed=317123,
        labels='visible object-ID masks for balls; original YOLO pseudo-labels for four scenery classes',
        domain='synthetic MuJoCo camera; real-camera generalization has not been measured'),indent=2))
    print('Dataset complete',counts,flush=True)


if __name__ == '__main__':
    main()
