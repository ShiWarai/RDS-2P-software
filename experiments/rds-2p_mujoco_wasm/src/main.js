import { Simulator } from "./sim/sim.js";
import { Store } from "./rules/store.js";
import { compileAction } from "./rules/to_program.js";
import { NluEngine } from "./nlu/nlu.js";
import { LayaBrowserBackend } from "./nlu/laya_browser.js";
import { SpeechListener, speechSupported } from "./speech/recognizer.js";
import { VoskStt, voskSupported, voskWarmup, voskWarmupError, voskModelReady, isSecure } from "./speech/vosk_stt.js";
import { MANUAL_BUTTONS, programForCommand, commandLabel } from "./robot/motions.js";
import { PoseManager } from "./sim/poseManager.js";
import {
  initBlocks,
  toolboxJson,
  rulesToBlocks,
  blocksToRules,
  writeBackIds,
  refreshPoseFields,
  refreshBranchFields,
  setPoseOptionsProvider,
  clearRunMarks,
  setBadgeOnBlock,
  flashBlock,
  actionStepFromBlock,
  splitPhrases,
  attachTemplateExpander,
  START_BLOCK,
  NODE_TYPES,
  OPTION_BLOCK,
  Q_CHOICE_BLOCK,
  Q_NOUL_BLOCK,
  Q_SCORE_BLOCK,
  BRANCH_BLOCK,
  COMMAND_BLOCK,
  POSE_BLOCK,
  WAIT_BLOCK,
  SAY_BLOCK,
} from "./blocks/workspace.js";
import { buildSliderPanel, buildCommandButtons, toast } from "./ui/panels.js";
import { parseRef, refValueForRes, compareOp, fmtP, fmtValue } from "./rules/to_laya.js";

const app = {
  sim: null,
  store: new Store(),
  presetPoses: {},
  poseAngles: {},
  nlu: null,
  workspace: null,
  lastText: "",
  sliders: { pose: null },
};

const $ = (id) => document.getElementById(id);

function resolvePose(name) {
  if (app.store.userPoses.has(name)) { return app.store.userPoses.get(name); }
  return app.presetPoses[name] ?? null;
}

/** Точные углы суставов именованной позы робота (assets/pose_angles.json) или null. */
function resolvePoseAngles(name) {
  if (app.store?.userPoses?.has(name)) { return null; }
  return app.poseAngles[name] ?? null;
}

async function loadPresetPoses() {
  const [posesRes, anglesRes] = await Promise.all([
    fetch("./assets/poses.json"),
    fetch("./assets/pose_angles.json"),
  ]);
  app.presetPoses = (await posesRes.json()).poses || {};
  const raw = (await anglesRes.json()).poses || {};
  // Таблица — в конвенции ROS-моста; симулятор в ТОЙ ЖЕ конвенции (контрольная
  // сверка: тренировочные keyframes pre_recovery/lying_down совпадают с позами
  // робота по знакам 1-в-1: lb +,−,+,− и положительные hips). Поэтому конверсия —
  // тождественная, БЕЗ инверсий. (Перебор с зеркалами был ошибкой: инверсия таза
  // давала присед мордой вниз, всех 12 — стойку на задних лапах, только колена —
  // задние лапы разгибались вместо поджима.)
  app.poseAngles = Object.fromEntries(
    Object.entries(raw).map(([name, row]) => [name, toSimAngles(row)]),
  );
}

/** ROS-мост → MJCF: конвенции совпадают, конверсия тождественная. */
function toSimAngles(row) {
  return row.slice();
}

function poseOptions() {
  const safePresets = Object.keys(app.presetPoses)
    .filter((n) => !PoseManager.isNoLimit(app.presetPoses[n]))
    .map((n) => [`🐾 ${humanPoseName(n)}`, n]);
  const mine = app.store.poseNames().map((n) => [`✨ ${n}`, n]);
  return [["🐾 поза…", ""], ...safePresets, ...mine];
}

const POSE_TITLES = {
  position_0: "стоять",
  position_1: "отставить",
  position_2: "равняйся",
  position_give: "дать лапу",
};

function humanPoseName(n) {
  return POSE_TITLES[n] || n.replace(/^position_/, "").replace(/_/g, " ") || n;
}

/* ── прогон каскада: Старт → вопросы → развилки → движение ── */

let busy = false;

