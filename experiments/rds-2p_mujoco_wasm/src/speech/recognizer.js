/**
 * Голос: Web Speech API (ru-RU), PLAN.md 4.3.
 * Текстовое поле «проверить фразу» — всегда доступный запасной вход.
 */

const SR = typeof window !== "undefined"
  ? (window.SpeechRecognition || window.webkitSpeechRecognition)
  : null;

export const speechSupported = !!SR;

export class SpeechListener {
  /**
   * @param {object} handlers {onText(finalText), onInterim(text), onError(code), onState(state)}
   * @param {string} lang
   */
  constructor(handlers, lang = "ru-RU") {
    this.handlers = handlers;
    this.lang = lang;
    this.recognition = null;
    this.listening = false;
    this.wantListening = false;
  }

  ensure() {
    if (!speechSupported) { return null; }
    if (this.recognition) { return this.recognition; }
    const rec = new SR();
    rec.lang = this.lang;
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onstart = () => { this.listening = true; this.handlers.onState?.("listening"); };
    rec.onerror = (e) => {
      this.handlers.onError?.(e.error || "unknown");
    };
    rec.onresult = (e) => {
      let interim = "";
      let final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) { final += r[0].transcript; }
        else { interim += r[0].transcript; }
      }
      if (interim) { this.handlers.onInterim?.(interim.trim()); }
      if (final) { this.handlers.onText?.(final.trim()); }
    };
    rec.onend = () => {
      this.listening = false;
      this.handlers.onState?.("idle");
      if (this.wantListening) {
        // Chrome сам закрывает распознавание после паузы — перезапускаемся,
        // пока ребёнок не выключил микрофон.
        try { rec.start(); } catch { this.wantListening = false; this.handlers.onState?.("idle"); }
      }
    };
    this.recognition = rec;
    return rec;
  }

  toggle() {
    if (this.listening || this.wantListening) {
      this.stop();
      return false;
    }
    this.start();
    return true;
  }

  start() {
    const rec = this.ensure();
    if (!rec) {
      this.handlers.onError?.("unsupported");
      return;
    }
    this.wantListening = true;
    try {
      rec.start();
    } catch {
      // уже запущено
    }
  }

  stop() {
    this.wantListening = false;
    try { this.recognition?.stop(); } catch { /* noop */ }
    this.listening = false;
  }
}
