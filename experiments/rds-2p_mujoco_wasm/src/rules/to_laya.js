/**
 * Компилятор «блоки-вопросы → запросы Laya» + разбор ответов (System One).
 *
 * Jev/Laya: state + типизированные вопросы → распределения вероятностей.
 *   choice — неупорядоченный список вариантов;
 *   noul   — Бернулли (true/false), short for Bernoulli;
 *   score  — упорядоченная шкала (level i), ответ — взвешенный балл Σ i·pᵢ.
 */

export const MAX_LAYA_OPTIONS = 64; // KMAX

/** Вопрос блока → спецификация для воркера Laya. */
export function questionSpec(q) {
  if (q.qtype === "score") {
    return {
      qtype: "score",
      instructions: q.instructions || q.name,
      criteria: (q.levels && q.levels.length) ? q.levels : ["низкая", "средняя", "высокая"],
    };
  }
  if (q.qtype === "noul") {
    return { qtype: "noul", instructions: q.instructions || q.name };
  }
  const criteria = {};
  const used = new Set();
  const opts = (q.options || []).slice(0, MAX_LAYA_OPTIONS);
  opts.forEach((o, i) => {
    // Ключ критерия — это ТЕКСТ, который модель читает как «метку» варианта.
    // Внутренние id (r_paw/o_cmd) туда попадать не должны: с ними классификатор
    // сыпется (проверено на эталоне — «дай лапу» 99% → мусор).
    const base = String(o.name || "").trim() || `Вариант ${i + 1}`;
    let label = base;
    let n = 2;
    while (used.has(label)) { label = `${base} ${n}`; n += 1; }
    used.add(label);
    const examples = (o.examples || []).join(", ");
    criteria[label] = examples;
  });
  return {
    qtype: "choice",
    instructions: q.instructions || "Какой вариант лучше подходит к фразе?",
    criteria,
  };
}

/** Ответ воркера → нормализованный результат вопроса. */
export function interpretAnswer(q, answer) {
  const probs = answer?.probabilities || {};
  const order = Array.isArray(answer?.order) ? answer.order : null;
  const rows = [];
  if (q.qtype === "choice") {
    (q.options || []).forEach((o, i) => {
      // Метки в ответе — названия вариантов (см. questionSpec), маппинг позиционный.
      const key = order ? order[i] : o.name;
      rows.push({ key: o.id, label: o.name, p: Number(probs[key] ?? 0) });
    });
  } else if (q.qtype === "noul") {
    rows.push({ key: "true", label: "да", p: Number(probs.true ?? 0) });
    rows.push({ key: "false", label: "нет", p: Number(probs.false ?? 0) });
  } else {
    const levels = q.levels || [];
    levels.forEach((text, i) => {
      rows.push({ key: `level:${i}`, label: String(text), p: Number(probs[text] ?? 0) });
    });
    const score = levels.reduce((acc, _t, i) => acc + i * Number(probs[levels[i]] ?? 0), 0);
    return { qid: q.id, qtype: q.qtype, rows, score, mode: argmaxRow(rows), confidence: answer?.confidence };
  }
  return { qid: q.id, qtype: q.qtype, rows, mode: argmaxRow(rows), confidence: answer?.confidence };
}

function argmaxRow(rows) {
  let best = rows[0] || null;
  for (const r of rows) { if (r.p > (best?.p ?? -1)) { best = r; } }
  return best;
}

/** Разобрать ref развилки: '<qid>::<sel>'. */
export function parseRef(ref) {
  const [qid, sel] = String(ref || "").split("::");
  return qid && sel ? { qid, sel } : null;
}

/** Значение «события» для условия развилки. */
export function refValue(q, res, sel) {
  if (!res) { return null; }
  if (q.qtype === "choice") {
    const row = res.rows.find((r) => r.key === sel);
    return row ? row.p : null;
  }
  if (q.qtype === "noul") {
    const row = res.rows.find((r) => r.key === sel);
    return row ? row.p : null;
  }
  if (sel === "score") { return res.score; }
  const row = res.rows.find((r) => r.key === sel);
  return row ? row.p : null;
}

/** То же, но только по результату прогона (строки уже содержат ключи). */
export function refValueForRes(res, sel) {
  if (!res) { return null; }
  if (sel === "score") { return res.score ?? null; }
  const row = res.rows.find((r) => r.key === sel);
  return row ? row.p : null;
}

/** Сравнение по оператору («=» — с допуском для float). */
export function compareOp(value, op, target) {
  switch (op) {
    case ">": return value > target;
    case "<": return value < target;
    case "≥": return value >= target;
    case "≤": return value <= target;
    case "=": return Math.abs(value - target) <= 0.02;
    default: return false;
  }
}

export function fmtP(p) {
  return `${Math.round((p ?? 0) * 100)}%`;
}

export function fmtValue(v) {
  if (v == null) { return "—"; }
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}