function specFromBlock(block) {
  if (block.type === Q_CHOICE_BLOCK) {
    const options = [];
    let child = block.getInputTargetBlock("OPTS");
    let i = 0;
    while (child) {
      if (child.type === OPTION_BLOCK) {
        options.push({
          id: child.data || `tmp${i}`,
          name: String(child.getFieldValue("NAME") || "").trim() || `Вариант ${i + 1}`,
          examples: splitPhrases(child.getFieldValue("EXAMPLES")),
        });
      }
      child = child.getNextBlock();
      i++;
    }
    return {
      id: block.data || undefined,
      qtype: "choice",
      name: String(block.getFieldValue("NAME") || "Выбор"),
      instructions: String(block.getFieldValue("ASK") || "").trim(),
      options,
    };
  }
  if (block.type === Q_NOUL_BLOCK) {
    return {
      id: block.data || undefined,
      qtype: "noul",
      name: String(block.getFieldValue("NAME") || "Да/нет"),
      instructions: String(block.getFieldValue("ASK") || "").trim(),
    };
  }
  return {
    id: block.data || undefined,
    qtype: "score",
    name: String(block.getFieldValue("NAME") || "Шкала"),
    instructions: String(block.getFieldValue("ASK") || "").trim(),
    levels: splitPhrases(block.getFieldValue("LEVELS")),
  };
}

function nthOption(block, idx) {
  let child = block.getInputTargetBlock("OPTS");
  let i = 0;
  while (child) {
    if (child.type === OPTION_BLOCK) {
      if (i === idx) { return child; }
      i++;
    }
    child = child.getNextBlock();
  }
  return null;
}

/** Бейджи вероятностей прямо на блоках вопроса. */
function markQuestionOnBlocks(block, spec, res) {
  if (spec.qtype === "choice") {
    let child = block.getInputTargetBlock("OPTS");
    let i = 0;
    while (child) {
      if (child.type === OPTION_BLOCK) {
        const row = res.rows[i];
        if (row) { setBadgeOnBlock(child, "BADGE", fmtP(row.p)); }
        i++;
      }
      child = child.getNextBlock();
    }
    setBadgeOnBlock(block, "BADGE", res.mode ? `${res.mode.label} ${fmtP(res.mode.p)}` : "—");
  } else if (spec.qtype === "noul") {
    const pTrue = res.rows.find((r) => r.key === "true")?.p ?? 0;
    const pFalse = res.rows.find((r) => r.key === "false")?.p ?? 0;
    setBadgeOnBlock(block, "BADGE_YES", fmtP(pTrue));
    setBadgeOnBlock(block, "BADGE_NO", fmtP(pFalse));
  } else {
    setBadgeOnBlock(block, "BADGE", res.mode
      ? `${res.mode.label} ${fmtP(res.mode.p)} · балл ${res.score.toFixed(2)}`
      : `балл ${res.score.toFixed(2)}`);
    res.rows.forEach((row, i) => setBadgeOnBlock(block, `BADGE_LVL_${i}`, fmtP(row.p)));
  }
}

async function walkQuestion(block, ctx, actions) {
  const spec = specFromBlock(block);
  let res;
  try {
    res = await app.nlu.askQuestion(spec, app.lastText);
  } catch (err) {
    setBadgeOnBlock(block, spec.qtype === "noul" ? "BADGE_YES" : "BADGE", "сбой");
    toast(`Вопрос «${spec.name}» не прошёл: ${String(err?.message || err)}`, { kind: "err" });
    return false;
  }
  if (block.data) { ctx.results.set(block.data, res); }
  markQuestionOnBlocks(block, spec, res);
  flashBlock(block, app.workspace);

  // Каскад: идём по выбранной ветке.
  if (spec.qtype === "choice") {
    const idx = res.rows.indexOf(res.mode);
    const optionBlock = nthOption(block, idx);
    if (optionBlock) {
      flashBlock(optionBlock, app.workspace);
      return walkChain(optionBlock.getInputTargetBlock("DO"), ctx, actions);
    }
    return true;
  }
  if (spec.qtype === "noul") {
    const child = block.getInputTargetBlock(res.mode?.key === "true" ? "YES" : "NO");
    return walkChain(child, ctx, actions);
  }
  const m = /^level:(\d+)$/.exec(res.mode?.key || "");
  if (m) {
    return walkChain(block.getInputTargetBlock(`LVL_${m[1]}`), ctx, actions);
  }
  return true;
}

async function walkStatement(block, ctx, actions) {
  if (!block) { return true; }
  switch (block.type) {
    case START_BLOCK:
      flashBlock(block, app.workspace);
      return walkChain(block.getNextBlock(), ctx, actions);
    case Q_CHOICE_BLOCK:
    case Q_NOUL_BLOCK:
    case Q_SCORE_BLOCK:
      return walkQuestion(block, ctx, actions);
    case BRANCH_BLOCK: {
      const ref = parseRef(block.getFieldValue("EVENT"));
      const res = ref ? ctx.results.get(ref.qid) : null;
      const val = ref && res ? refValueForRes(res, ref.sel) : null;
      const target = Number(block.getFieldValue("VALUE"));
      const op = block.getFieldValue("OP");
      const ok = val != null && compareOp(val, op, target);
      setBadgeOnBlock(block, "BADGE", val == null ? "—" : `${fmtValue(val)} ${ok ? "✓" : "✗"}`);
      if (ok) {
        flashBlock(block, app.workspace);
        return walkChain(block.getInputTargetBlock("DO"), ctx, actions);
      }
      return true;
    }
    case COMMAND_BLOCK:
    case POSE_BLOCK:
    case WAIT_BLOCK:
    case SAY_BLOCK: {
      flashBlock(block, app.workspace);
      const step = actionStepFromBlock(block);
      if (step) { actions.push(step); }
      return true;
    }
    default:
      return true;
  }
}

