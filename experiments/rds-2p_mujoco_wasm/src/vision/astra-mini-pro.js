// Orbbec Astra Mini Pro (long range), not Astra Mini S Pro.
// https://www.orbbec.com/products/structured-light-camera/astra-mini-pro-series/
export const ASTRA_MINI_PRO = Object.freeze({
  model: "Orbbec Astra Mini Pro",
  width: 640,
  height: 480,
  fps: 30,
  dimensionsMm: Object.freeze({ width: 84.9, height: 20, depth: 19.92 }),
  depth: Object.freeze({ horizontalFov: 58.4, verticalFov: 45.5, min: 0.6, max: 5 }),
  rgb: Object.freeze({ horizontalFov: 62, verticalFov: 49 }),
});
