import assert from "node:assert/strict";
import { selectBlueBall, blueBallCommand } from "../src/vision/blue-ball.js";
import { decodeYoloV8, nonMaximumSuppression } from "../src/vision/postprocess.js";
import { getLetterboxGeometry, preprocessRgbaBottomUp } from "../src/vision/preprocess.js";
import { BallFollower } from "../src/vision/ball-follower.js";

const blue={label:"blue_ball",confidence:.9,x1:280,y1:200,x2:360,y2:280};
const green={classId:6,label:"green_ball",confidence:.92,x1:483,y1:250,x2:519,y2:284};
const falseBush={classId:1,label:"bush",confidence:.49,x1:482,y1:248,x2:521,y2:283};
assert.deepEqual(nonMaximumSuppression([falseBush,green]),[green],"one green ball must not also carry a weaker bush label");
const bush={...falseBush,confidence:.95};
assert.deepEqual(nonMaximumSuppression([green,bush]),[bush],"one bush must not also carry a weaker ball label");
const nearbyBush={...bush,x1:510,x2:590};
assert.equal(nonMaximumSuppression([nearbyBush,green]).length,2,"a nearby real bush and ball must both survive NMS");
const detection=selectBlueBall([blue,{...blue,label:"red_ball",x2:450}],640,480);
assert.equal(detection.centerX,.5);
assert.equal(selectBlueBall([{...blue,label:"tree"}],640,480),null);
assert.equal(selectBlueBall([{...blue,confidence:.2}],640,480),null);
assert.equal(selectBlueBall([{name:"ball_blue",bodyID:19}],640,480),null,"no simulator-object fallback");
assert(blueBallCommand(detection,100,100)[0]>0);
assert(blueBallCommand({...detection,centerX:.7},100,100)[2]<0);
assert(blueBallCommand({...detection,centerX:.3},100,100)[2]>0);
assert.equal(blueBallCommand({...detection,relativeWidth:.22},100,100)[0],0);
assert.equal(blueBallCommand({...detection,centerX:.95},100,100)[0],0);
assert.deepEqual(blueBallCommand(null,100,100),[0,0,0]);
assert.deepEqual(blueBallCommand(detection,801,100),[0,0,0]);
const output=new Float32Array(11);output.set([160,160,32,32]);output[8]=.9;
const decoded=decodeYoloV8(output,[1,11,1],getLetterboxGeometry(640,480,320,320));
assert.equal(decoded[0].label,"blue_ball");
assert.equal(decoded[0].x1,288);
assert.equal(decoded[0].y1,208);
const legacy=new Float32Array(8);
assert.throws(()=>decodeYoloV8(legacy,[1,8,1],getLetterboxGeometry(640,480,320,320)),/channels/);

const nativeGeometry=getLetterboxGeometry(640,480);
assert.equal(nativeGeometry.scaleX,1);
assert.equal(nativeGeometry.scaleY,1);
assert.equal(nativeGeometry.padLeft,0);
assert.equal(nativeGeometry.padTop,0);
const nativeOutput=new Float32Array(11);nativeOutput.set([320,240,80,80]);nativeOutput[8]=.9;
assert.deepEqual(decodeYoloV8(nativeOutput,[1,11,1],nativeGeometry)[0],
  {...blue,classId:4,confidence:nativeOutput[8]});
// Every sensor pixel survives the bottom-up -> NCHW conversion, without padding.
const pixels=new Uint8Array(640*480*4);
for(let y=0;y<480;y++)for(let x=0;x<640;x++) {
  const i=(y*640+x)*4;pixels.set([x%256,y%256,(x+y)%256,255],i);
}
const prepared=preprocessRgbaBottomUp(pixels,640,480);
assert.equal(prepared.data.length,3*640*480);
for(let y=0;y<480;y++)for(let x=0;x<640;x++) {
  const src=((479-y)*640+x)*4,dst=y*640+x;
  for(let c=0;c<3;c++)assert(Math.abs(prepared.data[c*640*480+dst]-pixels[src+c]/255)<1e-7);
}

let finishLoad,starts=0,stops=0;
globalThis.window={__vision:{ensureStarted:async()=>({resume(){},waitUntilReady:async()=>{}}),pause(){}}};
globalThis.document={getElementById:()=>null};
const follower=Object.assign(Object.create(BallFollower.prototype),{
  generation:0,active:false,starting:false,color:"blue",
  button:{style:{setProperty(){}},setAttribute(){},classList:{toggle(){}}},status:{textContent:""},
  sim:{paused:false,policy:{load:()=>new Promise(resolve=>{finishLoad=resolve;})},
    player:{stop(){},startPolicy(){starts++;},stopPolicy(){stops++;},notifyActive(){}}},
});
const loading=follower.start();
await new Promise(resolve=>setImmediate(resolve));
assert(follower.starting);
follower.stop();finishLoad(true);await loading;
assert.equal(starts,0,"cancelled model load must not start walking");
follower.sim.policy.load=async()=>true;await follower.start();assert(follower.active);
follower.stop();assert.equal(stops,1);
follower.sim.paused=true;await follower.start();assert.equal(starts,1);
console.log("YOLO-only selection, decoding, following and cancellation checks passed");
