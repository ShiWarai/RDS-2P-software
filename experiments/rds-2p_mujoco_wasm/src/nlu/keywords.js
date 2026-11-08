/**
 * Мгновенный NLU-фолбэк до загрузки Laya (PLAN.md 4.3):
 * нормализация + совпадение с примерами фраз из правил.
 */

export function normalizeRu(text) {
  return String(text ?? "")
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/[^а-яa-z0-9\s]/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function tokenizeWords(norm) {
  return norm.split(" ").filter(Boolean);
}

function levenshteinShort(a, b, max) {
  if (Math.abs(a.length - b.length) > max) { return max + 1; }
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let rowMin = i;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      cur[j] = Math.min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
      rowMin = Math.min(rowMin, cur[j]);
    }
    if (rowMin > max) { return max + 1; }
    prev = cur;
  }
  return prev[b.length];
}

/** «лапку»≈«лапу» (опечатка/падеж), «подай»⊃«дай» — детским формулировкам быть. */
function wordMatch(word, exWord) {
  if (word === exWord) { return true; }
  if (exWord.length >= 3 && word.includes(exWord)) { return true; }
  if (word.length >= 4 && exWord.length >= 4 && word !== exWord) {
    return levenshteinShort(word, exWord, 1) <= 1;
  }
  return false;
}

/**
 * @param {string} text — услышанный текст
 * @param {Array<{id,name,examples:string[]}>} rules
 * @returns {{ruleId: string|null, confidence: number, probabilities: Object<string,number>}}
 */
export function classifyByKeywords(text, rules) {
  const norm = normalizeRu(text);
  const words = new Set(tokenizeWords(norm));
  const scores = {};

  for (const rule of rules) {
    let best = 0;
    for (const exampleRaw of rule.examples || []) {
      const example = normalizeRu(exampleRaw);
      if (!example) { continue; }
      let s = 0;
      if (norm === example) {
        s = 1;
      } else if (example.length >= 3 && norm.includes(example)) {
        s = 0.85 + 0.15 * Math.min(1, example.length / Math.max(1, norm.length));
      } else {
        const exWords = tokenizeWords(example);
        const textWords = [...words];
        const hits = exWords.filter((w) => w.length > 2 && textWords.some((t) => wordMatch(t, w))).length;
        if (exWords.length > 0 && hits > 0) {
          s = 0.6 * (hits / exWords.length);
        }
      }
      best = Math.max(best, s);
    }
    scores[rule.id] = best;
  }

  const ids = rules.map((r) => r.id);
  const max = Math.max(0, ...ids.map((id) => scores[id]));
  if (max <= 0) {
    return { ruleId: null, confidence: 0, probabilities: Object.fromEntries(ids.map((id) => [id, 0])) };
  }

  // Мягкая нормализация для «процентов»: экспоненты от скоров.
  const exps = ids.map((id) => Math.exp((scores[id] - max) * 6));
  const total = exps.reduce((a, b) => a + b, 0) || 1;
  const probabilities = {};
  ids.forEach((id, i) => { probabilities[id] = exps[i] / total; });

  const topId = ids[ids.findIndex((id) => scores[id] === max)];
  const second = Math.max(0, ...ids.filter((id) => id !== topId).map((id) => scores[id]));
  const confidence = max >= 0.5 ? Math.max(0, Math.min(1, (max - second) / Math.max(1e-6, max))) : max;

  return { ruleId: topId, confidence, probabilities };
}
