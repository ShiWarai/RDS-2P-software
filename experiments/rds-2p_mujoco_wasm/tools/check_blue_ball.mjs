import assert from "node:assert/strict";
import { selectBlueBall, blueBallCommand } from "../src/vision/blue-ball.js";
import { decodeYoloV8 } from "../src/vision/postprocess.js";
import { getLetterboxGeometry } from "../src/vision/preprocess.js";
import { BallFollower } from "../src/vision/ball-follower.js";

const blue={label:"blue_ball",confidence:.9,x1:280,y1:200,x2:360,y2:280};
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
const decoded=decodeYoloV8(output,[1,11,1],getLetterboxGeometry(640,480,320));
assert.equal(decoded[0].label,"blue_ball");
assert.equal(decoded[0].x1,288);
assert.equal(decoded[0].y1,208);
const legacy=new Float32Array(8);
assert.throws(()=>decodeYoloV8(legacy,[1,8,1],getLetterboxGeometry(640,480,320)),/channels/);

let finishLoad,starts=0,stops=0;
globalThis.window={__vision:{ensureStarted:async()=>({resume(){},waitUntilReady:async()=>{}}),pause(){}}};
globalThis.document={getElementById:()=>null};
const follower=Object.assign(Object.create(BallFollower.prototype),{
  generation:0,active:false,starting:false,
  button:{setAttribute(){},classList:{toggle(){}}},status:{textContent:""},
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