async function walkChain(first, ctx, actions) {
  let block = first;
  while (block) {
    const ok = await walkStatement(block, ctx, actions);
    if (!ok) { return false; }
    block = block.getNextBlock();
  }
  return true;
}

async function runFlow() {
  const text = $("phrase-input").value.trim();
  if (!text) { toast("Напиши фразу или скажи голосом 🎤", { kind: "err" }); return; }
  app.lastText = text;
  if (busy) { return; }
  const ws = app.workspace;
  clearRunMarks(ws);
  $("run-time").textContent = "⏱ …";

  const tops = ws.getTopBlocks(true).filter((b) => NODE_TYPES.includes(b.type));
  const starts = tops.filter((b) => b.type === START_BLOCK);
  const roots = starts.length ? starts : tops;
  if (!roots.length) {
    toast("🧩 Вытащи блок из «🎲 Вопросы» или «📦 Шаблоны» слева", { kind: "err" });
    $("run-time").textContent = "⏱ —";
    return;
  }
  if (!app.nlu.available) {
    toast("🧠 Модель ИИ не загружена — дождись загрузки (пилюля сверху)", { kind: "err", timeout: 9000 });
    $("run-time").textContent = "⏱ —";
    return;
  }

  busy = true;
  $("btn-check").classList.add("processing");
  const ctx = { results: new Map() };
  const actions = [];
  const t0 = performance.now();
  try {
    for (const root of roots) {
      const ok = await walkStatement(root, ctx, actions);
      if (!ok) { return; }
    }
    const ms = Math.round(performance.now() - t0);
    $("run-time").textContent = `⏱ ${(ms / 1000).toFixed(1)} с`;
    if (actions.length) {
      await playSteps(actions, "Панда действует");
    } else if ($("hud-status").textContent === "🐼 Панда ждёт команд") {
      $("hud-status").textContent = "📊 вероятности — на блоках";
    }
  } finally {
    busy = false;
    $("btn-check").classList.remove("processing");
  }
}

/* ── воспроизведение (с ленивой загрузкой политики ходьбы) ── */

async function ensurePolicy() {
  const policy = app.sim?.policy;
  if (!policy) { return false; }
  if (policy.available) { return true; }
  // Пилюлю рисует подписка на policy.onStatus (прогресс/докачка/повтор),
  // а load() ждёт текущую попытку и перезапускает её после терминального сбоя.
  return policy.load();
}

async function playSteps(steps, note) {
  if (steps.some((s) => s.kind === "policy" && !s.stop)) {
    const policy = app.sim?.policy;
    if (policy && !policy.available) {
      $("hud-status").textContent = "Панда: ждёт загрузку нейросети ходьбы…";
    }
    const ok = await ensurePolicy();
    if (!ok) {
      // «Запасного варианта» нет: ходьбу умеет только нейросеть, а её модель
      // докачивается сама (Range + ретраи, см. policyRunner.js). Сюда попадаем
      // лишь при явной HTTP 4xx — модель отсутствует на сервере.
      toast("Нейросеть ходьбы не готова 🕹️ посмотри статус у пилюли", { kind: "err", timeout: 9000 });
      $("hud-status").textContent = "🐼 Панда ждёт нейросеть ходьбы";
      return;
    }
  }
  runProgram(steps, note);
}

function runProgram(steps, note) {
  if (!app.sim || !app.sim.model) { toast("Симулятор ещё не готов.", { kind: "err" }); return; }
  if (app.sim.paused) { toast("Панда на паузе: жми ▶️", { kind: "err" }); return; }
  if (note) { $("hud-status").textContent = note; }
  app.sim.onStep = (label, step) => {
    if (step?.kind === "say") { app.sim.say(step.text); }
    if (label) { $("hud-status").textContent = `Панда: ${label}`; }
  };
  app.sim.play(steps);
}

async function runCommand(id) {
  const prog = programForCommand(id);
  if (prog) { await playSteps(prog, `Панда: ${commandLabel(id)}`); }
}

/* ── микрофон ────────────────────────────────────── */

let speech = null;      // запасной вариант: встроенный Web Speech API
let vosk = null;        // основной: офлайн-распознавание в браузере
let preferVosk = true;

const MIC_STATES = {
  idle: "🎤",
  listening: "🏳️",
  decoding: "🧠",
};

function micToastState(state) {
  const hud = $("hud-status");
  if (state === "listening") { hud.textContent = "👂 Слушаю! Скажи фразу и нажми 🏳️"; }
  else if (state === "decoding") { hud.textContent = "🧠 Распознаю…"; }
  else { hud.textContent = "🐼 Панда ждёт команд"; }
}

