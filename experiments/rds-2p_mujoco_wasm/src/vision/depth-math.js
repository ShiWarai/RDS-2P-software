export const MAX_DEPTH = 2;
export const DEPTH_EPSILON = 0.001;
export const NO_DEPTH_COLOR = [37, 43, 52];
export const DEPTH_COLORS = [
  [255, 64, 64], [255, 220, 64], [64, 210, 100], [64, 210, 240], [64, 96, 255],
];

/** Three.js 0.181.2 packing.glsl.js, RGBA8 bytes (not display colors). */
export function unpackDepth(bytes, offset = 0) {
  const r = bytes[offset], g = bytes[offset + 1], b = bytes[offset + 2], a = bytes[offset + 3];
  if (r === 255 && g === 255 && b === 255 && a === 255) return NaN;
  return r / 256 + g / 65536 + b / 16777216 + a / (255 * 16777216);
}

export function depthToMeters(depth, near, far) {
  if (!Number.isFinite(depth) || depth < 0 || depth >= 1) return NaN;
  return near * far / (far - depth * (far - near));
}

export function isDepthInRange(meters, near = 0.001) {
  return Number.isFinite(meters) && meters >= near && meters <= MAX_DEPTH + DEPTH_EPSILON;
}

/** Writes directly into the reused output array. */
export function writeDepthColor(meters, output, offset = 0, near = 0.001) {
  if (!isDepthInRange(meters, near)) {
    output.set(NO_DEPTH_COLOR, offset);
  } else {
    const t = Math.min(MAX_DEPTH, meters) * 2;
    const index = Math.min(3, Math.floor(t));
    const fraction = t - index;
    for (let channel = 0; channel < 3; channel++) {
      output[offset + channel] = Math.round(
        DEPTH_COLORS[index][channel] * (1 - fraction) + DEPTH_COLORS[index + 1][channel] * fraction
      );
    }
  }
  output[offset + 3] = 255;
}

/** GPU rows are bottom-up. Both arrays returned to callers use top-down rows. */
export function colorizeDepth(raw, width, height, near, far, meters, rgba) {
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const destination = y * width + x;
      const source = ((height - 1 - y) * width + x) * 4;
      const z = depthToMeters(unpackDepth(raw, source), near, far);
      meters[destination] = z;
      writeDepthColor(z, rgba, destination * 4, near);
    }
  }
}
