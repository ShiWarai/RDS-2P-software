/**
 * Blockly v3: блоки-вопросы (System One / Jev-Laya) + каскад.
 *
 * Структура потока: «▶ Старт» → цепочка блоков; вопросы/развилки/действия
 * встраиваются друг в друга (каскад: вопрос внутри варианта другого вопроса).
 *
 *   ▶ Старт          — контейнер «откуда начинается движение»;
 *   ❓ выбор         — варианты (🔘) с действиями в каждом;
 *   ✅ да/нет        — Бернулли: ветки «если да/нет →»;
 *   🧮 шкала         — уровни; у каждого уровня своя ветка «действия»;
 *   🔀 если P(…)     — развилка по вероятности/баллу, встраивается куда угодно;
 *   действия         — команда/поза/жди/сказать.
 *
 * «📦 Шаблоны» — готовые собранные заготовки (см. templates.js).
 * Сериализация — дерево store v3 (src/rules/store.js).
 */

import { MOTOR_COMMANDS } from "../rules/catalog.js";
import { TEMPLATES } from "./templates.js";

export const START_BLOCK = "panda_start";
export const Q_CHOICE_BLOCK = "panda_ask_choice";
export const Q_NOUL_BLOCK = "panda_ask_noul";
export const Q_SCORE_BLOCK = "panda_ask_score";
export const OPTION_BLOCK = "panda_option";
export const BRANCH_BLOCK = "panda_branch";
export const COMMAND_BLOCK = "panda_command";
export const POSE_BLOCK = "panda_pose";
export const WAIT_BLOCK = "panda_wait";
export const SAY_BLOCK = "panda_say";
export const TPL_BLOCK = "panda_tpl";

export const QUESTION_TYPES = [Q_CHOICE_BLOCK, Q_NOUL_BLOCK, Q_SCORE_BLOCK];
export const NODE_TYPES = [START_BLOCK, ...QUESTION_TYPES, BRANCH_BLOCK,
  COMMAND_BLOCK, POSE_BLOCK, WAIT_BLOCK, SAY_BLOCK];

const FLOW_TYPE = "Flow";

const COLOURS = {
  start: "#16a34a",
  choice: "#14b8a6",
  noul: "#0ea5e9",
  score: "#8b5cf6",
  option: "#0f766e",
  branch: "#eab308",
  command: "#3b82f6",
  pose: "#f97316",
  wait: "#64748b",
  say: "#ec4899",
};

export const BRANCH_OPS = [">", "<", "≥", "≤", "="];

let poseOptionsProvider = () => [];
let BLY = null;

export function setPoseOptionsProvider(fn) {
  poseOptionsProvider = fn;
}

function badgeField() {
  const f = new BLY.FieldLabel("");
  try { f.className_ = "panda-badge"; } catch { /* не критично */ }
  return f;
}

function commandOptions() {
  return [
    ["— команда —", ""],
    ...MOTOR_COMMANDS.map((c) => [c.label, c.id]),
  ];
}

/**
 * Список событий для развилки: все вопросы и их варианты (и вложенные тоже).
 * Значение — '<qid>::<sel>'; sel: id варианта | true | false | score | level:i
 */
function eventOptions() {
  const out = [["— выбери событие —", ""]];
  let ws = null;
  try { ws = this?.getSourceBlock?.()?.workspace; } catch { /* fallback ниже */ }
  if (!ws) { try { ws = BLY?.getMainWorkspace?.(); } catch { /* нет */ } }
  if (!ws) { return out; }
  const qName = (b) => String(b.getFieldValue("NAME") || "вопрос").trim() || "вопрос";
  for (const q of ws.getAllBlocks(true)) {
    if (!QUESTION_TYPES.includes(q.type) || !q.data) { continue; }
    if (q.type === Q_CHOICE_BLOCK) {
      let child = q.getInputTargetBlock("OPTS");
      while (child) {
        if (child.type === OPTION_BLOCK && child.data) {
          const oName = String(child.getFieldValue("NAME") || "вариант").trim() || "вариант";
          out.push([`«${qName(q)}»: ${oName}`, `${q.data}::${child.data}`]);
        }
        child = child.getNextBlock();
      }
    } else if (q.type === Q_NOUL_BLOCK) {
      out.push([`«${qName(q)}»: да`, `${q.data}::true`]);
      out.push([`«${qName(q)}»: нет`, `${q.data}::false`]);
    } else if (q.type === Q_SCORE_BLOCK) {
      out.push([`«${qName(q)}»: балл`, `${q.data}::score`]);
      splitPhrases(q.getFieldValue("LEVELS")).forEach((text, i) => {
        out.push([`«${qName(q)}»: ${text}`, `${q.data}::level:${i}`]);
      });
    }
  }
  return out;
}

