export const MOTOR_COMMANDS = [
  { id: "give_paw",           label: "дай лапу" },
  { id: "stand_at_attention", label: "равняйся" },
  { id: "dismiss",            label: "отставить" },
  { id: "lie_down",           label: "лежать" },
  { id: "pray",               label: "служить" },
  { id: "rotate",             label: "кувырок" },
  // Команды движения: короткий шаг нейросетевой походкой в нужную сторону
  // (замеры в симуляторе: вперёд ~12 см, назад ~14 см, боком ~15 см за 1.8 с).
  // «Ходьба» как отдельная команда убрана: режим включается кнопкой «🚶 ходьба»
  // и рулится WASD, а в блок-схемах теперь конкретные шаги.
  { id: "step_forward",       label: "шаг вперёд" },
  { id: "step_back",          label: "шаг назад" },
  { id: "step_left",          label: "шаг влево" },
  { id: "step_right",         label: "шаг вправо" },
  { id: "stop_running",       label: "смирно" },
];

export const ALL_COMMANDS = [...MOTOR_COMMANDS];

export const commandById = (id) => ALL_COMMANDS.find((c) => c.id === id) || null;

export const isMotorCommand = (id) => MOTOR_COMMANDS.some((c) => c.id === id);