/**
 * Программы движений — перенос последовательностей из
 * ros_packages/src/rds_2p_commands/rds_2p_commands/action_handlers/robot_routine_handler.py
 *
 * Шаг программы (интерпретируется src/sim/motionPlayer.js):
 *   {kind:'pose', pose: 'position_2', blend?, hold?, noLimit?, label}
 *   {kind:'wait', ms, label}
 *   {kind:'release', label}            — снять torque со всех приводов («плюх»)
 *   {kind:'gait', on: true|false, label} — процедурный трот («бежит на месте»)
 *   {kind:'policy', vx,vy,wz | stop:true, label} — нейросетевая походка
 *     (rds2p_policy.onnx из rospkg rds_2p_inference; фолбэк — трот)
 *   {kind:'ui', id, label}             — не моторная команда: эффект в интерфейсе
 *
 * Позы задаются именами из assets/poses.json или пользовательскими позами.
 */

import { MOTOR_COMMANDS, commandById } from "../rules/catalog.js";

const B = 400; // базовый бленд между позами, мс (план: 250–500)

export const PROGRAMS = {
  give_paw: [
    pose("position_give", 500, "поднимает переднюю лапу"),
    pose("position_2", 500, "возвращает лапу: стойка"),
    pose("position_1", 400, "обычная стойка"),
  ],
  stand_at_attention: [
    pose("position_2", 400, "равняйся!"),
  ],
  dismiss: [
    pose("position_1", 400, "отставить"),
  ],
  lie_down: [
    pose("position_0", 1000, "ложится"),
    { kind: "release", label: "лапки расслаблены (torque выключен)" },
  ],
  pray: [
    pose("position_0", 900, "исходная стойка"),
    pose("position_4_0", 500, "служить: подготовка"),
    pose("position_4_1", 600, "служить"),
    pose("position_4_2", 500, "служить"),
    pose("position_4_3", 500, "служить"),
    pose("position_4_4", 500, "служить"),
    pose("position_4_n_1", 600, "служить"),
    pose("position_4_n", 900, "служить"),
    pose("position_2", 600, "встала"),
  ],
  // Кувырок — последовательность из поз робота (position_3_*, no_limit).
  // В симуляции это best-effort: жёсткие пики идут через мягкий предохранитель.
  rotate: [
    pose("position_3_0", 600, "кувырок: подготовка"),
    pose("position_3_1", 900, "кувырок (данные робота)"),
    pose("position_3_2", 1000, "кувырок (данные робота)"),
    pose("position_3_0", 800, "выравнивание"),
    pose("position_3_3", 900, "кувырок (данные робота)"),
    pose("position_3_4", 1000, "кувырок (данные робота)"),
    pose("position_3_0", 700, "выравнивание"),
    pose("position_3_5", 800, "после кувырка"),
    pose("position_0", 900, "встала"),
  ],
  run: [
    { kind: "policy", vx: 0, vy: 0, wz: 0, label: "режим «Ходьба» (WASD рулит)" },
  ],
  // Шаги‑команды: короткая нейросетевая походка в сторону + возврат в стойку.
  // Замеры в симуляторе (1.8 с): вперёд ~12 см (vx +1.0), назад ~14 см (vx −1.0),
  // боком ~15 см (vy ±0.8). Фолбэк без политики — трот на месте.
  step_forward: [
    { kind: "policy", vx: 1.0, vy: 0, wz: 0, label: "шагает вперёд" },
    { kind: "wait", ms: 1800, label: "шаг вперёд" },
    { kind: "policy", stop: true, label: "остановилась" },
    pose("position_0", 400, "встала"),
  ],
  step_back: [
    { kind: "policy", vx: -1.0, vy: 0, wz: 0, label: "шагает назад" },
    { kind: "wait", ms: 1800, label: "шаг назад" },
    { kind: "policy", stop: true, label: "остановилась" },
    pose("position_0", 400, "встала"),
  ],
  step_left: [
    { kind: "policy", vx: 0, vy: 0.8, wz: 0, label: "шагает влево" },
    { kind: "wait", ms: 1800, label: "шаг влево" },
    { kind: "policy", stop: true, label: "остановилась" },
    pose("position_0", 400, "встала"),
  ],
  step_right: [
    { kind: "policy", vx: 0, vy: -0.8, wz: 0, label: "шагает вправо" },
    { kind: "wait", ms: 1800, label: "шаг вправо" },
    { kind: "policy", stop: true, label: "остановилась" },
    pose("position_0", 400, "встала"),
  ],
  stop_running: [
    { kind: "policy", stop: true, label: "остановилась" },
    pose("position_0", 600, "спокойная стойка"),
  ],
};

function pose(name, hold, label) {
  return { kind: "pose", pose: name, blend: B, hold, label };
}

/** Собрать программу для команды из правил/кнопок. */
export function programForCommand(id) {
  if (PROGRAMS[id]) {
    return PROGRAMS[id].map((s) => ({ ...s }));
  }
  return null;
}

export const COMMAND_LABELS = Object.fromEntries(
  MOTOR_COMMANDS.map((c) => [c.id, c.label])
);

export function commandLabel(id) {
  return commandById(id)?.label ?? id;
}

/** Кнопки панели ручных команд (правая половина). */
export const MANUAL_BUTTONS = [
  { id: "give_paw", text: "🐾 лапу" },
  { id: "stand_at_attention", text: "🫡 равняйся" },
  { id: "dismiss", text: "🙌 отставить" },
  { id: "lie_down", text: "🛏️ лежать" },
  { id: "pray", text: "🙏 служить" },
  { id: "rotate", text: "🤸 кувырок" },
  { id: "run", text: "🚶 ходьба" },
  { id: "step_forward", text: "⬆️ шаг вперёд" },
  { id: "step_back", text: "⬇️ шаг назад" },
  { id: "step_left", text: "⬅️ шаг влево" },
  { id: "step_right", text: "➡️ шаг вправо" },
  { id: "stop_running", text: "🛑 стой" },
];
