/**
 * Порт app/laya_encode.py из ShiWarai/system-one-rknn (laya==0.3.20, multilingual).
 *
 * Спецтокены mmBERT: CLS=2, SEP=1, PAD=0, MASK=4.
 * Блоки последовательности: head (тип вопроса + instructions) → опции с маркерами
 * → state (текст ребёнка) → SEP. MAX_LEN=512, HEAD_MAX_LEN=256, KMAX=64.
 *
 * Токенизатор: mmBERT tokenizer.json через @huggingface/tokenizers;
 * encode вызывается без special tokens — они добавляются вручную.
 */

export const MAX_LEN = 512;
export const HEAD_MAX_LEN = 256;
export const KMAX = 64;
export const QTYPES = { choice: 0, score: 1, noul: 2 };
export const CLS = 2;
export const SEP = 1;
export const PAD = 0;
export const MASK = 4;

const NOUL_FALSE = "no, the statement does not hold";
const NOUL_TRUE = "yes, the statement holds";

export class LimitError extends Error {}

function renderCriterion(value) {
  if (value == null) { return ""; }
  if (typeof value === "string") { return value; }
  return JSON.stringify(value);
}

export function renderOptions(item) {
  const kind = item.kind;
  if (kind === "choice") {
    return [...item.options];
  }
  if (kind === "score") {
    return item.options.map((text, i) => `level ${i}: ${renderCriterion(text)}`);
  }
  const criteria = item.criteria || {};
  const falseCrit = criteria.false;
  const trueCrit = criteria.true;
  const falseText = falseCrit != null && falseCrit !== "" ? renderCriterion(falseCrit) : NOUL_FALSE;
  const trueText = trueCrit != null && trueCrit !== "" ? renderCriterion(trueCrit) : NOUL_TRUE;
  return [`false: ${falseText}`, `true: ${trueText}`];
}

function stripMask(tok, text) {
  return String(text).split(tok.mask_token).join(" ");
}

/**
 * @param {object} tok — интерфейс { encode(text)->{ids}, mask_token, mask_token_id, cls_token_id, sep_token_id }
 * @param {string} state — текст ребёнка
 * @param {object} item — нормализованный вопрос {kind, instructions, options, labels, criteria}
 * @returns {[number[], number[]]} ids, markers
 */
export function buildSequence(tok, state, item) {
  const opts = renderOptions(item);
  if (opts.length > KMAX) {
    throw new LimitError(`Laya принимает не больше ${KMAX} вариантов`);
  }
  const ins = stripMask(tok, String(item.instructions ?? ""));
  const headIds = tok.encode(`${item.kind} question: ${ins}`).ids;

  const optIds = [];
  for (const opt of opts) {
    const optTokens = tok.encode(" " + stripMask(tok, opt)).ids.slice(0, 48);
    optIds.push([tok.mask_token_id, ...optTokens]);
  }

  let optBudget = HEAD_MAX_LEN - optIds.reduce((acc, o) => acc + o.length, 0);
  if (optBudget < 16) {
    const per = Math.max(4, Math.floor((HEAD_MAX_LEN - 16) / Math.max(1, optIds.length)));
    for (let i = 0; i < optIds.length; i++) { optIds[i] = optIds[i].slice(0, per); }
    optBudget = HEAD_MAX_LEN - optIds.reduce((acc, o) => acc + o.length, 0);
  }
  const headTrimmed = headIds.slice(0, Math.max(8, optBudget));

  const ids = [tok.cls_token_id, ...headTrimmed, tok.sep_token_id];
  const markers = [];
  for (const opt of optIds) {
    markers.push(ids.length);
    ids.push(...opt);
  }
  ids.push(tok.sep_token_id);

  const room = MAX_LEN - ids.length - 1;
  if (room < 0) {
    throw new LimitError("Вопрос Laya не помещается в 512 токенов");
  }
  const stateIds = tok.encode(stripMask(tok, serializeState(state))).ids;
  if (stateIds.length > room) {
    throw new LimitError(`Текст не помещается в оставшиеся ${room} токенов`);
  }
  ids.push(...stateIds, tok.sep_token_id);

  if (ids.length > MAX_LEN || markers.length !== opts.length) {
    throw new LimitError("Последовательность Laya не помещается в граф");
  }
  return [ids, markers];
}

function serializeState(state) {
  return typeof state === "string" ? state : JSON.stringify(state);
}

/**
 * Пакирование в плоские Int32-массивы (ONNX-входы int32, см. tools/export_onnx.py):
 * input_ids[512], attention_mask[512], marker_pos[64], marker_mask[64], qtype[1].
 */
export function padBuffers(ids, markers, qtype) {
  const inputIds = new Int32Array(MAX_LEN).fill(PAD);
  const attention = new Int32Array(MAX_LEN);
  const markerPos = new Int32Array(KMAX);
  const markerMask = new Int32Array(KMAX);
  inputIds.set(ids.slice(0, MAX_LEN));
  attention.fill(1, 0, Math.min(ids.length, MAX_LEN));
  markerPos.set(markers.slice(0, KMAX));
  markerMask.fill(1, 0, Math.min(markers.length, KMAX));
  return { inputIds, attention, markerPos, markerMask, qtype };
}

/** Нормализованный вопрос из criteria-словаря (порт normalize_question для choice). */
export function normalizeChoiceQuestion(name, raw) {
  const criteria = raw.criteria || {};
  const labels = Object.keys(criteria);
  const options = labels.map((key) => {
    const desc = criteria[key];
    if (desc == null || desc === "") { return key; }
    return typeof desc === "string" ? `${key}: ${desc}` : `${key}: ${JSON.stringify(desc)}`;
  });
  return {
    id: name,
    kind: raw.type,
    instructions: raw.instructions ?? "",
    labels,
    options,
    criteria,
  };
}

export function softmax(logits, temperature = 1.0) {
  const t = temperature && temperature > 0 ? temperature : 1.0;
  const scaled = logits.map((x) => x / t);
  const peak = Math.max(...scaled);
  const exps = scaled.map((x) => Math.exp(x - peak));
  const total = exps.reduce((a, b) => a + b, 0) || 1.0;
  return exps.map((e) => e / total);
}

/** Порт choice_confidence из app/api.py. */
export function choiceConfidence(probs) {
  const n = probs.length;
  if (n <= 1) { return 1.0; }
  const top = Math.max(...probs);
  return (top - 1.0 / n) / (1.0 - 1.0 / n);
}
