/**
 * Порт цепочки «моторы ⇄ суставы» из ROS2-стека RDS-2P — позы в симуляторе
 * считаются так же, как их считает настоящий робот:
 *
 *   шаг 1  units → радианы мотора:  θ = s_cfg·(units − zero_offset) / K,
 *          s_cfg = −1 при reversed: true  (ftservo_ros motor_controller.cpp,
 *          K = 195.56959 units/rad);
 *   шаг 2  радианы моторов → углы суставов (rds_2p motor_to_joint_bridge.cpp):
 *            leg_block: q = s_axis·θ
 *            hip:       q = s_axis·θ + 0.7854
 *            shin:      q = s_axis·(π − knee(θ_hip, θ_shin)) + 1.5707,
 *          где knee() — угол бедро-голень по параллелограмму
 *          (порт computeKneeAngleFromMotorsRad, константы из leg.py),
 *          s_axis = −1 при reversed_axis: true;
 *   шаг 3  кламп в ctrlrange — делает MuJoCo, мы дополнительно зажимаем в poseManager.
 *
 * Данные: calibrate.json с робота — initial_position (он же zero_offset) и окна
 * min/max; reversed — из ftservo_ros/config/config_example.yaml; оси — из
 * rds_2p/config/joint_offsets.yaml. Поза: units = min + (max−min)·pos (0.5 — середина).
 */

export const UNITS_PER_RAD = 195.56959;

// Порядок — как у актуаторов MJCF: [fl, fr, bl, br] × [leg_block, hip, shin].
// min/max — реальные окна с робота (calibrate: leg_N/positions/device_id-*),
// zero_offset_units и reversed — строго из ftservo_ros/config/config_example.yaml
// (проверено: таблица поз второго агента пересчитывается из этих данных 1-в-1).
export const MOTORS = [
  { name: "leg_block_fl", zero: 500, min: 409, max: 590, reversed: false },
  { name: "hip_fl",       zero: 400, min: 424, max: 581, reversed: false },
  { name: "shin_fl",      zero: 440, min: 390, max: 632, reversed: false },
  { name: "leg_block_fr", zero: 505, min: 427, max: 620, reversed: true },
  { name: "hip_fr",       zero: 605, min: 451, max: 627, reversed: true },
  { name: "shin_fr",      zero: 550, min: 458, max: 641, reversed: true },
  { name: "leg_block_bl", zero: 495, min: 422, max: 602, reversed: true },
  { name: "hip_bl",       zero: 415, min: 450, max: 600, reversed: false },
  { name: "shin_bl",      zero: 363, min: 292, max: 584, reversed: false },
  { name: "leg_block_br", zero: 530, min: 428, max: 610, reversed: false },
  { name: "hip_br",       zero: 644, min: 455, max: 613, reversed: true },
  { name: "shin_br",      zero: 613, min: 470, max: 647, reversed: true },
];

// joint_offsets.yaml: axis_rotate по семействам, reversed_axis для leg_block — как в файле.
export const AXIS_ROTATE = [0, 0.7854, 1.5707, 0, 0.7854, 1.5707, 0, 0.7854, 1.5707, 0, 0.7854, 1.5707];
export const REVERSED_AXIS = [true, true, true, false, true, true, true, true, true, false, true, true];

/* ── кинематика голени (константы из inverse_kinematic/leg.py) ── */

const L_HIP = 10.0;
const L_LEG = 10.255;
const L_CAROMYSLO = 3.191;
const L_TYAGA = 10.0;
const L_SIDE_A = 2.4;
const L_SIDE_B = 2.7;
const L_SIDE_C_ANGLE = 90.0 * Math.PI / 180.0;
const L_MALA_TYAGA = 2.8;
const L_RICHAG_3 = 2.4;
const OFFSET_3_X = 2.0;
const OFFSET_3_Y = -2.0;
const CAROMYSLO_ANGLE = Math.PI - (32.2 * Math.PI / 180.0);
const TAU = 2.0 * Math.PI;

function wrap2pi(x) {
  let r = x % TAU;
  if (r < 0) { r += TAU; }
  return r;
}

function wrapPi(x) {
  let r = x;
  while (r > Math.PI) { r -= TAU; }
  while (r < -Math.PI) { r += TAU; }
  return r;
}