/* ── шкала: динамические ветки по уровням ─────────── */

const MAX_LEVELS = 8;

function rebuildLevelInputs(block, levelsStr) {
  const levels = splitPhrases(levelsStr).slice(0, MAX_LEVELS);
  const same = block.levelLabels_
    && block.levelLabels_.length === levels.length
    && block.levelLabels_.every((x, i) => x === levels[i]);
  if (same) { return; }
  block.levelLabels_ = levels;

  // Снять и запомнить детей, чтобы не потерять при пересборке входов.
  const saved = [];
  for (const inp of [...block.inputList]) {
    if (/^LVL_\d+$/.test(inp.name)) {
      const child = inp.connection?.targetBlock() || null;
      saved.push(child);
      if (child) { inp.connection.disconnect(); }
      block.removeInput(inp.name);
    }
  }
  levels.forEach((label, i) => {
    block.appendStatementInput(`LVL_${i}`)
      .appendField(`⚖️ «${label}» →`)
      .appendField(badgeField(), `BADGE_LVL_${i}`);
  });
  saved.forEach((child, i) => {
    const conn = block.getInput(`LVL_${i}`)?.connection;
    if (conn && child && child.previousConnection) { conn.connect(child.previousConnection); }
  });
}

export function initBlocks(Blockly) {
  BLY = Blockly;
  const define = Blockly.common?.defineBlocks ?? Blockly.defineBlocks;
  const saveId = {
    saveExtraState() { return { id: this.data || null }; },
    loadExtraState(state) { if (state?.id) { this.data = state.id; } },
  };
  const flowBlock = () => {
    return {
      setPreviousStatement: true,
      setNextStatement: true,
    };
  };
  void flowBlock;

  const defs = {
    [START_BLOCK]: {
      init() {
        this.appendDummyInput().appendField("▶ Старт");
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.start);
        this.setTooltip("Просто начало пути: цепляй к нему блоки снизу.");
        this.setMovable(true);
      },
      ...saveId,
    },
    [Q_CHOICE_BLOCK]: {
      init() {
        this.appendDummyInput("HEAD")
          .appendField("❓ выбор")
          .appendField(new BLY.FieldTextInput("Команды"), "NAME");
        this.appendDummyInput("ASK")
          .appendField("💬")
          .appendField(new BLY.FieldTextInput("Какая команда подходит к фразе?"), "ASK");
        this.appendStatementInput("OPTS")
          .appendField("🔘 варианты:")
          .appendField(badgeField(), "BADGE");
        this.setPreviousStatement(true, FLOW_TYPE);
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.choice);
        this.setTooltip("Вопрос-выбор: вероятности по вариантам. Самый вероятный вариант выполняется (можно вложить следующий вопрос).");
        this.setMovable(true);
      },
      ...saveId,
    },
    [Q_NOUL_BLOCK]: {
      init() {
        this.appendDummyInput("HEAD")
          .appendField("✅ да/нет")
          .appendField(new BLY.FieldTextInput("Про робота?"), "NAME");
        this.appendDummyInput("ASK")
          .appendField("💬")
          .appendField(new BLY.FieldTextInput("Это команда роботу?"), "ASK");
        this.appendStatementInput("YES")
          .appendField("если да →")
          .appendField(badgeField(), "BADGE_YES");
        this.appendStatementInput("NO")
          .appendField("если нет →")
          .appendField(badgeField(), "BADGE_NO");
        this.setPreviousStatement(true, FLOW_TYPE);
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.noul);
        this.setTooltip("Бернулли-вопрос (noul): P(да)/P(нет). Ветка с большей вероятностью идёт дальше.");
        this.setMovable(true);
      },
      ...saveId,
    },
    [Q_SCORE_BLOCK]: {
      init() {
        this.appendDummyInput("HEAD")
          .appendField("🧮 шкала")
          .appendField(new BLY.FieldTextInput("Команда роботу?"), "NAME");
        this.appendDummyInput("ASK")
          .appendField("💬")
          .appendField(new BLY.FieldTextInput("Насколько фраза команда роботу?"), "ASK");
        const levelsField = new BLY.FieldTextInput("низкая, средняя, высокая");
        levelsField.setValidator((v) => {
          try { rebuildLevelInputs(this, v); } catch (err) { console.warn("levels:", err); }
          return v;
        });
        this.appendDummyInput("LEVELS_ROW")
          .appendField("⚖️ уровни:")
          .appendField(levelsField, "LEVELS")
          .appendField(badgeField(), "BADGE");
        this.setPreviousStatement(true, FLOW_TYPE);
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.score);
        this.setTooltip("Вопрос-шкала (score): упорядоченные уровни; у каждого уровня своя ветка действий. Работает выбранный уровень.");
        this.setMovable(true);
        rebuildLevelInputs(this, this.getFieldValue("LEVELS") || "низкая, средняя, высокая");
      },
      ...saveId,
    },
    [OPTION_BLOCK]: {
      init() {
        this.appendDummyInput("HEAD")
          .appendField("🔘")
          .appendField(new BLY.FieldTextInput("Моя команда"), "NAME");
        this.appendDummyInput("EX")
          .appendField("👂")
          .appendField(new BLY.FieldTextInput("дай лапу, поздоровайся"), "EXAMPLES");
        this.appendStatementInput("DO")
          .appendField("🎬")
          .appendField(badgeField(), "BADGE");
        this.setPreviousStatement(true, "Option");
        this.setNextStatement(true, "Option");
        this.setColour(COLOURS.option);
        this.setTooltip("Вариант ответа: имя + похожие фразы. Выберет модель — пойдут действия ниже (и вложенный вопрос).");
      },
      ...saveId,
    },
    [BRANCH_BLOCK]: {
      init() {
        this.appendDummyInput("HEAD")
          .appendField("🔀 если P(")
          .appendField(new BLY.FieldDropdown(eventOptions), "EVENT")
          .appendField(")")
          .appendField(new BLY.FieldDropdown(BRANCH_OPS.map((o) => [o, o])), "OP")
          .appendField(new BLY.FieldNumber(0.5, 0, 16, 0.05), "VALUE")
          .appendField(badgeField(), "BADGE");
        this.appendStatementInput("DO").appendField("→");
        this.setPreviousStatement(true, FLOW_TYPE);
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.branch);
        this.setTooltip("Развилка по вероятности уже пройденного вопроса (или баллу шкалы). Условие верно — действия идут дальше.");
        this.setMovable(true);
      },
      ...saveId,
    },
    [COMMAND_BLOCK]: {
      init() {
        this.appendDummyInput()
          .appendField("команда")
          .appendField(new BLY.FieldDropdown(commandOptions), "COMMAND");
        this.setPreviousStatement(true, FLOW_TYPE);
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.command);
        this.setTooltip("Одна готовая команда Панды.");
      },
    },
    [POSE_BLOCK]: {
      init() {
        this.appendDummyInput()
          .appendField("🐾 поза")
          .appendField(new BLY.FieldDropdown(() => poseOptionsProvider()), "POSE")
          .appendField("⏱")
          .appendField(new BLY.FieldNumber(800, 100, 20000, 100), "HOLD")
          .appendField("мс");
        this.setPreviousStatement(true, FLOW_TYPE);
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.pose);
        this.setTooltip("Заморозить Панду в выбранной позе (пресет или «моя поза»).");
      },
    },
    [WAIT_BLOCK]: {
      init() {
        this.appendDummyInput()
          .appendField("⏳ жди")
          .appendField(new BLY.FieldNumber(500, 0, 20000, 100), "MS")
          .appendField("мс");
        this.setPreviousStatement(true, FLOW_TYPE);
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.wait);
        this.setTooltip("Пауза между действиями.");
      },
    },
    [SAY_BLOCK]: {
      init() {
        this.appendDummyInput()
          .appendField("💬 сказать")
          .appendField(new BLY.FieldTextInput("Привет!"), "TEXT");
        this.setPreviousStatement(true, FLOW_TYPE);
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.say);
        this.setTooltip("Панда показывает облачко с этой фразой над головой (как в игре).");
      },
    },
    [TPL_BLOCK]: {
      init() {
        this.appendDummyInput()
          .appendField("📦")
          .appendField(new BLY.FieldDropdown(
            TEMPLATES.map((t) => [t.label, t.key]),
          ), "TPL");
        this.setPreviousStatement(true, FLOW_TYPE);
        this.setNextStatement(true, FLOW_TYPE);
        this.setColour(COLOURS.score);
        this.setTooltip("Брось на поле — семечко развернётся в готовый пример.");
        this.setMovable(true);
      },
    },
  };
  if (define) {
    define(defs);
  } else {
    Object.assign(Blockly.Blocks, defs);
  }
}

