
export const MODEL_LABELS = [
  "tree",
  "bush",
  "rock",
  "flower",
];

export function boxIoU(a, b) {
  const x1 = Math.max(a.x1, b.x1);
  const y1 = Math.max(a.y1, b.y1);
  const x2 = Math.min(a.x2, b.x2);
  const y2 = Math.min(a.y2, b.y2);

  const intersection =
    Math.max(0, x2 - x1) * Math.max(0, y2 - y1);

  const areaA =
    Math.max(0, a.x2 - a.x1) *
    Math.max(0, a.y2 - a.y1);

  const areaB =
    Math.max(0, b.x2 - b.x1) *
    Math.max(0, b.y2 - b.y1);

  const union = areaA + areaB - intersection;

  return union > 0 ? intersection / union : 0;
}

export function nonMaximumSuppression(
  candidates,
  iouThreshold = 0.45,
  maxDetections = 50
) {
  if (!Array.isArray(candidates) || candidates.length === 0) {
    return [];
  }

  const sorted = [...candidates].sort(
    (a, b) => b.confidence - a.confidence
  );

  const selected = [];

  while (
    sorted.length > 0 &&
    selected.length < maxDetections
  ) {
    const best = sorted.shift();
    selected.push(best);

    for (let i = sorted.length - 1; i >= 0; i--) {
      if (sorted[i].classId !== best.classId) {
        continue;
      }

      if (boxIoU(best, sorted[i]) > iouThreshold) {
        sorted.splice(i, 1);
      }
    }
  }

  return selected;
}

export function decodeYoloV8(
  outputData,
  outputDims,
  geometry,
  options = {}
) {
  const {
    confidenceThreshold = 0.35,
    iouThreshold = 0.45,
    maxDetections = 50,
  } = options;

  if (
    !outputData ||
    !outputDims ||
    outputDims.length !== 3
  ) {
    throw new Error("Неверная форма выходного тензора YOLO");
  }

  const [, dim1, dim2] = outputDims;

    const expectedChannels = 4 + MODEL_LABELS.length;

  const channelMajor =
    dim1 === expectedChannels ||
    (dim2 !== expectedChannels && dim1 < dim2);

  const channels = channelMajor ? dim1 : dim2;
  const predictions = channelMajor ? dim2 : dim1;

  if (channels !== expectedChannels) {
    throw new Error(`Expected ${expectedChannels} YOLO channels, received ${channels}`);
  }

  const getValue = (prediction, channel) => {
    return channelMajor
      ? outputData[channel * predictions + prediction]
      : outputData[prediction * channels + channel];
  };

  const candidates = [];

  for (let i = 0; i < predictions; i++) {
    const cx = getValue(i, 0);
    const cy = getValue(i, 1);
    const w = getValue(i, 2);
    const h = getValue(i, 3);

    if (
      !Number.isFinite(cx) ||
      !Number.isFinite(cy) ||
      !Number.isFinite(w) ||
      !Number.isFinite(h) ||
      w <= 0 ||
      h <= 0
    ) {
      continue;
    }

    let bestClass = -1;
    let bestScore = 0;

    for (let c = 0; c < MODEL_LABELS.length; c++) {
      const score = getValue(i, c + 4);

      if (score > bestScore) {
        bestScore = score;
        bestClass = c;
      }
    }

    if (
      bestScore < confidenceThreshold ||
      bestClass < 0
    ) {
      continue;
    }

    const x1Model = cx - w / 2;
    const y1Model = cy - h / 2;
    const x2Model = cx + w / 2;
    const y2Model = cy + h / 2;

    const x1 =
      (x1Model - geometry.padLeft) / geometry.scaleX;

    const y1 =
      (y1Model - geometry.padTop) / geometry.scaleY;

    const x2 =
      (x2Model - geometry.padLeft) / geometry.scaleX;

    const y2 =
      (y2Model - geometry.padTop) / geometry.scaleY;

    const clampX = (v) =>
      Math.max(0, Math.min(geometry.sourceWidth, v));

    const clampY = (v) =>
      Math.max(0, Math.min(geometry.sourceHeight, v));

    const box = {
      x1: clampX(x1),
      y1: clampY(y1),
      x2: clampX(x2),
      y2: clampY(y2),

      confidence: bestScore,
      classId: bestClass,
      label: MODEL_LABELS[bestClass],
    };

    if (
      box.x2 > box.x1 &&
      box.y2 > box.y1
    ) {
      candidates.push(box);
    }
  }

  return nonMaximumSuppression(
    candidates,
    iouThreshold,
    maxDetections
  );
}