/* Живая расшифровка: буквы летят в поле прямо во время речи. */
function onVoicePartial(t) {
  const text = String(t || "").trim();
  if (!text) { return; }
  $("phrase-input").value = text;
}

function onVoiceText(t) {
  const text = String(t || "").trim();
  if (!text) {
    toast("Ничего не расслышала 🙉 нажми 🎤 и скажи ещё раз", { kind: "err" });
    return;
  }
  const input = $("phrase-input");
  input.value = text;
  $("hud-status").textContent = "✍️ Написала в поле — жми ▶, если всё верно";
  input.focus();
}

const $bar = (id, { frac, label }) => {
  const el = $(id);
  el.classList.remove("hidden");
  el.querySelector(".loadbar-fill").style.width = `${Math.round(frac * 100)}%`;
  el.querySelector(".loadbar-pct").textContent = `${Math.round(frac * 100)}%`;
  if (frac >= 1) { el.classList.add("done"); }
};
const hideBar = (id) => { $(id).classList.add("hidden"); };

function setMicEnabled(on, why) {
  const btn = $("btn-mic");
  btn.disabled = !on;
  btn.title = on ? "Сказать фразу Панде (офлайн-распознавание)" : (why || "Голос ещё не готов…");
}

function setVoicePill(cls, text, why) {
  const p = $("pill-voice");
  if (!p) { return; }
  p.classList.remove("hidden");
  p.className = `pill ${cls}`;
  p.textContent = text;
  if (why) { p.title = why; }
}

function setPolicyPill(cls, text, why) {
  const p = $("pill-policy");
  if (!p) { return; }
  p.classList.remove("hidden");
  p.className = `pill ${cls}`;
  p.textContent = text;
  if (why) { p.title = why; }
}

function warmVoice() {
  setVoicePill("busy", "🎙 Готовлю голос…", "Скачиваю и распаковываю офлайн-модель распознавания");
  $bar("bar-voice", { frac: 0 });
  voskWarmup((ev) => {
    $bar("bar-voice", ev);
    if (ev.frac >= 1) {
      setVoicePill("busy", "🎙 Распаковываю…", "Модель скачана, идёт распаковка в память");
    } else {
      setVoicePill("busy", `🎙 Голос ${Math.round(ev.frac * 100)}%`, "Докачка офлайн-модели распознавания");
    }
  }).then((ok) => {
    if (ok) {
      setTimeout(() => hideBar("bar-voice"), 350);
      setMicEnabled(true);
      setVoicePill("ok", "🎙 Голос готов", "Офлайн-распознавание Vosk загружено — жми 🎤 и говори");
      return;
    }
    hideBar("bar-voice");
    const why = voskWarmupError() || "неизвестно";
    if (speechSupported) {
      preferVosk = false;
      setMicEnabled(true);
      setVoicePill("bad", "🎙 Голос: сбой", `Vosk не поднялся (${why}). Клик — повторить; пока доступно браузерное распознавание`);
      toast("Офлайн-голос не поднялся (" + why + ") — пробую браузерное распознавание", { kind: "err", timeout: 9000 });
    } else {
      setMicEnabled(false, "Голос недоступен: " + why);
      setVoicePill("bad", "🎙 Голос: сбой", `Клик — попробовать ещё раз. Причина: ${why}`);
      toast("Голос не загрузился: " + why + " — напиши фразу в поле 📝", { kind: "err", timeout: 10000 });
    }
  });
  $("pill-voice").onclick = () => {
    if (voskSupported() && !voskModelReady()) { warmVoice(); }
  };
}

