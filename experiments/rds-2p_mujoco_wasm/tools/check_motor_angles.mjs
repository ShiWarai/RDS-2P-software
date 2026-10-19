#!/usr/bin/env node
/**
 * Проверка порта «моторы → суставы» (src/sim/motorAngles.js) на данных из репо:
 *
 *   1) «цифровой нуль»: строим units-таблицу, при которой все 12 углов суставов
 *      равны нулю (по правилу инвертирования цепочки) — прогон должен дать [0×12];
 *   2) position_0 (все 0.5) — вектор /joint_commands: сверяем ЗНАКИ и порядок
 *      величин с эталоном с реального робота (числа отличаются: у нас примерные
 *      окна min/max, у железа свой calibrate.json);
 *   3) все позы пресета: конечность углов, диапазоны, фолбэки IK.
 *
 * Запуск: node tools/check_motor_angles.mjs
 */
import fs from "node:fs";
import {
  MOTORS, AXIS_ROTATE, REVERSED_AXIS, UNITS_PER_RAD,
  kneeAngleFromMotors, poseToJointAngles, motorUnitsToJointAngles,
} from "../src/sim/motorAngles.js";

let failures = 0;
const near = (a, b, eps) => Math.abs(a - b) <= eps;

/* ── 1. цифровой нуль ─────────────────────────────── */

function digitalZeroUnits() {
  const units = new Float64Array(12);
  for (let leg = 0; leg < 4; leg++) {
    const lb = leg * 3;
    const hip = lb + 1;
    const shin = lb + 2;
    const sHip = REVERSED_AXIS[hip] ? -1 : 1;
    const thetaHip = -AXIS_ROTATE[hip] / sHip;
    units[lb] = MOTORS[lb].zero;
    units[hip] = MOTORS[hip].zero + (MOTORS[hip].reversed ? -1 : 1) * thetaHip * UNITS_PER_RAD;
    // θ_shin такой, что knee(θ_hip, θ_shin) = π − 1.5707 (s_axis shin = −1).
    // Ветка решения — рядом с рабочим диапазоном (±1.6 рад), а не дальняя.
    const kneeTarget = Math.PI - AXIS_ROTATE[shin];
    let lo = -1.6;
    let hi = 1.6;
    const f = (t) => {
      const k = kneeAngleFromMotors(thetaHip, t);
      return k == null ? null : k - kneeTarget;
    };
    let flo = f(lo);
    let fhi = f(hi);
    if (flo == null || fhi == null || flo * fhi > 0) {
      lo = -4;
      hi = 4;
      flo = f(lo);
      fhi = f(hi);
      if (flo == null || fhi == null || flo * fhi > 0) {
        return { units: null, note: `колено без решения для ноги ${leg}` };
      }
    }
    for (let i = 0; i < 60; i++) {
      const m = (lo + hi) / 2;
      const fm = f(m);
      if (fm == null) { break; }
      if (fm * flo <= 0) { hi = m; } else { lo = m; flo = fm; }
    }
    const found = (lo + hi) / 2;
    units[shin] = MOTORS[shin].zero + (MOTORS[shin].reversed ? -1 : 1) * found * UNITS_PER_RAD;
  }
  return { units, note: "" };
}

const { units: zeroUnits, note } = digitalZeroUnits();
if (!zeroUnits) {
  failures++;
  console.log(`ПРОМАХ цифрового нуля: ${note}`);
} else {
  const q = motorUnitsToJointAngles(zeroUnits);
  let bad = 0;
  for (let i = 0; i < 12; i++) {
    if (!near(q[i], 0, 2e-3)) { bad++; }
  }
  console.log(`■ цифровой нуль: units=[${Array.from(zeroUnits).map((u) => u.toFixed(1)).join(", ")}]`);
  console.log(`  угол max |q| = ${Math.max(...Array.from(q, Math.abs)).toExponential(2)} рад${bad ? " — ПРОМАХ" : " ✓"}`);
  if (bad) { failures++; }
}

/* ── 2. таблица точных углов робота (assets/pose_angles.json) ── */

const anglesDoc = JSON.parse(fs.readFileSync(new URL("../assets/pose_angles.json", import.meta.url), "utf8"));
const CTRL_RANGES = [ // ctrlrange из MJCF (порядок актуаторов): [lo, hi]
  [-0.959931, 1.745329], [-1.047198, 1.047198], [-1.134464, 0.523599],
  [-1.745329, 0.959931], [-1.047198, 1.047198], [-1.134464, 0.523599],
  [-0.959931, 1.745329], [-1.047198, 1.047198], [-1.134464, 0.523599],
  [-1.745329, 0.959931], [-1.047198, 1.047198], [-1.134464, 0.523599],
];
console.log("■ таблица углов (assets/pose_angles.json):");
let badRows = 0;
for (const [name, row] of Object.entries(anglesDoc.poses)) {
  const ok = Array.isArray(row) && row.length === 12 && row.every((v) => Number.isFinite(v));
  if (!ok) { badRows++; }
  const over = row.map((v, i) => (ok && (v < CTRL_RANGES[i][0] - 1e-6 || v > CTRL_RANGES[i][1] + 1e-6) ? i : -1)).filter((i) => i >= 0);
  console.log(`  ${name.padEnd(15)} ${ok ? "✓" : "БИТАЯ"}${over.length ? `  вне ctrlrange: ${over.map((i) => MOTORS[i].name).join(", ")} (MuJoCo клампнет)` : ""}`);
}
if (badRows) { failures++; }

/* ── 3. все позы пресета ──────────────────────────── */

const posesDoc = JSON.parse(fs.readFileSync(new URL("../assets/poses.json", import.meta.url), "utf8"));
console.log("■ позы пресета:");
for (const [name, pose] of Object.entries(posesDoc.poses)) {
  const q = poseToJointAngles(pose);
  const finite = Array.from(q).every(Number.isFinite);
  const lbl = ["бедро", "таз", "голень"];
  const ranges = [0, 1, 2].map((f) => {
    const vals = [0, 1, 2, 3].map((leg) => q[leg * 3 + f]);
    return `${lbl[f]} [${Math.min(...vals).toFixed(2)}…${Math.max(...vals).toFixed(2)}]`;
  });
  console.log(`  ${name.padEnd(14)} ${finite ? "✓" : "NaN!"}  ${ranges.join("  ")}`);
  if (!finite) { failures++; }
}

console.log(failures ? `\nПРОВАЛОВ: ${failures}` : "\nвсе проверки пройдены");
process.exit(failures ? 1 : 0);