
import { ASTRA_MINI_PRO } from "./astra-mini-pro.js";

export const MODEL_WIDTH = ASTRA_MINI_PRO.width;
export const MODEL_HEIGHT = ASTRA_MINI_PRO.height;

/**
 * Геометрия letterbox.
 * Координаты source -> прямоугольный вход модели.
 */
export function getLetterboxGeometry(sourceWidth, sourceHeight, targetWidth = MODEL_WIDTH, targetHeight = MODEL_HEIGHT) {
  if (sourceWidth <= 0 || sourceHeight <= 0 || targetWidth <= 0 || targetHeight <= 0) {
    throw new Error("Некорректные размеры изображения");
  }

  const scale = Math.min(targetWidth / sourceWidth, targetHeight / sourceHeight);
  const resizedWidth = Math.max(1, Math.round(sourceWidth * scale));
  const resizedHeight = Math.max(1, Math.round(sourceHeight * scale));

  return {
    scale,
    scaleX: resizedWidth / sourceWidth,
    scaleY: resizedHeight / sourceHeight,
    resizedWidth,
    resizedHeight,
    padLeft: Math.floor((targetWidth - resizedWidth) / 2),
    padTop: Math.floor((targetHeight - resizedHeight) / 2),
    targetWidth,
    targetHeight,
    sourceWidth,
    sourceHeight,
  };
}

/**
 * RGBA из WebGL readRenderTargetPixels (bottom-up)
 * -> RGB Float32 NCHW, нормализация [0, 1].
 *
 * @param {Uint8Array|Uint8ClampedArray} rgba
 * @param {number} width
 * @param {number} height
 * @param {number} targetWidth
 * @param {number} targetHeight
 * @returns {{data: Float32Array, geometry: object}}
 */
export function preprocessRgbaBottomUp(
  rgba,
  width,
  height,
  targetWidth = MODEL_WIDTH,
  targetHeight = MODEL_HEIGHT
) {
  if (!rgba || rgba.length !== width * height * 4) {
    throw new Error("Неверный размер RGBA-буфера");
  }

  const geometry = getLetterboxGeometry(width, height, targetWidth, targetHeight);
  const planeSize = targetWidth * targetHeight;
  const output = new Float32Array(planeSize * 3);

  // Цвет фона letterbox — 114/255, как в стандартной YOLO-предобработке.
  output.fill(114 / 255);

  const { resizedWidth, resizedHeight, padLeft, padTop, scaleX, scaleY } =
    geometry;

  for (let dy = 0; dy < resizedHeight; dy++) {
    const sourceYTop = Math.min(
      height - 1,
      Math.max(0, Math.round((dy + 0.5) / scaleY - 0.5))
    );

    // WebGL readPixels: нижняя строка находится первой.
    const sourceYBottomUp = height - 1 - sourceYTop;

    for (let dx = 0; dx < resizedWidth; dx++) {
      const sourceX = Math.min(
        width - 1,
        Math.max(0, Math.round((dx + 0.5) / scaleX - 0.5))
      );

      const sourceIndex = (sourceYBottomUp * width + sourceX) * 4;
      const destIndex = (dy + padTop) * targetWidth + dx + padLeft;

      output[destIndex] = rgba[sourceIndex] / 255;
      output[planeSize + destIndex] = rgba[sourceIndex + 1] / 255;
      output[planeSize * 2 + destIndex] = rgba[sourceIndex + 2] / 255;
    }
  }

  return { data: output, geometry };
}
