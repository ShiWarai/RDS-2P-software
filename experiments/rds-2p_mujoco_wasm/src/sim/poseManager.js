/**
 * Менеджер поз: нормализованные доли мотора (0..1) → ctrl MuJoCo.
 *
 * Перевод идёт той же цепочкой, что у настоящего робота (см. src/sim/motorAngles.js):
 *   pose → units (min + (max−min)·pose) → радианы мотора (zero_offset, reversed)
 *   → углы суставов (reversed_axis, axis_rotate 45°/90°, параллелограмм голени).
 * Это те же формулы, что в ftservo_ros/motor_controller + rds_2p/motor_to_joint_bridge,
 * поэтому «равняйся», «дать лапу» и т.п. стоят так же, как на железе.
 *
 * Результат зажимается в [lo, hi] из actuator_ctrlrange (стандартные позы);
 * no_limit-позы (position_3_*, position_4_*) получают мягкий предохранитель ±20%.
 */

import { poseToJointAngles, MOTORS, REVERSED_AXIS } from "./motorAngles.js";

export const SOFT_FUSE = 0.2;

export class PoseManager {
  /** @param {object} model MjModel из mujoco-js (nu = 12) */
  constructor(model) {
    this.nu = model.nu;
    const range = model.actuator_ctrlrange;
    this.lo = new Float64Array(this.nu);
    this.hi = new Float64Array(this.nu);
    this.span = new Float64Array(this.nu);
    this.limited = new Uint8Array(this.nu);
    for (let i = 0; i < this.nu; i++) {
      this.lo[i] = range[2 * i];
      this.hi[i] = range[2 * i + 1];
      this.span[i] = this.hi[i] - this.lo[i];
      this.limited[i] = model.actuator_ctrllimited[i];
    }
  }

  normToCtrl(normArr, { noLimit = false } = {}) {
    const pose = new Float64Array(12);
    for (let i = 0; i < 12; i++) {
      let norm = Number(normArr[i] ?? 0.5);
      if (!Number.isFinite(norm)) { norm = 0.5; }
      if (!noLimit) { norm = Math.min(1, Math.max(0, norm)); }
      pose[i] = norm;
    }
    const q = poseToJointAngles(pose);
    const out = new Float64Array(this.nu);
    for (let i = 0; i < this.nu; i++) {
      const pad = noLimit ? SOFT_FUSE * this.span[i] : 0;
      out[i] = Math.min(this.hi[i] + pad, Math.max(this.lo[i] - pad, q[i]));
    }
    return out;
  }

  /**
   * Точные углы суставов (таблицы робота, assets/pose_angles.json) → ctrl.
   * Рамки те же, что у normToCtrl: жёстко в ctrlrange, для no_limit-поз мягкий
   * предохранитель ±20% (часть поз кувырка/«служить» намеренно вне диапазона).
   */
  clampToCtrl(angles, { noLimit = false } = {}) {
    const out = new Float64Array(this.nu);
    for (let i = 0; i < this.nu; i++) {
      let v = Number(angles[i]);
      if (!Number.isFinite(v)) { v = 0; }
      const pad = noLimit ? SOFT_FUSE * this.span[i] : 0;
      out[i] = Math.min(this.hi[i] + pad, Math.max(this.lo[i] - pad, v));
    }
    return out;
  }

  /** Есть ли углы за пределами ctrlrange (→ поза считается no_limit). */
  anglesOutOfRange(angles) {
    for (let i = 0; i < this.nu; i++) {
      const v = Number(angles[i]);
      if (Number.isFinite(v) && (v < this.lo[i] - 1e-6 || v > this.hi[i] + 1e-6)) { return true; }
    }
    return false;
  }

  /** Обратное преобразование — для чтения текущей позы в слайдеры редактора. */
  ctrlToNorm(ctrlArr) {
    const pose = new Float64Array(12).fill(0.5);
    const qOf = (idx, value) => {
      const probe = Float64Array.from(pose);
      probe[idx] = value;
      return poseToJointAngles(probe)[idx];
    };
    for (let i = 0; i < this.nu && i < 12; i++) {
      const target = Number(ctrlArr[i]);
      if (!Number.isFinite(target)) { continue; }
      const fa = qOf(i, 0) - target;
      const fb = qOf(i, 1) - target;
      let x;
      if (fa === 0) { x = 0; }
      else if (fb === 0) { x = 1; }
      else if (fa * fb < 0) {
        let a = 0;
        let b = 1;
        for (let k = 0; k < 40; k++) {
          const m = (a + b) / 2;
          if ((qOf(i, m) - target) * fa <= 0) { b = m; } else { a = m; }
        }
        x = (a + b) / 2;
      } else {
        x = Math.abs(fa) < Math.abs(fb) ? 0 : 1;
      }
      pose[i] = x;
    }
    return Array.from(pose);
  }

  static isNoLimit(normArr) {
    return normArr.some((x) => Number(x) > 1.001 || Number(x) < -0.001);
  }
}

/** Подписи 12 приводов: leg_1..leg_4 x (leg_block, hip, shin). */
export const LEG_NAMES = ["передняя левая", "передняя правая", "задняя левая", "задняя правая"];
export const LEG_ORDER = ["1", "2", "3", "4"];
export const JOINT_ICONS = ["↔", "↕", "⤵"];
export const JOINT_NAMES = ["бедро", "таз", "голень"];

export function actuatorLabel(i) {
  return `${LEG_NAMES[Math.floor(i / 3)]} ${JOINT_NAMES[i % 3]}`;
}

/** Данные моторов — для отладочных панелей (та же таблица, что в цепочке). */
export { MOTORS, REVERSED_AXIS };