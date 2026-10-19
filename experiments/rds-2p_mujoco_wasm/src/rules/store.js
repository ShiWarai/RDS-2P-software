/**
 * Хранилище вопросов/развилок и пользовательских поз (localStorage).
 *
 * Модель v3 — ДЕРЕВО потока (каскад):
 *   { kind:'start',    id, then:[узлы] }
 *   { kind:'question', id, qtype:'choice', name, instructions,
 *         options:[{id, name, examples, then:[узлы]}] }
 *   { kind:'question', id, qtype:'noul',  name, instructions, yes:{then}, no:{then} }
 *   { kind:'question', id, qtype:'score', name, instructions, levels:[...],
 *         outcomes:[{then:[узлы]} | null, ...] }
 *   { kind:'branch',   id, ref:'<qid>::<sel>', op, value, then:[узлы] }
 *   { kind:'command'|'pose'|'wait'|'say', ... }
 *
 * Миграции: v1 (правила+привратники) → v2 (плоские вопросы) → v3 (дерево).
 */

import { MOTOR_COMMANDS } from "./catalog.js";

const RULES_KEY = "panda.rules.v1";
const POSES_KEY = "panda.poses.v1";
const PRESET_URL = "assets/rules/panda_rules.json";

const LEGACY_JUNK = /фокус|что умеешь|список команд|подсказк|доклад|пульт|молчи|тише/i;