/* ── шаблоны → toolbox JSON ───────────────────────── */

function chainJson(nodes) {
  if (!nodes || !nodes.length) { return null; }
  const [first, ...rest] = nodes;
  const firstBlock = nodeToJson(first);
  if (!firstBlock) { return null; }
  if (rest.length) {
    const nextBlock = chainJson(rest);
    if (nextBlock) { firstBlock.next = { block: nextBlock }; }
  }
  return firstBlock;
}

/** Узел дерева → JSON блока (для шаблонов и повторного использования). */
export function nodeToJson(node) {
  if (!node) { return null; }
  switch (node.kind) {
    case "command": return { type: COMMAND_BLOCK, fields: { COMMAND: node.command } };
    case "pose": return { type: POSE_BLOCK, fields: { POSE: node.pose, HOLD: node.hold_ms ?? 800 } };
    case "wait": return { type: WAIT_BLOCK, fields: { MS: node.ms ?? 500 } };
    case "say": return { type: SAY_BLOCK, fields: { TEXT: node.text ?? "" } };
    case "start": {
      const json = { type: START_BLOCK };
      const c = chainJson(node.then);
      if (c) { json.next = { block: c }; }
      return json;
    }
    case "branch": {
      const json = { type: BRANCH_BLOCK, fields: { OP: node.op || ">", VALUE: node.value ?? 0.5 } };
      const c = chainJson(node.then);
      if (c) { json.inputs = { DO: { block: c } }; }
      return json;
    }
    case "question":
      if (node.qtype === "choice") {
        const json = { type: Q_CHOICE_BLOCK, fields: { NAME: node.name || "Команды", ASK: node.instructions || "" } };
        const opts = (node.options || []).map((o) => {
          const oj = { type: OPTION_BLOCK, fields: { NAME: o.name || "", EXAMPLES: (o.examples || []).join(", ") } };
          const c = chainJson(o.then);
          if (c) { oj.inputs = { DO: { block: c } }; }
          return oj;
        });
        if (opts.length) {
          const chain = opts[0];
          let cur = chain;
          for (let i = 1; i < opts.length; i++) { cur.next = { block: opts[i] }; cur = opts[i]; }
          json.inputs = { OPTS: { block: chain } };
        }
        return json;
      }
      if (node.qtype === "noul") {
        const json = { type: Q_NOUL_BLOCK, fields: { NAME: node.name || "Да/нет", ASK: node.instructions || "" } };
        const inputs = {};
        const y = chainJson(node.yes?.then);
        const n = chainJson(node.no?.then);
        if (y) { inputs.YES = { block: y }; }
        if (n) { inputs.NO = { block: n }; }
        if (Object.keys(inputs).length) { json.inputs = inputs; }
        return json;
      }
      if (node.qtype === "score") {
        const json = { type: Q_SCORE_BLOCK, fields: { NAME: node.name || "Шкала", ASK: node.instructions || "", LEVELS: (node.levels || []).join(", ") } };
        const inputs = {};
        (node.outcomes || []).forEach((oc, i) => {
          const c = chainJson(oc?.then);
          if (c) { inputs[`LVL_${i}`] = { block: c }; }
        });
        if (Object.keys(inputs).length) { json.inputs = inputs; }
        return json;
      }
      return null;
    default:
      return null;
  }
}

