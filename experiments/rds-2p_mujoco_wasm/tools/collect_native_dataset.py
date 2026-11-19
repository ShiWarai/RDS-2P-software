#!/usr/bin/env python3
"""Training-only instance masks for all seven classes at Astra RGB H62/V49."""
import argparse
import base64
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['tree', 'bush', 'rock', 'flower', 'blue_ball', 'red_ball', 'green_ball']

SETUP = r"""async () => {
  const THREE=await import('three'),s=__panda.sim;
  s.renderer.setAnimationLoop(null);s.setPaused(true);s.renderer.shadowMap.enabled=false;
  s.ballFollower.dispose();
  const camera=new THREE.PerspectiveCamera(49,640/480,.001,20);
  camera.projectionMatrix.elements[0]=1/Math.tan(62*Math.PI/360);
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
  const target=new THREE.WebGLRenderTarget(640,480),pixels=new Uint8Array(640*480*4);
  const canvas=document.createElement('canvas');canvas.width=640;canvas.height=480;
  const context=canvas.getContext('2d'),instances=[],membership=new Map();
  const add=(nodes,cls)=>{
    const id=instances.length+1,material=new THREE.MeshBasicMaterial({toneMapped:false});
    material.color.setRGB((id&255)/255,((id>>8)&255)/255,((id>>16)&255)/255);
    instances.push({id,cls,material});
    for(const node of nodes)node.traverse(o=>{if(o.isMesh)membership.set(o,id);});
  };
  const zoo=s.zoo.children;
  const trees=zoo.filter(o=>o.isGroup&&o.children.some(c=>c.geometry?.type==='ConeGeometry'));
  const bushes=zoo.filter(o=>o.geometry?.type==='SphereGeometry'&&o.geometry.parameters.radius>.08);
  const rocks=zoo.filter(o=>o.geometry?.type==='DodecahedronGeometry');
  const stems=zoo.filter(o=>o.geometry?.type==='CylinderGeometry');
  const heads=zoo.filter(o=>o.geometry?.type==='SphereGeometry'&&o.geometry.parameters.radius<.04);
  if(trees.length!==6||bushes.length!==6||rocks.length!==3||stems.length!==26||heads.length!==26)
    throw Error('Scene layout changed: training instance labels need review');
  trees.forEach(o=>add([o],0));bushes.forEach(o=>add([o],1));rocks.forEach(o=>add([o],2));
  for(const stem of stems){const head=heads.find(h=>h.position.x===stem.position.x&&h.position.z===stem.position.z);
    if(!head)throw Error('Flower has no matching head');add([stem,head],3);}
  const balls=['ball_blue','ball_red','ball_green'].map(name=>Object.values(s.bodies).find(b=>b.name===name));
  balls.forEach((o,i)=>add([o],i+4));
  const black=new THREE.MeshBasicMaterial({color:0,toneMapped:false}),meshes=[];
  s.scene.traverse(o=>{if(o.isMesh)meshes.push({o,material:o.material,id:membership.get(o)||0});});
  window.nativeTrainingFrame=seed=>{
    let state=seed>>>0;const rand=()=>{state=(Math.imul(1664525,state)+1013904223)>>>0;return state/4294967296;};
    const range=(a,b)=>a+(b-a)*rand(),nearHome=rand()<.45;
    const yaw=nearHome?range(-1.4,1.4):range(-Math.PI,Math.PI);
    const x=nearHome?range(-.15,.4):range(-.7,.7),z=nearHome?range(-.3,.3):range(-.7,.7),height=range(.13,.21);
    camera.position.set(x,height,z);camera.lookAt(x+Math.cos(yaw),height+range(-.09,.035),z-Math.sin(yaw));
    s.hemiLight.intensity=range(.65,1.2);s.ambientLight.intensity=range(.2,.55);s.spotlight.intensity=range(1.4,2.8);
    balls.forEach((b,i)=>{const distance=range(.35,1.7),bearing=yaw+range(-.85,.85),radius=range(.045,.085);
      b.position.set(x+Math.cos(bearing)*distance,radius,z-Math.sin(bearing)*distance);b.scale.setScalar(radius/.065);
      b.visible=rand()>.12;});
    s.scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);
    s.renderer.setRenderTarget(target);s.renderer.outputColorSpace=THREE.SRGBColorSpace;s.renderer.toneMapping=THREE.NoToneMapping;
    s.renderer.clear();s.renderer.render(s.scene,camera);s.renderer.readRenderTargetPixels(target,0,0,640,480,pixels);
    const top=new Uint8ClampedArray(pixels.length);
    for(let y=0;y<480;y++)top.set(pixels.subarray((479-y)*640*4,(480-y)*640*4),y*640*4);
    context.putImageData(new ImageData(top,640,480),0,0);
    const jpeg=canvas.toDataURL('image/jpeg',.95).split(',')[1];
    const background=s.scene.background,fog=s.scene.fog;s.scene.background=new THREE.Color(0);s.scene.fog=null;
    for(const {o,id} of meshes)o.material=id?instances[id-1].material:black;
    s.renderer.outputColorSpace=THREE.LinearSRGBColorSpace;s.renderer.clear();s.renderer.render(s.scene,camera);
    s.renderer.readRenderTargetPixels(target,0,0,640,480,pixels);
    const boxes=instances.map(o=>({...o,x1:640,y1:480,x2:0,y2:0,area:0}));
    for(let i=0;i<640*480;i++){const p=i*4,id=pixels[p]+(pixels[p+1]<<8)+(pixels[p+2]<<16);
      if(!id||id>boxes.length)continue;const b=boxes[id-1],px=i%640,py=479-Math.floor(i/640);
      b.x1=Math.min(b.x1,px);b.x2=Math.max(b.x2,px+1);b.y1=Math.min(b.y1,py);b.y2=Math.max(b.y2,py+1);b.area++;}
    for(const {o,material} of meshes)o.material=material;s.scene.background=background;s.scene.fog=fog;
    const labels=boxes.filter(b=>b.area>=25&&b.x2-b.x1>=5&&b.y2-b.y1>=5).map(b=>
      [b.cls,(b.x1+b.x2)/1280,(b.y1+b.y2)/960,(b.x2-b.x1)/640,(b.y2-b.y1)/480]);
    return {jpeg,labels,seed};
  };
}"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:8085')
    parser.add_argument('--count', type=int, default=180)
    parser.add_argument('--output', type=Path, default=ROOT/'.test/vision_regression/native_dataset')
    args = parser.parse_args()
    root = args.output.resolve()
    if (root/'data.yaml').exists():
        raise ValueError('Choose a fresh dataset directory')
    counts = dict.fromkeys(NAMES, 0)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome')
        page = browser.new_page(viewport={'width': 800, 'height': 600})
        page.goto(args.url, wait_until='domcontentloaded')
        page.wait_for_function('window.__panda?.sim?.ballFollower', timeout=60000)
        page.evaluate(SETUP)
        for index in range(args.count):
            split = 'val' if index % 10 == 8 else 'test' if index % 10 == 9 else 'train'
            for kind in ['images', 'labels']:
                (root/kind/split).mkdir(parents=True, exist_ok=True)
            seed = 986321+index*4597
            frame = page.evaluate('seed=>nativeTrainingFrame(seed)', seed)
            (root/'images'/split/f'native-{seed}.jpg').write_bytes(base64.b64decode(frame['jpeg']))
            (root/'labels'/split/f'native-{seed}.txt').write_text(
                ''.join(' '.join(map(str, row))+'\n' for row in frame['labels']), encoding='utf-8')
            for row in frame['labels']:
                counts[NAMES[int(row[0])]] += 1
            if index % 30 == 0:
                print(index, counts, flush=True)
        browser.close()
    (root/'data.yaml').write_text('path: '+root.as_posix()+'\ntrain: images/train\nval: images/val\ntest: images/test\nnames: '+json.dumps(NAMES)+'\n', encoding='utf-8')
    (root/'provenance.json').write_text(json.dumps(dict(count=args.count, counts=counts,
        fov=dict(horizontal=62, vertical=49), resolution=[640, 480], seed=986321,
        labels='Visible instance masks for all seven classes; no teacher predictions.',
        domain='Synthetic scene; instance IDs are used only for training labels.'), indent=2), encoding='utf-8')
    print(root, counts, flush=True)


if __name__ == '__main__':
    main()
