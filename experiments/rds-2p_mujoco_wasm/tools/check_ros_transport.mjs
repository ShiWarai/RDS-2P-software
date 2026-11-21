import assert from "node:assert/strict";
import { RosBallFollow } from "../src/vision/ros-ball-follow.js";

const sent=[];
class MockSocket {
  static OPEN=1;
  constructor() {
    this.readyState=0;
    queueMicrotask(()=>{
      this.readyState=1;this.onopen();
      this.onmessage({data:JSON.stringify({topic:"/ball_follow/status",msg:{data:JSON.stringify({ready:true,enabled:false,manual_source:"",inference_ms:20})}})});
    });
  }
  send(data) { sent.push(JSON.parse(data)); }
  close() { this.readyState=3;this.onclose(); }
}
globalThis.WebSocket=MockSocket;
let disconnected=0;
const remote=new RosBallFollow(()=>{},()=>{disconnected++;});
await remote.connect("ws://localhost:9090");
assert(remote.connected);
assert(sent.some(m=>m.op==="subscribe"&&m.topic==="/ball_follow/status"));
assert(!sent.some(m=>m.op==="publish"&&m.msg.data===true),"connecting must not arm motion");
remote.start();
assert(sent.some(m=>m.op==="publish"&&m.msg.data===true));
remote.lastStatusAt=performance.now()-1000;
await new Promise(resolve=>setTimeout(resolve,250));
assert.equal(sent.filter(m=>m.op==="publish").at(-1).msg.data,false,"stale ROS connection must disarm");
assert.equal(disconnected,1);
assert(!remote.connected);
await remote.connect("ws://localhost:9090");
remote.status.manual_source="joy";remote.lastStatusAt=performance.now();
assert.throws(()=>remote.start(),/joy/);
remote.close();
console.log("ROS transport: connect without motion, heartbeat, timeout and manual override passed");