export function toolboxJson() {
  return {
    kind: "categoryToolbox",
    contents: [
      {
        kind: "category",
        name: "🎲 Вопросы",
        colour: COLOURS.choice,
        contents: [
          { kind: "block", type: Q_CHOICE_BLOCK },
          { kind: "block", type: Q_NOUL_BLOCK },
          { kind: "block", type: Q_SCORE_BLOCK },
          { kind: "block", type: OPTION_BLOCK },
        ],
      },
      {
        kind: "category",
        name: "🧭 Ход",
        colour: COLOURS.start,
        contents: [
          { kind: "block", type: START_BLOCK },
          { kind: "block", type: BRANCH_BLOCK },
        ],
      },
      {
        kind: "category",
        name: "🎬 Действия",
        colour: COLOURS.command,
        contents: [
          { kind: "block", type: COMMAND_BLOCK },
          { kind: "block", type: POSE_BLOCK },
          { kind: "block", type: WAIT_BLOCK },
          { kind: "block", type: SAY_BLOCK },
        ],
      },
      {
        kind: "category",
        name: "📦 Шаблоны",
        colour: COLOURS.score,
        contents: TEMPLATES.map((t) => ({
          kind: "block",
          type: TPL_BLOCK,
          fields: { TPL: t.key },
        })),
      },
    ],
  };
}

