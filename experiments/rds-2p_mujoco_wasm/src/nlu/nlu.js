/**
 * Оркестратор System One: единственный мозг Панды — Laya в браузере (ONNX).
 * Вопросы-блоки → спецификации → распределения вероятностей.
 * Никаких «поняла/не поняла»: движок отдаёт только данные.
 */

import { questionSpec, interpretAnswer } from "../rules/to_laya.js";

export class NluEngine {
  constructor({ laya = null } = {}) {
    this.laya = laya;
  }

  get mode() {
    return this.laya?.available ? "laya" : "none";
  }

  get available() {
    return Boolean(this.laya?.available);
  }

  /**
   * Задать один вопрос блока модели.
   * @returns {Promise<{qid, qtype, rows:[{key,label,p}], mode, score?, confidence?, ms}>}
   */
  async askQuestion(q, text) {
    const msg = await this.laya.ask(questionSpec(q), text);
    const res = interpretAnswer(q, msg.answer);
    res.ms = msg.ms;
    return res;
  }
}