function initSpeech() {
  const btn = $("btn-mic");
  const setBtn = (state) => {
    btn.classList.toggle("on", state === "listening" || state === "decoding" || state === "loading-model");
    btn.textContent = MIC_STATES[state] || "🎤";
    if (state === "listening") { btn.title = "Стоп — распознать то, что сказала панда"; }
    else if (state === "idle") { btn.title = "Сказать фразу Панде (офлайн-распознавание)"; }
  };
  const handleError = (code) => {
    if (code === "not-allowed") { toast("Дай доступ к микрофону 🎤 (замóк в адресной строке → Микрофон → Разрешить)", { kind: "err", timeout: 9000 }); }
    else if (code === "no-device" || code === "audio-capture") { toast("Микрофон не найден 🎤 напиши фразу в поле и жми ▶", { kind: "err" }); }
    else if (code === "network") { toast("Голосовой сервис браузера недоступен — включён офлайн-режим, нажми 🎤 ещё раз", { kind: "err", timeout: 8000 }); }
    else if (code === "load") { toast("Не удалось загрузить офлайн-распознавание — попробуй ещё раз или напиши фразу", { kind: "err" }); }
    else if (code === "unsupported") { toast("Браузер не умеет распознавание речи — пиши фразы в поле 📝", { kind: "err" }); }
  };

  if (voskSupported()) {
    vosk = new VoskStt({
      onText: onVoiceText,
      onPartial: onVoicePartial,
      onState: (st) => { setBtn(st); micToastState(st); },
      onError: handleError,
    });
    warmVoice();
  } else if (speechSupported) {
    setMicEnabled(true);
    setVoicePill("busy", "🎙 Браузерный голос", "Встроенное распознавание Chrome (нужен интернет)");
  } else {
    setMicEnabled(false, "Этот браузер не умеет распознавание — пиши в поле 📝");
    setVoicePill("bad", "🎙 Голос недоступен", "Ни WASM-распознавания, ни Web Speech");
  }

  const ensureWebSpeech = () => {
    if (speech || !speechSupported) { return speech; }
    speech = new SpeechListener({
      onState: (state) => { setBtn(state === "listening" ? "listening" : "idle"); },
      onInterim: (t) => { onVoicePartial(t); },
      onText: onVoiceText,
      onError: handleError,
    });
    return speech;
  };

  btn.onclick = async () => {
    if (!isSecure() && !window.isSecureContext) {
      toast(`Микрофон заблокирован: адрес «${location.host}» небезопасный. Открой localhost или запусти «python3 tools/serve.py --https» 🔒`, { kind: "err", timeout: 10000 });
      $("phrase-input").focus();
      return;
    }
    if (preferVosk && vosk) {
      try { await vosk.toggle(); return; }
      catch { preferVosk = false; ensureWebSpeech()?.toggle(); }
    } else if (speechSupported) {
      ensureWebSpeech()?.toggle();
    } else {
      handleError("unsupported");
      $("phrase-input").focus();
    }
  };
}

/* ── управление политикой: клик по симулятору + WASD/стрелки ── */

let driving = false;
const drivingKeys = new Set();

function keyCmd(code) {
  // Управление — ТОЛЬКО стрелками: WASD больше не перехватываем, чтобы буквы
  // свободно печатались в полях и работали как обычные горячие клавиши.
  switch (code) {
    case "ArrowUp": return [1, 0, 0];
    case "ArrowDown": return [-0.5, 0, 0];
    case "ArrowLeft": return [0, 0, 0.8];
    case "ArrowRight": return [0, 0, -0.8];
    default: return null;
  }
}

function currentCmd() {
  let fwd = 0;
  let turn = 0;
  for (const code of drivingKeys) {
    const c = keyCmd(code);
    if (!c) { continue; }
    fwd += c[0];
    turn += c[2];
  }
  fwd = Math.max(-0.5, Math.min(1, fwd));
  turn = Math.max(-0.8, Math.min(0.8, turn));
  return [fwd, 0, turn];
}

/** Подсказка про стрелки — только пока активен режим «Ходьба». */
function updateDriveHint() {
  const el = $("drive-hint");
  if (!el) { return; }
  const on = driving && Boolean(app.sim?.player?.policyOn);
  el.classList.toggle("hidden", !on);
}

function enableDriving() {
  if (driving) { return; }
  driving = true;
  $("sim").classList.add("driving");
  updateDriveHint();
  // Политика стартует ещё на boot (параллельно голосу и ИИ), но если её
  // отложили — догружаем сейчас; пилюля покажет прогресс через onStatus.
  if (app.sim?.policy && !app.sim.policy.available) {
    app.sim.policy.load();
  }
}

function disableDriving(stop) {
  if (!driving) { return; }
  driving = false;
  drivingKeys.clear();
  $("sim").classList.remove("driving");
  updateDriveHint();
  if (stop && app.sim?.player?.policyOn) {
    app.sim.player.stopPolicy();
    $("hud-status").textContent = "🐼 Панда встала";
  }
}

let hintAt = 0;
function hintOnce(msg) {
  const now = performance.now();
  if (now - hintAt < 3500) { return; }
  hintAt = now;
  toast(msg, { kind: "err" });
}

async function applyDriving() {
  const p = app.sim?.player;
  if (!p) { return; }
  // Управление — только когда работает режим «Ходьба» (политика активна).
  if (!p.policyOn) {
    const cmd = currentCmd();
    if (cmd[0] !== 0 || cmd[2] !== 0) {
      hintOnce("🚶 Управление работает только в режиме «Ходьба» — нажми кнопку 🚶, потом рули стрелками (после клика по симулятору)");
    }
    return;
  }
  updateDriveHint();
  const cmd = currentCmd();
  // Клавиши не нажаты → панда стоит на месте (баланс), а не идёт сама.
  p.setPolicyCmd(cmd);
}

function initDriving() {
  const zone = $("sim");
  zone.addEventListener("pointerdown", (e) => {
    if (e.button === 0) { enableDriving(); }
  });
  document.addEventListener("keydown", (e) => {
    if (!driving) { return; }
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) { return; }
    if (e.code === "Escape") { disableDriving(true); return; }
    const c = keyCmd(e.code);
    if (!c) { return; }
    e.preventDefault();
    drivingKeys.add(e.code);
    applyDriving();
  });
  document.addEventListener("keyup", (e) => {
    if (!driving) { return; }
    if (drivingKeys.delete(e.code)) { applyDriving(); }
  });
}