/* ── обновление выпадающих списков ────────────────── */

function refreshGeneratedOptions(workspace, blockType, fieldName) {
  for (const block of workspace.getAllBlocks(true)) {
    if (block.type !== blockType) { continue; }
    const field = block.getField(fieldName);
    if (!field) { continue; }
    try {
      if ("generatedOptions" in field) { field.generatedOptions = null; }
      try { field.getOptions?.(false); } catch { /* генератор не готов */ }
      field.forceRerender?.();
    } catch (err) {
      console.warn("Не удалось обновить список:", err);
    }
  }
}

/** Списки событий у развилок (после сборки блоков и после sync). */
export function refreshBranchFields(workspace) {
  refreshGeneratedOptions(workspace, BRANCH_BLOCK, "EVENT");
}

/** Списки поз у всех блоков panda_pose. */
export function refreshPoseFields(workspace) {
  refreshGeneratedOptions(workspace, POSE_BLOCK, "POSE");
}

/* ── отметки прогона: бейджи вероятностей и мерцание ── */

export function findBlockById(workspace, id) {
  if (!workspace || !id) { return null; }
  for (const b of workspace.getAllBlocks(true)) {
    if (b.data === id) { return b; }
  }
  return null;
}

/** Поставить текст в поле-бейдж блока (по id). */
export function setBadge(workspace, id, fieldName, text) {
  const b = findBlockById(workspace, id);
  setBadgeOnBlock(b, fieldName, text);
}

/** То же, но напрямую по блоку. */
export function setBadgeOnBlock(b, fieldName, text) {
  if (!b) { return; }
  const f = b.getField(fieldName);
  if (!f) { return; }
  try { f.setValue(String(text ?? "")); } catch { /* noop */ }
}

/** Мерцание активированного блока (+ мягкое свечение до следующего прогона). */
export function flashBlock(blockOrId, workspace) {
  const b = typeof blockOrId === "string" ? findBlockById(workspace, blockOrId) : blockOrId;
  const root = b?.getSvgRoot?.();
  if (!root) { return; }
  root.classList.remove("panda-flash", "panda-lit");
  void root.getBoundingClientRect(); // перезапуск CSS-анимации
  root.classList.add("panda-flash", "panda-lit");
}

/** Сброс всех отметок перед новым прогоном. */
export function clearRunMarks(workspace) {
  if (!workspace) { return; }
  for (const b of workspace.getAllBlocks(true)) {
    const root = b.getSvgRoot?.();
    if (root) { root.classList.remove("panda-flash", "panda-lit"); }
    for (const inp of b.inputList || []) {
      for (const f of inp.fieldRow || []) {
        if (f.name && String(f.name).startsWith("BADGE")) {
          try { f.setValue(""); } catch { /* noop */ }
        }
      }
    }
  }
}

/* ── сериализация (дерево v3) ─────────────────────── */

