import * as THREE from "three";
import { DepthMap } from "../src/vision/depth-map.js";

const checks = [];
function assert(condition, name) {
  if (!condition) throw new Error(name);
  checks.push(name);
}
const near = (actual, expected) => Math.abs(actual - expected) <= 0.02;

try {
  const renderer = new THREE.WebGLRenderer();
  renderer.setSize(400, 300);
  renderer.setClearColor(0x123456, 0.4);
  renderer.setViewport(3, 4, 250, 180);
  renderer.setScissor(4, 5, 230, 170);
  renderer.setScissorTest(true);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0.5, 0.8, 1);
  scene.fog = new THREE.Fog(0x123456, 0.1, 1);
  const base = new THREE.Group(); base.name = "base_link"; scene.add(base);
  const map = new DepthMap({ renderer, scene, bodies: { 1: base } }, document.querySelector("#depth"));
  map.open();
  const camera = map.camera;
  // Fixture alone aligns its sensor with -Z, so plane depth is independently known.
  camera.position.set(0, 0, 0); camera.quaternion.identity();
  const material = new THREE.MeshBasicMaterial();
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(10, 10), material);
  scene.add(plane);
  const sample = (x, y) => map.depthMeters[y * map.width + x];
  const color = (x, y) => [...map.image.data.slice(4 * (y * map.width + x), 4 * (y * map.width + x) + 3)];
  function state() {
    return JSON.stringify({
      target: renderer.getRenderTarget()?.uuid, viewport: renderer.getViewport(new THREE.Vector4()).toArray(),
      scissor: renderer.getScissor(new THREE.Vector4()).toArray(), test: renderer.getScissorTest(),
      clear: renderer.getClearColor(new THREE.Color()).toArray(), alpha: renderer.getClearAlpha(),
      auto: renderer.autoClear, output: renderer.outputColorSpace, tone: renderer.toneMapping,
      shadow: renderer.shadowMap.autoUpdate, background: scene.background?.getHex(), fog: scene.fog?.color.getHex(),
      override: scene.overrideMaterial?.uuid,
      actualViewport: Array.from(renderer.getContext().getParameter(renderer.getContext().VIEWPORT)),
      actualScissor: Array.from(renderer.getContext().getParameter(renderer.getContext().SCISSOR_BOX)),
      actualScissorTest: renderer.getContext().isEnabled(renderer.getContext().SCISSOR_TEST),
    });
  }
  const saved = state();
  assert(map.width === 640 && map.height === 480, "native 640x480 sensor resolution");
  assert(near(2 * Math.atan(1 / camera.projectionMatrix.elements[0]) * 180 / Math.PI, 58.4), "horizontal FOV 58.4 degrees");
  assert(near(2 * Math.atan(1 / camera.projectionMatrix.elements[5]) * 180 / Math.PI, 45.5), "vertical FOV 45.5 degrees");
  for (const z of [0.6, 1, 2.8, 5]) {
    plane.position.z = -z;
    map.capture();
    assert(near(sample(320, 240), z), `center depth ${z}m (${sample(320,240)})`);
    assert(near(sample(20, 20), z) && near(sample(620, 460), z), `axial edge depth ${z}m`);
  }
  for (const z of [0.59, 5.01]) {
    plane.position.z = -z; map.capture();
    assert(JSON.stringify(color(320, 240)) === "[37,43,52]", `${z}m neutral`);
  }
  plane.visible = false; map.capture();
  assert([...map.depthMeters].every(Number.isNaN), "empty sky is missing depth");
  plane.visible = true; plane.position.z = -1.5;
  const front = new THREE.Mesh(new THREE.PlaneGeometry(0.4, 0.4), material);
  front.position.set(-0.3, 0.3, -0.8); scene.add(front);
  map.capture();
  assert(near(sample(105, 25), 0.8), "top-left near occluder orientation");
  assert(near(sample(530, 450), 1.5), "bottom-right far background orientation");
  // Too-close surfaces must mask valid background rather than being clipped away.
  front.position.set(0, 0, -0.3); map.capture();
  assert(near(sample(320, 240), 0.3) && JSON.stringify(color(320, 240)) === "[37,43,52]", "close occluder masks background");
  assert(state() === saved, "renderer state restored on success");
  const read = renderer.readRenderTargetPixels;
  renderer.readRenderTargetPixels = () => { throw new Error("injected readback failure"); };
  let caught = false;
  try { map.capture(); } catch (error) { caught = /injected/.test(error.message); }
  renderer.readRenderTargetPixels = read;
  assert(caught && state() === saved, "renderer state restored on failure");
  const priorTarget = new THREE.WebGLRenderTarget(200, 180);
  priorTarget.viewport.set(2, 3, 100, 120);
  priorTarget.scissor.set(8, 9, 80, 90);
  priorTarget.scissorTest = true;
  renderer.setRenderTarget(priorTarget);
  const targetSaved = state();
  map.capture();
  assert(state() === targetSaved, "active target viewport/scissor restored");
  renderer.readRenderTargetPixels = () => { throw new Error("injected target failure"); };
  try { map.capture(); } catch (error) { assert(/injected/.test(error.message), "target failure propagated"); }
  renderer.readRenderTargetPixels = read;
  assert(state() === targetSaved, "active target state restored on failure");
  renderer.setRenderTarget(null); priorTarget.dispose();
  for (let i = 0; i < 20; i++) { map.close(); map.open(); }
  assert(base.children.filter(child => child.name === "robot-depth-camera").length === 1, "20 cycles one camera");
  map.close(); const count = map.metrics.frameCount; map.update(performance.now());
  assert(map.metrics.frameCount === count, "closed map captures nothing");
  map.dispose(); map.dispose();
  assert(base.children.length === 0, "idempotent disposal removes camera");
  front.geometry.dispose(); plane.geometry.dispose(); material.dispose(); renderer.dispose();
  window.depthResults = { passed: true, checks };
} catch (error) {
  window.depthResults = { passed: false, checks, error: error.stack };
}
document.querySelector("#result").textContent = JSON.stringify(window.depthResults, null, 2);