/* ── вопросы/развилки ↔ Blockly ──────────────────── */

let blockSyncLock = false;

function rebuildBlocks() {
  blockSyncLock = true;
  rulesToBlocks(app.workspace, app.store.rules);
  blockSyncLock = false;
  refreshPoseFields(app.workspace);
  refreshBranchFields(app.workspace);
}

function syncFromBlocks() {
  if (blockSyncLock || !app.workspace) { return; }
  const rules = blocksToRules(app.workspace);
  const saved = app.store.setRulesFromBlocks(rules);
  writeBackIds(app.workspace, saved);
}

function scheduleSync() {
  clearTimeout(scheduleSync._t);
  scheduleSync._t = setTimeout(syncFromBlocks, 400);
}

/* ── редактор поз ────────────────────────────────── */

const SAFE_PRESETS = [
  ["position_0", "стоять"],
  ["position_1", "отставить"],
  ["position_2", "равняйся"],
  ["position_give", "лапа"],
];

function openPoseDrawer() {
  const drawer = $("pose-drawer");
  drawer.classList.toggle("hidden");
  if (drawer.classList.contains("hidden")) { return; }
  app.sliders.pose.setValues(app.sim.currentNormPose());
  renderPoseChips();
}

function renderPoseChips() {
  const box = $("pose-presets");
  box.replaceChildren();
  for (const [name, label] of SAFE_PRESETS) {
    if (!app.presetPoses[name]) { continue; }
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.textContent = label;
    chip.title = `Поставить позу «${label}»`;
    chip.onclick = () => applyPose(app.presetPoses[name], name);
    box.appendChild(chip);
  }
  for (const name of app.store.poseNames()) {
    const chip = document.createElement("span");
    chip.className = "chip mine";
    const text = document.createElement("button");
    text.className = "chip-text";
    text.textContent = name;
    text.title = `Применить мою позу «${name}»`;
    text.onclick = () => applyPose(app.store.userPoses.get(name));
    const del = document.createElement("button");
    del.className = "chip-x";
    del.textContent = "✕";
    del.title = "удалить позу";
    del.onclick = () => {
      app.store.removePose(name);
      rebuildBlocks();
      renderPoseChips();
    };
    chip.append(text, del);
    box.appendChild(chip);
  }
}

function applyPose(normArr, name = null) {
  const angles = name ? resolvePoseAngles(name) : null;
  if (angles) {
    // Пресет робота: ставим ТОЧНЫЕ углы, а слайдеры — их норм-представление.
    const target = app.sim.setLiveAngles(angles);
    if (target) { app.sliders.pose.setValues(Array.from(app.sim.poseManager.ctrlToNorm(target))); }
    return;
  }
  app.sliders.pose.setValues(normArr);
  app.sim.setLivePose(normArr);
}

function saveCurrentPose() {
  const name = $("pose-name").value.trim();
  if (!name) { toast("Напиши имя позы и жми 💾", { kind: "err" }); return; }
  app.store.addPose(name, app.sliders.pose.getValues());
  $("pose-name").value = "";
  rebuildBlocks();
  renderPoseChips();
  toast(`Поза «${name}» сохранена 🐼`);
}

/* ── статус моделей ──────────────────────────────── */

function initStatus(laya) {
  const pillModel = $("pill-model");
  const pillEp = $("pill-ep");
  const setCheckEnabled = (on) => {
    const b = $("btn-check");
    if (b.disabled === !on) { return; }
    b.disabled = !on;
    b.title = on ? "Проверить фразу" : "Панда ещё не понимает слова — грузится модель ИИ 🧠";
  };
  setCheckEnabled(false);

  const render = () => {
    if (laya.state === "ready") {
      pillEp.classList.remove("hidden");
      pillEp.textContent = `⚙️ ${laya.ep || "—"}`;
      pillEp.className = "pill ok";
    } else {
      pillEp.classList.add("hidden");
    }

    pillModel.classList.remove("hidden");
    if (laya.state === "downloading") {
      pillModel.className = "pill busy";
      pillModel.textContent = `🧠 Скачиваю модель… ${Math.round(laya.progress * 100)}%`;
      $bar("bar-laya", { frac: laya.progress || 0.02 });
    } else if (laya.state === "starting") {
      pillModel.className = "pill busy";
      pillModel.textContent = "🧠 Запускаю модель на процессоре…";
      $bar("bar-laya", { frac: 1 });
    } else if (laya.state === "ready") {
      pillModel.className = "pill ok";
      pillModel.textContent = "🧠 Модель ИИ готова";
    } else {
      pillModel.className = "pill bad";
      pillModel.textContent = laya.state === "failed" ? "🧠 Модель ИИ: сбой" : "🧠 Модель ИИ не загружена";
    }
    if (laya.state !== "downloading" && laya.state !== "starting") { hideBar("bar-laya"); }
    setCheckEnabled(laya.state === "ready");
  };

  pillModel.title = laya.state === "ready" ? "Модель ИИ Панды — работает прямо в браузере" : "Нажми — проверить и загрузить модель ИИ";
  pillModel.onclick = async () => {
    if (laya.state === "ready" || laya.state === "downloading") { return; }
    let has = false;
    try {
      const st = await fetch("./api/laya/status");
      has = st.ok ? Boolean((await st.json()).available) : false;
    } catch { has = false; }
    if (!has) {
      toast("Модели ИИ нет на сервере 📦 собери её: tools/export_onnx.py → models/laya/laya_multilingual_seq512.onnx (подробности в tools/download_models.sh)", { kind: "err", timeout: 11000 });
      return;
    }
    laya.start("./");
  };
  laya.subscribe(render);
  render();
  return render;
}

