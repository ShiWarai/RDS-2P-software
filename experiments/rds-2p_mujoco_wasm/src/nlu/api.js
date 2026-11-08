/**
 * Резервный NLU через бэкенд (PLAN.md 4.3): браузер обращается только к нашему
 * tools/serve.py по POST /api/nlu; тот проксирует на внешний сервис модели
 * (system-one-npu /v1/systemone или облачный с ключом). Ключей во фронтенде нет.
 */

import { buildSystemOneRequest, pickRuleFromAnswer } from "../rules/to_laya.js";

export class NluBackend {
  /** @param {string} endpoint по умолчанию '/api/nlu' */
  constructor(endpoint = "/api/nlu") {
    this.endpoint = endpoint;
    this.available = false;
  }

  async probe() {
    try {
      const res = await fetch(`${this.endpoint}?probe=1`, { method: "GET" });
      const data = await res.json().catch(() => ({}));
      this.available = res.ok && data.enabled === true;
    } catch {
      this.available = false;
    }
    return this.available;
  }

  /** @returns {Promise<{ruleId, confidence, probabilities, ms}|null>} */
  async classify(rules, text) {
    if (!this.available) { return null; }
    const request = buildSystemOneRequest(rules, text);
    const started = performance.now();
    try {
      const res = await fetch(this.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      if (!res.ok) { return null; }
      const data = await res.json();
      const answer = data.answers?.command;
      const ruleId = pickRuleFromAnswer(answer);
      return {
        ruleId,
        confidence: answer?.confidence ?? 0,
        probabilities: answer?.probabilities ?? {},
        ms: Math.round(performance.now() - started),
      };
    } catch (err) {
      console.warn("NLU backend запрос не удался:", err);
      return null;
    }
  }
}
