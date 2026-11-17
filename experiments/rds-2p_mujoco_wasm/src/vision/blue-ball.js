export const BALL_COLORS = {
  blue: { ru: "синий", hex: "#174bc4" },
  red: { ru: "красный", hex: "#b62424" },
  green: { ru: "зелёный", hex: "#087a34" },
};

/** Select ONLY neural detections. No pixels, simulator objects or colour fallback. */
export function selectBlueBall(detections, width, height, color = "blue") {
  const label = `${color}_ball`;
  const candidates = detections.filter(box => box.label === label && box.confidence >= 0.35
    && box.x2 > box.x1 && box.y2 > box.y1);
  const box = candidates.sort((a,b) => (b.x2-b.x1)*(b.y2-b.y1) - (a.x2-a.x1)*(a.y2-a.y1))[0];
  return box ? { ...box, centerX: (box.x1+box.x2)/(2*width), centerY: (box.y1+box.y2)/(2*height),
    relativeWidth: (box.x2-box.x1)/width, width, height } : null;
}

/** Normalized visual servoing command, shared contract with the ROS controller. */
export function blueBallCommand(detection, now, capturedAt) {
  if (!detection || now - capturedAt > 700) return [0, 0, 0];
  const error = (detection.centerX - 0.5) * 2;
  const turn = Math.abs(error) < 0.06 ? 0 : Math.max(-0.65, Math.min(0.65, -error * 1.4));
  const forward = Math.abs(error) > 0.55 ? 0
    : Math.max(0, Math.min(0.55, (0.18 - detection.relativeWidth) * 6)) * (1 - Math.abs(error));
  return [forward, 0, turn];
}