function initPolicyPill() {
  let tick = null;
  const render = () => {
    const st = app.sim?.policy?.status || { state: "idle" };
    if (st.state === "downloading") {
      setPolicyPill("busy",
        `🕹️ Скачиваю ходьбу… ${Math.round((st.progress || 0) * 100)}%`,
        st.attempt > 1
          ? `Нейросеть ходьбы rds2p_policy.onnx — попытка ${st.attempt}, докачиваю с места обрыва`
          : "Нейросеть ходьбы rds2p_policy.onnx (rospkg rds_2p_inference) — качается параллельно голосу и ИИ");
    } else if (st.state === "starting") {
      setPolicyPill("busy", "🕹️ Запускаю ходьбу…", "Собираю ORT-сессию нейросети");
    } else if (st.state === "retry") {
      const sec = Math.max(0, Math.ceil(((st.retryUntil || 0) - Date.now()) / 1000));
      setPolicyPill("busy", `🕹️ Ходьба: повтор через ${sec} с…`,
        `Не получилось: ${st.error}. Докачаю сам — нажимать ничего не надо`);
    } else if (st.state === "ready") {
      setPolicyPill("ok", "🕹️ Ходьба готова", "Нейросеть ходьбы загружена — стрелки или клик по симулятору");
    } else if (st.state === "error") {
      setPolicyPill("bad", "🕹️ Ходьба: сбой", `Не загрузилась: ${st.error || "?"}. Клик — повторить`);
    } else {
      setPolicyPill("", "🕹️ Ходьба: не загружена", "Нейросеть ходьбы (rospkg rds_2p_inference). Клик — загрузить; работает по клику на симулятор и стрелкам");
    }
    const counting = st.state === "retry";
    if (counting && !tick) { tick = setInterval(render, 1000); }
    if (!counting && tick) { clearInterval(tick); tick = null; }
  };
  if (app.sim?.policy) { app.sim.policy.onStatus = render; }
  render();
  $("pill-policy").onclick = async () => {
    if (app.sim?.policy?.available) { return; }
    await ensurePolicy();
  };
}

async function startModelIfPresent(laya) {
  try {
    const status = await fetch("./api/laya/status");
    if (status.ok) {
      const st = await status.json().catch(() => null);
      if (!st?.available) { return; }
    } else if (status.status !== 404) {
      return;
    } else {
      const head = await fetch("./models/laya/manifest.json");
      if (!head.ok) { return; }
    }
    await laya.start("./");
  } catch {
    /* модели нет — статус честно покажет «Модель ИИ не загружена» */
  }
}

/* ── boot ────────────────────────────────────────── */

/** Сброс кэша моделей (голос Vosk и ИИ Laya живут в IndexedDB) + перезагрузка. */
async function resetModelCache() {
  const ok = typeof confirm !== "function"
    || confirm("Сбросить кэш моделей (голос и ИИ) и загрузить их заново?");
  if (!ok) { return; }
  try {
    if (indexedDB.databases) {
      const dbs = await indexedDB.databases();
      for (const db of dbs) { if (db.name) { indexedDB.deleteDatabase(db.name); } }
    }
    if (globalThis.caches) {
      for (const key of await caches.keys()) { await caches.delete(key); }
    }
  } catch (err) {
    console.warn("сброс кэша моделей:", err);
  }
  location.reload();
}