/** Пересечение окружностей: [] — нет, [p] — касание, [p1, p2] — две точки. */
function circleIntersection(x1, y1, r1, x2, y2, r2) {
  const eps = 1e-6;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const d = Math.hypot(dx, dy);
  if (d > r1 + r2 + eps || d < Math.abs(r1 - r2) - eps || (Math.abs(d) < eps && Math.abs(r1 - r2) < eps)) {
    return [];
  }
  const a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d);
  const h = Math.sqrt(Math.max(0.0, r1 * r1 - a * a));
  const xm = x1 + a * dx / d;
  const ym = y1 + a * dy / d;
  if (h < eps) { return [{ x: xm, y: ym }]; }
  const rx = h * dy / d;
  const ry = h * (x1 - x2) / d;
  return [{ x: xm + rx, y: ym + ry }, { x: xm - rx, y: ym - ry }];
}

/**
 * Угол между бедром и голенью (рад) по углам двух моторов (рад).
 * Порт computeKneeAngleFromMotorsRad из motor_to_joint_bridge.cpp.
 * @returns {number|null} null — геометрия не дала решения
 */
export function kneeAngleFromMotors(theta2Motor, theta3Motor) {
  const theta2 = theta2Motor + Math.PI;
  const theta3 = theta3Motor;

  const kx = L_HIP * Math.cos(theta2);
  const ky = L_HIP * Math.sin(theta2);
  const rx = OFFSET_3_X + L_RICHAG_3 * Math.cos(theta3);
  const ry = OFFSET_3_Y + L_RICHAG_3 * Math.sin(theta3);

  const pCandidates = circleIntersection(0, 0, L_SIDE_B, rx, ry, L_MALA_TYAGA);
  if (!pCandidates.length) { return null; }
  let p = pCandidates[0];
  for (const c of pCandidates) { if (c.y > p.y) { p = c; } }

  const alpha = Math.atan2(p.y, p.x) + L_SIDE_C_ANGLE;
  const dx = L_SIDE_A * Math.cos(alpha);
  const dy = L_SIDE_A * Math.sin(alpha);

  const bCandidates = circleIntersection(dx, dy, L_TYAGA, kx, ky, L_CAROMYSLO);
  if (!bCandidates.length) { return null; }
  const score = (pt) => {
    const kneeDeg = 180.0 - (wrap2pi(Math.atan2(pt.y - ky, pt.x - kx) - theta2 - CAROMYSLO_ANGLE) * 180.0 / Math.PI);
    return Math.abs(kneeDeg);
  };
  let b = bCandidates[0];
  for (const c of bCandidates) { if (score(c) < score(b)) { b = c; } }

  const thetaLeg = wrap2pi(Math.atan2(b.y - ky, b.x - kx) - theta2 - CAROMYSLO_ANGLE);
  const kneeDeg = 180.0 - (thetaLeg * 180.0 / Math.PI);
  return wrapPi(kneeDeg * Math.PI / 180.0);
}

/* ── преобразования ── */

export function poseToUnits(pose, cfg) {
  return cfg.min + (cfg.max - cfg.min) * pose;
}

export function thetaFromUnits(units, cfg) {
  const s = cfg.reversed ? -1 : 1;
  return s * (units - cfg.zero) / UNITS_PER_RAD;
}

/** 12 моторных units → 12 углов суставов (рад). */
export function motorUnitsToJointAngles(units) {
  const theta = new Float64Array(12);
  for (let i = 0; i < 12; i++) { theta[i] = thetaFromUnits(units[i], MOTORS[i]); }
  const q = new Float64Array(12);
  for (let i = 0; i < 12; i++) {
    const s = REVERSED_AXIS[i] ? -1 : 1;
    const family = i % 3;
    if (family === 0) {
      q[i] = s * theta[i];
    } else if (family === 1) {
      q[i] = s * theta[i] + AXIS_ROTATE[i];
    } else {
      const knee = kneeAngleFromMotors(theta[i - 1], theta[i]);
      if (knee == null) {
        q[i] = s * theta[i] + AXIS_ROTATE[i]; // как фолбэк в мосте
      } else {
        q[i] = s * wrapPi(Math.PI - knee) + AXIS_ROTATE[i];
      }
    }
  }
  return q;
}

/** Нормализованная поза (0..1 на мотор, порядок MJCF) → углы суставов (рад). */
export function poseToJointAngles(poseArr) {
  const units = new Float64Array(12);
  for (let i = 0; i < 12; i++) {
    units[i] = poseToUnits(Number(poseArr[i] ?? 0.5), MOTORS[i]);
  }
  return motorUnitsToJointAngles(units);
}