export function splitPhrases(text) {
  return String(text ?? "")
    .split(/[,;\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Один блок-действие → узел (или null). */
export function actionNodeFromBlock(block) {
  if (!block) { return null; }
  if (block.type === COMMAND_BLOCK) {
    const cmd = block.getFieldValue("COMMAND");
    return cmd ? { kind: "command", command: cmd } : null;
  }
  if (block.type === POSE_BLOCK) {
    return { kind: "pose", pose: block.getFieldValue("POSE"), hold_ms: Number(block.getFieldValue("HOLD")) || 500 };
  }
  if (block.type === WAIT_BLOCK) {
    return { kind: "wait", ms: Number(block.getFieldValue("MS")) || 500 };
  }
  if (block.type === SAY_BLOCK) {
    return { kind: "say", text: String(block.getFieldValue("TEXT") ?? "") };
  }
  return null;
}

/** Шаг программы для плеера из блока-действия (для подсветки пути). */
export function actionStepFromBlock(block) {
  const node = actionNodeFromBlock(block);
  if (!node) { return null; }
  if (node.kind === "command") { return { kind: "command", command: node.command }; }
  if (node.kind === "pose") { return { kind: "pose", pose: node.pose, hold_ms: node.hold_ms, blend: 400 }; }
  if (node.kind === "wait") { return { kind: "wait", ms: node.ms }; }
  return { kind: "say", text: node.text };
}

function chainNodes(firstBlock) {
  const out = [];
  let block = firstBlock;
  while (block) {
    const node = nodeFromBlock(block);
    if (node) { out.push(node); }
    block = block.getNextBlock();
  }
  return out;
}

/** Блок (вместе с его вложениями) → узел дерева. */
export function nodeFromBlock(block) {
  if (!block) { return null; }
  if (block.type === START_BLOCK) {
    return { kind: "start", id: block.data || undefined, then: chainNodes(block.getNextBlock()) };
  }
  if (block.type === Q_CHOICE_BLOCK) {
    const options = [];
    let child = block.getInputTargetBlock("OPTS");
    while (child) {
      if (child.type === OPTION_BLOCK) {
        options.push({
          id: child.data || undefined,
          name: String(child.getFieldValue("NAME") || "").trim(),
          examples: splitPhrases(child.getFieldValue("EXAMPLES")),
          then: chainNodes(child.getInputTargetBlock("DO")),
        });
      }
      child = child.getNextBlock();
    }
    return {
      id: block.data || undefined,
      kind: "question",
      qtype: "choice",
      name: String(block.getFieldValue("NAME") || "").trim() || "Выбор",
      instructions: String(block.getFieldValue("ASK") || "").trim(),
      options,
    };
  }
  if (block.type === Q_NOUL_BLOCK) {
    return {
      id: block.data || undefined,
      kind: "question",
      qtype: "noul",
      name: String(block.getFieldValue("NAME") || "").trim() || "Да/нет",
      instructions: String(block.getFieldValue("ASK") || "").trim(),
      yes: { then: chainNodes(block.getInputTargetBlock("YES")) },
      no: { then: chainNodes(block.getInputTargetBlock("NO")) },
    };
  }
  if (block.type === Q_SCORE_BLOCK) {
    const levels = splitPhrases(block.getFieldValue("LEVELS"));
    return {
      id: block.data || undefined,
      kind: "question",
      qtype: "score",
      name: String(block.getFieldValue("NAME") || "").trim() || "Шкала",
      instructions: String(block.getFieldValue("ASK") || "").trim(),
      levels,
      outcomes: levels.map((_l, i) => {
        const then = chainNodes(block.getInputTargetBlock(`LVL_${i}`));
        return then.length ? { then } : null;
      }),
    };
  }
  if (block.type === BRANCH_BLOCK) {
    return {
      id: block.data || undefined,
      kind: "branch",
      ref: String(block.getFieldValue("EVENT") || ""),
      op: String(block.getFieldValue("OP") || ">"),
      value: Number(block.getFieldValue("VALUE")),
      then: chainNodes(block.getInputTargetBlock("DO")),
    };
  }
  return actionNodeFromBlock(block);
}

/** Блоки → дерево узлов (один корень на верхний блок). */
export function blocksToRules(workspace) {
  const nodes = [];
  for (const top of workspace.getTopBlocks(true)) {
    if (!NODE_TYPES.includes(top.type)) { continue; }
    const node = nodeFromBlock(top);
    if (node) { nodes.push(node); }
  }
  return nodes;
}

/* ── сборка блоков из дерева ──────────────────────── */

function blockFromNode(workspace, node) {
  if (!node) { return null; }
  const spawn = (type) => { const b = workspace.newBlock(type); b.initSvg(); b.render(); return b; };
  switch (node.kind) {
    case "command": {
      const b = spawn(COMMAND_BLOCK);
      b.setFieldValue(node.command, "COMMAND");
      return b;
    }
    case "pose": {
      const b = spawn(POSE_BLOCK);
      b.setFieldValue(node.pose, "POSE");
      b.setFieldValue(String(node.hold_ms ?? 800), "HOLD");
      return b;
    }
    case "wait": {
      const b = spawn(WAIT_BLOCK);
      b.setFieldValue(String(node.ms ?? 500), "MS");
      return b;
    }
    case "say": {
      const b = spawn(SAY_BLOCK);
      b.setFieldValue(String(node.text ?? ""), "TEXT");
      return b;
    }
    case "branch": {
      const b = spawn(BRANCH_BLOCK);
      if (node.id) { b.data = node.id; }
      b.setFieldValue(String(node.op || ">"), "OP");
      b.setFieldValue(String(node.value ?? 0.5), "VALUE");
      attachChain(workspace, b, "DO", node.then);
      if (node.ref) { b._pendingEvent = node.ref; }
      return b;
    }
    case "question":
      if (node.qtype === "choice") {
        const b = spawn(Q_CHOICE_BLOCK);
        if (node.id) { b.data = node.id; }
        b.setFieldValue(node.name || "", "NAME");
        b.setFieldValue(node.instructions || "", "ASK");
        const conn = b.getInput("OPTS").connection;
        let prev = null;
        for (const opt of node.options || []) {
          const ob = spawn(OPTION_BLOCK);
          if (opt.id) { ob.data = opt.id; }
          ob.setFieldValue(opt.name || "", "NAME");
          ob.setFieldValue((opt.examples || []).join(", "), "EXAMPLES");
          attachChain(workspace, ob, "DO", opt.then);
          if (prev) { prev.nextConnection.connect(ob.previousConnection); }
          else { conn.connect(ob.previousConnection); }
          prev = ob;
        }
        return b;
      }
      if (node.qtype === "noul") {
        const b = spawn(Q_NOUL_BLOCK);
        if (node.id) { b.data = node.id; }
        b.setFieldValue(node.name || "", "NAME");
        b.setFieldValue(node.instructions || "", "ASK");
        attachChain(workspace, b, "YES", node.yes?.then);
        attachChain(workspace, b, "NO", node.no?.then);
        return b;
      }
      if (node.qtype === "score") {
        const b = spawn(Q_SCORE_BLOCK);
        if (node.id) { b.data = node.id; }
        b.setFieldValue(node.name || "", "NAME");
        b.setFieldValue(node.instructions || "", "ASK");
        b.setFieldValue((node.levels || []).join(", "), "LEVELS");
        (node.outcomes || []).forEach((oc, i) => {
          attachChain(workspace, b, `LVL_${i}`, oc?.then);
        });
        return b;
      }
      return null;
    case "start": {
      const b = spawn(START_BLOCK);
      if (node.id) { b.data = node.id; }
      attachNextChain(workspace, b, node.then);
      return b;
    }
    default:
      return null;
  }
}

function attachNextChain(workspace, head, nodes) {
  let prev = head;
  for (const node of nodes || []) {
    const b = blockFromNode(workspace, node);
    if (!b) { continue; }
    if (prev.nextConnection && b.previousConnection) {
      prev.nextConnection.connect(b.previousConnection);
    }
    prev = b;
  }
}

function attachChain(workspace, parentBlock, inputName, nodes) {
  const conn = parentBlock.getInput(inputName)?.connection;
  if (!conn || !nodes || !nodes.length) { return; }
  let prev = null;
  for (const node of nodes) {
    const b = blockFromNode(workspace, node);
    if (!b) { continue; }
    if (prev) { prev.nextConnection.connect(b.previousConnection); }
    else { conn.connect(b.previousConnection); }
    prev = b;
  }
}

/** Дерево → блоки (полная пересборка workspace). */
export function rulesToBlocks(workspace, rules, Blockly) {
  workspace.clear();
  let y = 24;
  const pendingEvents = [];
  for (const node of rules) {
    const block = blockFromNode(workspace, node);
    if (!block) { continue; }
    block.moveBy(16, y);
    try { y += block.getHeightWidth().height + 20; } catch { y += 160; }
  }
  // Собираем отложенные EVENT-значения развилок — после создания всех вопросов.
  for (const b of workspace.getAllBlocks(true)) {
    if (b.type === BRANCH_BLOCK && b._pendingEvent) {
      try { b.setFieldValue(b._pendingEvent, "EVENT"); } catch { /* останется placeholder */ }
      delete b._pendingEvent;
    }
  }
  refreshBranchFields(workspace);
  try {
    workspace.zoomToFit && workspace.zoomToFit();
  } catch { /* не критично */ }
}

/* ── обратная запись id (для развилок) ────────────── */

function assignChain(firstBlock, nodes) {
  let block = firstBlock;
  let i = 0;
  let changed = false;
  while (block && i < nodes.length) {
    if (assignIds(block, nodes[i])) { changed = true; }
    block = block.getNextBlock();
    i++;
  }
  return changed;
}

function assignIds(block, node) {
  let changed = false;
  if (!block || !node) { return false; }
  if (node.id && block.data !== node.id) { block.data = node.id; changed = true; }
  if (block.type === START_BLOCK) {
    if (assignChain(block.getNextBlock(), node.then || [])) { changed = true; }
  } else if (block.type === Q_CHOICE_BLOCK) {
    let child = block.getInputTargetBlock("OPTS");
    let i = 0;
    while (child && i < (node.options || []).length) {
      const opt = node.options[i];
      if (child.type === OPTION_BLOCK) {
        if (opt.id && child.data !== opt.id) { child.data = opt.id; changed = true; }
        if (assignChain(child.getInputTargetBlock("DO"), opt.then || [])) { changed = true; }
      }
      child = child.getNextBlock();
      i++;
    }
  } else if (block.type === Q_NOUL_BLOCK) {
    if (assignChain(block.getInputTargetBlock("YES"), node.yes?.then || [])) { changed = true; }
    if (assignChain(block.getInputTargetBlock("NO"), node.no?.then || [])) { changed = true; }
  } else if (block.type === Q_SCORE_BLOCK) {
    (node.outcomes || []).forEach((oc, i) => {
      if (assignChain(block.getInputTargetBlock(`LVL_${i}`), oc?.then || [])) { changed = true; }
    });
  } else if (block.type === BRANCH_BLOCK) {
    if (assignChain(block.getInputTargetBlock("DO"), node.then || [])) { changed = true; }
  }
  return changed;
}

/** Разложить id из store обратно по блокам (нужно развилкам и стабильности). */
export function writeBackIds(workspace, rules) {
  let changed = false;
  const tops = workspace.getTopBlocks(true).filter((b) => NODE_TYPES.includes(b.type));
  const pairs = Math.min(tops.length, rules.length);
  for (let i = 0; i < pairs; i++) {
    if (assignIds(tops[i], rules[i])) { changed = true; }
  }
  if (changed) { refreshBranchFields(workspace); }
  return changed;
}
/* ── шаблоны-«семечки»: разворачиваются только на поле ─── */

export function expandTemplateBlock(workspace, seed) {
  const key = seed.getFieldValue("TPL");
  const tpl = TEMPLATES.find((t) => t.key === key);
  if (!tpl) { seed.dispose(false, false); return null; }
  let pt = { x: 16, y: 16 };
  try { pt = seed.getRelativeToSurfaceXY(new BLY.utils.Coordinate(0, 0)); } catch { /* noop */ }
  const json = nodeToJson(tpl.tree);
  if (!json) { seed.dispose(false, false); return null; }
  json.x = pt.x;
  json.y = pt.y;
  let head = null;
  try {
    head = BLY.serialization.blocks.append(json, workspace);
  } catch (err) {
    console.warn("Шаблон не вставился:", err);
    seed.dispose(false, false);
    return null;
  }
  seed.dispose(false, false);
  try { head?.select?.(); } catch { /* noop */ }
  return head;
}

/** Слушатель: как только шаблон-семечко появился на поле — развернуть его. */
export function attachTemplateExpander(workspace) {
  if (!workspace) { return; }
  workspace.addChangeListener((e) => {
    const isCreate = e.type === "create" || (e.type === "block" && e.reason === "create");
    if (!isCreate) { return; }
    const seed = workspace.getBlockById(e.blockId);
    if (!seed || seed.type !== TPL_BLOCK) { return; }
    // После завершения drag-сессии из flyout — короткая отложенная вставка.
    setTimeout(() => {
      if (!seed.disposed) { expandTemplateBlock(workspace, seed); }
    }, 60);
  });
}