async function boot() {
  await loadPresetPoses();
  await app.store.init();

  app.sim = new Simulator();
  app.sim.resolvePose = resolvePose;
  app.sim.resolvePoseAngles = resolvePoseAngles;
  app.sim.resolveCommand = (id) => programForCommand(id);
  window.__panda = app;
  try {
    await app.sim.init($("sim"));
  } catch (err) {
    console.error("Симулятор не поднялся:", err);
    toast("Симулятор не удалось загрузить. Проверь сервер.", { kind: "err" });
  }

  const laya = new LayaBrowserBackend();
  app.nlu = new NluEngine({ laya });

  // Blockly
  if (window.Blockly) {
    initBlocks(window.Blockly);
    setPoseOptionsProvider(poseOptions);
    app.workspace = window.Blockly.inject("blocklyDiv", {
      toolbox: toolboxJson(),
      media: "./node_modules/blockly/media/",
      grid: { length: 24, snap: 24, line: 1, shape: "dot", colour: "#e6ddca", place: "end" },
      zoom: { startScale: 0.95, maxScale: 1.35, minScale: 0.55, controls: true },
      trashcan: true,
      move: { scrollbars: true, drag: true, wheel: true },
    });
    // перетаскивание вида средней кнопкой (клик колёсика)
    const bdiv = $("blocklyDiv");
    bdiv.addEventListener("mousedown", (ev) => {
      if (ev.button !== 1) { return; }
      ev.preventDefault();
      let lastX = ev.clientX;
      let lastY = ev.clientY;
      const mm = (e2) => {
        try { app.workspace.scroll(lastX - e2.clientX, lastY - e2.clientY); } catch { /* noop */ }
        lastX = e2.clientX; lastY = e2.clientY;
      };
      const mu = () => { window.removeEventListener("mousemove", mm); window.removeEventListener("mouseup", mu); };
      window.addEventListener("mousemove", mm);
      window.addEventListener("mouseup", mu);
    });
    app.workspace.addChangeListener(scheduleSync);
    attachTemplateExpander(app.workspace);
    rebuildBlocks();
    const blocklyDiv = $("blocklyDiv");
    new ResizeObserver(() => {
      try { window.Blockly.svgResize(app.workspace); } catch { /* noop */ }
    }).observe(blocklyDiv);
    setTimeout(() => {
      try { window.Blockly.svgResize(app.workspace); } catch { /* noop */ }
    }, 500);
  } else {
    toast("Blockly не загрузился.", { kind: "err" });
  }

  // Кнопки ручных команд
  buildCommandButtons($("command-buttons"), MANUAL_BUTTONS, runCommand);

  // Редактор поз — единственный набор слайдеров в drawer
  app.sliders.pose = buildSliderPanel($("pose-sliders"), {
    onChange: (v) => app.sim.setLivePose(v),
  });

  // Пауза / сброс
  $("btn-pause").onclick = (e) => {
    app.sim.setPaused(!app.sim.paused);
    e.currentTarget.textContent = app.sim.paused ? "\u25B6" : "\u23F8\uFE0E";
    e.currentTarget.classList.toggle("accent", app.sim.paused);
  };
  $("btn-reset").onclick = () => {
    app.sim.resetToHome();
    $("hud-status").textContent = "🏠 Панда дома";
  };

  // Проверить фразу (поле + ▶)
  const setRunMode = (stop) => {
    const b = $("btn-check");
    b.textContent = stop ? "⏹" : "▶";
    b.classList.toggle("stop", Boolean(stop));
    b.disabled = !stop && !laya.available;
    b.title = stop ? "Остановить анимацию" : (laya.available ? "Проверить фразу" : "Панда ещё не понимает слова — грузится мозг 🧠");
    updateDriveHint();
  };
  if (app.sim.player) { app.sim.player.onActive = setRunMode; }
  $("btn-check").onclick = () => {
    const p = app.sim?.player;
    if (p && p.active) {
      p.stop();
      setRunMode(false);
      $("hud-status").textContent = "🛑 Остановила";
      return;
    }
    if (busy) { return; }
    runFlow();
  };
  $("phrase-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { $("btn-check").click(); }
  });

  // Тулбар: редактор поз
  $("btn-poses").onclick = openPoseDrawer;
  $("btn-poses-close").onclick = () => $("pose-drawer").classList.add("hidden");
  $("btn-pose-save").onclick = saveCurrentPose;
  $("btn-pose-center").onclick = () => applyPose(new Array(12).fill(0.5));

  // Речь, статусы и вождение
  initSpeech();
  const renderStatus = initStatus(laya);
  renderStatus();
  initPolicyPill();
  initDriving();
  app.resetModelCache = resetModelCache;
  $("btn-models-reset")?.addEventListener("click", resetModelCache);
  // Все три модели качаются ПАРАЛЛЕЛЬНО и показывают прогресс:
  //   голос Vosk (46 МБ, IndexedDB), ИИ Laya (646 МБ, IndexedDB) и политика
  //   ходьбы (4 МБ, HTTP-кэш; Range-докачка + бесконечные ретраи — см.
  //   policyRunner.js). Голос не держим дольше 45 с, чтобы не оттягивать ИИ.
  app.sim?.policy?.load();
  const voiceDone = voskSupported() && !voskModelReady()
    ? Promise.race([warmVoice(), new Promise((r) => setTimeout(r, 45000))])
    : Promise.resolve();
  voiceDone.finally(() => startModelIfPresent(laya).catch(() => {}));
}

boot();