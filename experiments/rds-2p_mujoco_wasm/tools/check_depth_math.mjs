import test from "node:test";
import assert from "node:assert/strict";
import {
  unpackDepth, depthToMeters, isDepthInRange, writeDepthColor, colorizeDepth,
  NO_DEPTH_COLOR, DEPTH_COLORS, MIN_DEPTH, MAX_DEPTH,
} from "../src/vision/depth-math.js";

test("known RGBA bytes and perspective projection values", () => {
  assert.equal(unpackDepth(new Uint8Array([128, 0, 0, 0])), 0.5);
  assert.equal(unpackDepth(new Uint8Array([0, 128, 0, 0])), 1 / 512);
  assert.equal(unpackDepth(new Uint8Array([0, 0, 128, 0])), 1 / 131072);
  assert.equal(unpackDepth(new Uint8Array([0, 0, 0, 255])), 1 / 16777216);
  assert(Number.isNaN(unpackDepth(new Uint8Array([255, 255, 255, 255]))));
  assert.equal(depthToMeters(0, 1, 3), 1);
  assert.equal(depthToMeters(0.75, 1, 3), 2);
  assert.equal(depthToMeters(0.5, 1, 3), 1.5);
  for (const d of [NaN, Infinity, -0.1, 1]) assert(Number.isNaN(depthToMeters(d, 1, 3)));
});

test("fixed colors, maximum inclusive, invalid values neutral", () => {
  const rgba = new Uint8ClampedArray(4);
  for (let i = 0; i < 5; i++) {
    writeDepthColor(MIN_DEPTH + i * (MAX_DEPTH - MIN_DEPTH) / 4, rgba);
    assert.deepEqual([...rgba], [...DEPTH_COLORS[i], 255]);
  }
  assert(isDepthInRange(0.6));
  assert(isDepthInRange(5));
  assert(isDepthInRange(5.0005));
  assert(!isDepthInRange(5.01));
  assert(!isDepthInRange(0));
  for (const z of [NaN, Infinity, -1, 0.59, 5.01]) {
    writeDepthColor(z, rgba);
    assert.deepEqual([...rgba], [...NO_DEPTH_COLOR, 255]);
  }
});

test("bottom-up readback flips vertically once, never horizontally", () => {
  // GPU bottom: depths 0 and .5; GPU top: .75 and missing.
  const raw = new Uint8Array([0,0,0,0, 128,0,0,0, 192,0,0,0, 255,255,255,255]);
  const meters = new Float32Array(4), rgba = new Uint8ClampedArray(16);
  colorizeDepth(raw, 2, 2, 1, 3, meters, rgba);
  assert.equal(meters[0], 2);
  assert(Number.isNaN(meters[1]));
  assert.equal(meters[2], 1);
  assert.equal(meters[3], 1.5);
  const expected = new Uint8ClampedArray(4);
  writeDepthColor(2, expected);
  assert.deepEqual([...rgba.slice(0, 4)], [...expected]);
  assert.deepEqual([...rgba.slice(4, 8)], [...NO_DEPTH_COLOR, 255]);
});