function uid(prefix = "r") {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}${Date.now().toString(36).slice(-3)}`;
}

export const DEFAULT_POSE = () => new Array(12).fill(0.5);

const motorIds = new Set(MOTOR_COMMANDS.map((c) => c.id));

/** Шаги старого действия: выкидываем UI-шаги и исчезнувшие команды. */
function cleanSteps(steps) {
  return (steps || []).filter(
    (s) => s.kind !== "ui" && (s.kind !== "command" || motorIds.has(s.command))
  );
}

/** Старые шаги действия → узлы дерева v3. */
function stepsToNodes(steps) {
  const nodes = [];
  for (const s of cleanSteps(steps)) {
    if (s.kind === "command") { nodes.push({ kind: "command", command: s.command }); }
    else if (s.kind === "pose") { nodes.push({ kind: "pose", pose: s.pose, hold_ms: s.hold_ms ?? s.hold ?? 500 }); }
    else if (s.kind === "wait") { nodes.push({ kind: "wait", ms: s.ms ?? 500 }); }
    else if (s.kind === "say") { nodes.push({ kind: "say", text: s.text ?? "" }); }
  }
  return nodes;
}

/** Это уже дерево v3? */
function isV3(nodes) {
  if (!Array.isArray(nodes) || !nodes.length) { return true; }
  return nodes.some(
    (n) => n && (n.kind === "start" || n.then !== undefined
      || ["command", "pose", "wait", "say"].includes(n.kind))
  );
}

/**
 * Миграция v1 (правила + gate) → v2 (плоские вопросы) — как раньше.
 * @returns {Array|null}
 */
export function migrateLegacyRules(rules) {
  if (!Array.isArray(rules) || !rules.length) { return null; }
  const legacy = rules.some((r) => r.kind === "gate")
    || rules.some((r) => r.kind == null);
  if (!legacy) { return null; }

  const options = [];
  const questions = [];
  for (const r of rules) {
    if (r.kind === "gate") {
      const qtype = r.qtype === "score" ? "score" : "noul";
      questions.push({
        id: r.id || uid("q"),
        kind: "question",
        qtype,
        name: r.name || "Проверка",
        instructions: r.name || "Проверка",
        levels: qtype === "score" ? (r.levels || []) : undefined,
      });
      continue;
    }
    const hay = `${r.name || ""} ${(r.examples || []).join(" ")}`;
    if (LEGACY_JUNK.test(hay)) { continue; }
    const steps = cleanSteps(r.action?.steps);
    if ((r.action?.steps || []).length && !steps.length) { continue; }
    options.push({
      id: r.id || uid("o"),
      name: r.name || (r.examples || [])[0] || "Вариант",
      examples: r.examples || [],
      action: { type: "chain", steps },
    });
  }
  const out = [];
  if (options.length) {
    out.push({
      id: "q_commands",
      kind: "question",
      qtype: "choice",
      name: "Команды",
      instructions: "Какая команда подходит к фразе?",
      options,
    });
  }
  out.push(...questions);
  return out.length ? out : null;
}

/** Миграция v2 (плоская) → v3 (дерево). @returns {Array|null} */
export function migrateV2toV3(nodes) {
  if (!Array.isArray(nodes) || !nodes.length) { return null; }
  if (isV3(nodes)) { return null; }
  const out = [];
  for (const r of nodes) {
    if (r.kind === "question" && r.qtype === "choice") {
      out.push({
        id: r.id, kind: "question", qtype: "choice", name: r.name, instructions: r.instructions,
        options: (r.options || []).map((o) => ({
          id: o.id, name: o.name || o.id, examples: o.examples || [],
          then: stepsToNodes(o.action?.steps),
        })),
      });
    } else if (r.kind === "question" && r.qtype === "noul") {
      out.push({
        id: r.id, kind: "question", qtype: "noul", name: r.name, instructions: r.instructions,
        yes: { then: stepsToNodes(r.yes?.action?.steps) },
        no: { then: stepsToNodes(r.no?.action?.steps) },
      });
    } else if (r.kind === "question" && r.qtype === "score") {
      out.push({
        id: r.id, kind: "question", qtype: "score", name: r.name, instructions: r.instructions,
        levels: r.levels || [],
        outcomes: (r.levels || []).map(() => null),
      });
    } else if (r.kind === "branch") {
      out.push({
        id: r.id, kind: "branch", ref: r.ref, op: r.op, value: r.value,
        then: stepsToNodes(r.action?.steps),
      });
    }
  }
  return out.length ? out : null;
}

/** Выпиленные команды (например «ходьба»: режим переехал на кнопку+WASD) —
 *  вычищаем и из сохранённых правил v3, чтобы в блоках не оставалось «— команда —». */
function dropRetiredCommands(node) {
  if (!node || typeof node !== "object") { return node; }
  if (node.kind === "command" && !motorIds.has(node.command)) { return null; }
  const kids = (arr) => (arr || []).map(dropRetiredCommands).filter(Boolean);
  if (node.then) { node.then = kids(node.then); }
  if (node.options) { node.options = node.options.map((o) => (o ? { ...o, then: kids(o.then) } : o)); }
  if (node.outcomes) { node.outcomes = node.outcomes.map((o) => (o ? { ...o, then: kids(o.then) } : o)); }
  if (node.yes) { node.yes = kids(node.yes); }
  if (node.no) { node.no = kids(node.no); }
  return node;
}

function normalizeLoaded(nodes) {
  let cur = nodes;
  const v2 = migrateLegacyRules(cur);
  if (v2) { cur = v2; }
  const v3 = migrateV2toV3(cur);
  if (v3) { cur = v3; }
  return cur.map(dropRetiredCommands).filter(Boolean);
}

/* ── рекурсивный merge id ─────────────────────────── */

function mergeChain(newNodes, oldNodes, used) {
  const olds = (oldNodes || []).filter(Boolean);
  return (newNodes || []).map((n, i) => mergeNode(n, olds[i], used));
}

function pickId(newNode, oldNode, used, prefix) {
  if (newNode.id && !used.has(newNode.id)) { return newNode.id; }
  if (oldNode && oldNode.id && !used.has(oldNode.id)) { return oldNode.id; }
  return uid(prefix);
}

function mergeNode(newNode, oldNode, used) {
  if (!newNode) { return newNode; }
  const same = oldNode && oldNode.kind === newNode.kind;
  switch (newNode.kind) {
    case "start": {
      const id = pickId(newNode, same ? oldNode : null, used, "s");
      used.add(id);
      return { ...newNode, id, then: mergeChain(newNode.then, same ? oldNode.then : [], used) };
    }
    case "question": {
      if (newNode.qtype !== (same ? oldNode.qtype : null)) { oldNode = null; }
      const id = pickId(newNode, oldNode, used, "q");
      used.add(id);
      const item = { ...newNode, id, name: newNode.name || id };
      if (item.qtype === "choice") {
        const olds = (oldNode?.options || []).filter(Boolean);
        item.options = (newNode.options || []).map((o, i) => {
          let old = olds.find((x) => x.id === o.id && !used.has(x.id)) || null;
          if (!old) { old = olds.find((x) => x.name === o.name && x.id && !used.has(x.id)) || null; }
          if (!old && olds[i] && !used.has(olds[i].id)) { old = olds[i]; }
          const oid = pickId(o, old, used, "o");
          used.add(oid);
          return {
            ...o, id: oid,
            name: o.name || (o.examples || [])[0] || oid,
            examples: dedupeStrings(o.examples || []),
            then: mergeChain(o.then, old?.then || [], used),
          };
        });
      } else if (item.qtype === "noul") {
        item.yes = { then: mergeChain(newNode.yes?.then, oldNode?.yes?.then || [], used) };
        item.no = { then: mergeChain(newNode.no?.then, oldNode?.no?.then || [], used) };
      } else if (item.qtype === "score") {
        const olds = (oldNode?.outcomes || []);
        item.outcomes = (newNode.levels || []).map((_l, i) => {
          const oc = (newNode.outcomes || [])[i] || null;
          const old = olds[i] || null;
          if (!oc) { return null; }
          return { then: mergeChain(oc.then, old?.then || [], used) };
        });
      }
      return item;
    }
    case "branch": {
      const id = pickId(newNode, same ? oldNode : null, used, "b");
      used.add(id);
      return { ...newNode, id, then: mergeChain(newNode.then, same ? oldNode.then : [], used) };
    }
    default:
      return { ...newNode };
  }
}

/** Слить весь список корней: пары — по id, затем по (тип+имя), затем по типу. */
export function mergeRoots(incoming, oldRules) {
  const olds = (oldRules || []).filter(Boolean);
  const claimed = new Set();
  const pairs = (incoming || []).map((n) => {
    if (!n) { return null; }
    if (n.id) {
      const byId = olds.find((x) => x.id === n.id && !claimed.has(x.id));
      if (byId) { claimed.add(byId.id); return byId; }
    }
    const sameKind = olds.filter((x) => x.kind === n.kind && !claimed.has(x.id));
    const byName = n.name ? sameKind.find((x) => x.name === n.name) : null;
    const o = byName || sameKind[0] || null;
    if (o) { claimed.add(o.id); }
    return o;
  });
  const used = new Set();
  return (incoming || []).map((n, i) => mergeNode(n, pairs[i], used));
}

export class Store {
  constructor() {
    this.rules = [];
    this.userPoses = new Map();
    this.preset = null;
  }

  async init() {
    try {
      const res = await fetch(PRESET_URL);
      this.preset = await res.json();
    } catch (err) {
      console.warn("Не удалось загрузить пресет правил:", err);
      this.preset = { name: "Каскад Панды", rules: [] };
    }
    this.load();
  }

  load() {
    try {
      const rawRules = localStorage.getItem(RULES_KEY);
      const rawPoses = localStorage.getItem(POSES_KEY);
      if (rawRules) {
        const parsed = JSON.parse(rawRules);
        if (Array.isArray(parsed)) {
          const migrated = normalizeLoaded(parsed);
          this.rules = migrated;
          if (migrated !== parsed) { this.save(); }
        }
      }
      if (rawPoses) {
        const parsed = JSON.parse(rawPoses);
        if (parsed && typeof parsed === "object") {
          this.userPoses = new Map(Object.entries(parsed));
        }
      }
    } catch (err) {
      console.warn("localStorage повреждён, начинаем с пресета:", err);
      this.rules = [];
      this.userPoses = new Map();
    }
    if (!localStorage.getItem(RULES_KEY)) {
      this.resetToPreset();
    }
  }

  save() {
    try {
      localStorage.setItem(RULES_KEY, JSON.stringify(this.rules));
      localStorage.setItem(POSES_KEY, JSON.stringify(Object.fromEntries(this.userPoses)));
    } catch (err) {
      console.warn("Не удалось сохранить в localStorage:", err);
    }
  }

  resetToPreset() {
    this.rules = normalizeLoaded(structuredClone(this.preset?.rules ?? []));
    this.save();
  }

  /** incoming — корни дерева из Blockly (см. workspace.blocksToRules). */
  setRulesFromBlocks(incoming) {
    this.rules = mergeRoots(incoming, this.rules);
    this.save();
    return this.rules;
  }

  addPose(name, values) {
    const clean = Array.from(values).map((x) => Math.min(1, Math.max(0, Number(x) || 0.5)));
    this.userPoses.set(name, clean);
    this.save();
    return clean;
  }

  removePose(name) {
    this.userPoses.delete(name);
    this.save();
  }

  poseNames() {
    return [...this.userPoses.keys()];
  }

  /** Разрешение имени позы: сначала пользовательские, потом пресеты поз. */
  resolvePose(name, presetPoses) {
    if (this.userPoses.has(name)) { return this.userPoses.get(name); }
    return presetPoses?.[name] ?? null;
  }

  exportJSON() {
    return JSON.stringify(
      {
        kind: "panda-workshop",
        version: 3,
        exported: new Date().toISOString(),
        rules: this.rules,
        poses: Object.fromEntries(this.userPoses),
      },
      null,
      2
    );
  }

  importJSON(text) {
    const data = JSON.parse(text);
    if (!data || !Array.isArray(data.rules)) {
      throw new Error("В файле нет массива «rules»");
    }
    this.rules = normalizeLoaded(data.rules);
    if (data.poses && typeof data.poses === "object") {
      for (const [name, vals] of Object.entries(data.poses)) {
        if (Array.isArray(vals) && vals.length === 12) {
          this.userPoses.set(name, vals.map((x) => Number(x)));
        }
      }
    }
    this.save();
    return this.rules;
  }
}

export function dedupeStrings(arr) {
  const seen = new Set();
  const out = [];
  for (const s of arr) {
    const key = String(s).trim().toLowerCase();
    if (!key || seen.has(key)) { continue; }
    seen.add(key);
    out.push(String(s).trim());
  }
  return out;
}