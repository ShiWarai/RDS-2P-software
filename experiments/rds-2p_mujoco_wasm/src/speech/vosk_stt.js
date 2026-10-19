/* Локальное распознавание русской речи в браузере — vosk-browser@0.0.8 (WASM).
   Реальный API библиотеки:
     const model = await Vosk.createModel(url)      — грузит tar.gz сам (в воркере);
     new model.KaldiRecognizer()                    — экземпляры распознавания;
     rec.acceptWaveform(audioBuffer)                — AudioBuffer целиком;
     rec.on("result"|"partialresult", ...)          — асинхронные события, stop()'а нет.
   URL подаём blob: — тогда докачку 46 МБ делаем сами с прогрессом и кэшем Cache Storage,
   а воркер читает blob мгновенно. Бандл window.Vosk подгружается из node_modules.
   Стриминг (AudioContext) — частичные результаты летят в UI живьём; если контекст не
   стартовал — запасной путь MediaRecorder → decodeAudioData → пачка. */
const MODEL_URL = "models/stt/vosk-ru-small.tar.gz";
const CACHE_NAME = "panda-vosk-v1";
const MAX_SECONDS = 8;

let modelPromise = null;
let modelReady = false;
let modelCb = null;
let voskJsPromise = null;
let warmupError = "";
let model = null;

export function voskSupported() {
  if (typeof WebAssembly === "undefined") { return false; }
  return typeof Blob !== "undefined" && URL.canParse("blob:");
}

function report(frac, label) { if (modelCb) { modelCb({ frac: Math.max(0, Math.min(1, frac)), label }); } }

/* Промис с таймаутом: Vosk.createModel может зависнуть на распаковке (квота IndexedDB),
   и без таймаута пилюля вечно висит на 92%. */
function withTimeout(promise, ms, msg) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(msg)), ms)),
  ]);
}

/* UMD-бандл vosk-browser из node_modules — единый источник (как ort-web для Laya). */
function ensureVoskGlobal() {
  if (typeof window.Vosk !== "undefined") { return Promise.resolve(window.Vosk); }
  if (!voskJsPromise) {
    const url = new URL("node_modules/vosk-browser/dist/vosk.js?v=0.0.8", document.baseURI).href;
    voskJsPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = url;
      s.onload = () => { window.Vosk ? resolve(window.Vosk) : reject(new Error("vosk.js загрузился, но window.Vosk пуст")); };
      s.onerror = () => { voskJsPromise = null; reject(new Error(`vosk библиотека не загрузилась: ${url}`)); };
      document.head.appendChild(s);
    });
  }
  return voskJsPromise;
}

async function cacheMatch(url) {
  if (!("caches" in window)) { return null; }
  try { const c = await caches.open(CACHE_NAME); return (await c.match(url)) || null; }
  catch { return null; }
}

async function storeCache(url, blob) {
  if (!("caches" in window)) { return; }
  try {
    const c = await caches.open(CACHE_NAME);
    await c.put(url, new Response(blob, { headers: { "Content-Length": String(blob.size) } }));
  } catch { /* квота — следующая загрузка просто качает заново */ }
}

async function loadModel() {
  const Vosk = await ensureVoskGlobal();
  const url = new URL(MODEL_URL, document.baseURI).href;
  const cached = await cacheMatch(url);
  let blob;
  if (cached) {
    report(0.88, "📦 берём из кэша");
    blob = await cached.blob();
  } else {
    report(0.01, "📥 качаю голос");
    const resp = await fetch(MODEL_URL);
    if (!resp.ok) { throw new Error(`модель ${MODEL_URL}: HTTP ${resp.status}`); }
    const total = Number(resp.headers.get("Content-Length")) || 0;
    if (total > 0 && resp.body && resp.body.getReader) {
      const reader = resp.body.getReader();
      const chunks = [];
      let got = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) { break; }
        chunks.push(value);
        got += value.length;
        report(0.01 + 0.86 * (got / total), "📥 качаю голос");
      }
      blob = new Blob(chunks, { type: "application/gzip" });
    } else {
      report(0.3, "📥 качаю голос");
      blob = await resp.blob();
    }
    await storeCache(url, blob);
  }
  report(0.92, "📦 распаковываю");
  const blobUrl = URL.createObjectURL(blob);
  try {
    model = await withTimeout(
      Vosk.createModel(blobUrl),
      120000,
      "распаковка голосовой модели зависла — нажми ♻️ Сбросить модели и попробуй снова",
    );
    try { model.setLogLevel(-3); } catch { /* не критично */ }
  } finally {
    setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
  }
  modelReady = true;
  report(1, "готово");
  return model;
}

function ensureModel() {
  if (!modelPromise) {
    modelPromise = loadModel();
    modelPromise.catch(() => { modelPromise = null; });
  }
  return modelPromise;
}

export function voskWarmup(onProgress) {
  modelCb = onProgress || null;
  if (!voskSupported()) { warmupError = "браузер не умеет WASM-распознавание"; return Promise.resolve(false); }
  return ensureModel()
    .then(() => { warmupError = ""; return true; })
    .catch((e) => { warmupError = String((e && e.message) || e); return false; });
}

export function voskModelReady() { return modelReady; }
export function voskWarmupError() { return warmupError; }

/* Собирает текст с распознавателя: result-события приходят асинхронно и без явного stop.
   resolve когда после последнего result пройдёт quietMs или настанет hardMs. */
function collect(rec, initial = "", quietMs = 700, hardMs = 6000) {
  return new Promise((resolve) => {
    const parts = initial ? [initial] : [];
    let quietTimer = null;
    const hardTimer = setTimeout(fin, hardMs);
    function fin() { clearTimeout(quietTimer); clearTimeout(hardTimer); resolve(parts.filter(Boolean).join(" ").trim()); }
    rec.on("result", (m) => {
      const t = m && m.result && m.result.text ? String(m.result.text).trim() : "";
      if (t && t !== parts[parts.length - 1]) { parts.push(t); }
      if (quietTimer) { clearTimeout(quietTimer); }
      quietTimer = setTimeout(fin, quietMs);
    });
  });
}

export class VoskStt {
  constructor({ onText, onPartial, onState, onError }) {
    this.onText = onText || (() => {});
    this.onPartial = onPartial || (() => {});
    this.onState = onState || (() => {});
    this.onError = onError || (() => {});
    this.state = "idle";
    this.stream = null;
    this.mode = null; // "stream" | "clip"
    // стриминг
    this.ctx = null;
    this.srcNode = null;
    this.processor = null;
    this.rec = null;
    this.parts = [];
    this.live = "";
    // клип
    this.media = null;
    this.chunks = [];
    this.autoTimer = 0;
  }

  isBusy() { return this.state !== "idle"; }

  toggle() {
    if (this.state === "listening") { this.stop(); return Promise.resolve(); }
    return this.state === "idle" ? this.start() : Promise.resolve();
  }

  setState(s) { this.state = s; this.onState(s); }

  async start() {
    if (this.state === "listening") { this.stop(); return; }
    if (this.state !== "idle") { return; }
    if (!voskSupported()) { this.onError("this browser cannot decode audio"); return; }
    if (!modelReady) {
      this.setState("loading-model");
      try { await ensureModel(); }
      catch (e) { this.setState("idle"); this.onError(`model: ${e && e.message ? e.message : e}`); return; }
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch (e) {
      this.setState("idle");
      this.onError(e && e.name === "NotAllowedError" ? "microphone blocked" : `mic: ${e && e.message ? e.message : e}`);
      return;
    }
    const startedStreaming = await this._startStreaming().catch(() => false);
    if (startedStreaming) {
      this.mode = "stream";
    } else {
      this._teardownStream();
      this.mode = this._startClipRecorder() ? "clip" : null;
      if (!this.mode) {
        this._teardownMic();
        this.setState("idle");
        this.onError("audio capture failed");
        return;
      }
    }
    this.setState("listening");
    this.autoTimer = setTimeout(() => this.stop(), MAX_SECONDS * 1000);
  }

  /* --- основной путь: живой стриминг --- */

  async _startStreaming() {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    this.ctx = new Ctor();
    if (this.ctx.state !== "running") { await this.ctx.resume().catch(() => {}); }
    await new Promise((r) => setTimeout(r, 120));
    if (this.ctx.state !== "running") { return false; }
    this.parts = [];
    this.live = "";
    this.rec = new model.KaldiRecognizer(this.ctx.sampleRate);
    this.rec.on("partialresult", (m) => {
      const p = m && m.result && m.result.partial ? String(m.result.partial).trim() : "";
      const live = [...this.parts, p].filter(Boolean).join(" ").trim();
      if (live) { this.live = live; this.onPartial(live); }
    });
    this.rec.on("result", (m) => {
      const t = m && m.result && m.result.text ? String(m.result.text).trim() : "";
      if (t) { this.parts.push(t); this.live = this.parts.join(" ").trim(); this.onPartial(this.live); }
    });
    this.srcNode = this.ctx.createMediaStreamSource(this.stream);
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    this.processor.onaudioprocess = (ev) => {
      if (!this.rec) { return; }
      try { this.rec.acceptWaveform(ev.inputBuffer); } catch { /* модель могла быть снята */ }
    };
    this.srcNode.connect(this.processor);
    this.processor.connect(this.ctx.destination);
    return true;
  }

  stop() {
    if (this.state !== "listening") { return; }
    clearTimeout(this.autoTimer);
    if (this.mode === "stream") { this._stopStreaming(); }
    else { this._stopClipRecorder(); }
  }

  _finishFinal(text) {
    this.mode = null;
    this.setState("idle");
    this.onText(String(text || "").trim());
  }

  _stopStreaming() {
    const rec = this.rec;
    const parts = this.parts;
    const live = this.live;
    this.rec = null;
    this._teardownMic();
    this._teardownStream();
    if (!rec) { this._finishFinal(live); return; }
    this.setState("decoding");
    try { rec.retrieveFinalResult(); } catch { /* воркер мог уже отдать всё */ }
    collect(rec, "", 500, 3000)
      .then((tail) => {
        const full = [parts.filter(Boolean).join(" "), tail].filter(Boolean).join(" ").trim();
        this._finishFinal(full || live);
      })
      .finally(() => { try { rec.remove(); } catch { /* уже снят */ } });
  }

  /* --- запасной путь: MediaRecorder клип --- */

  _startClipRecorder() {
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
      .find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m));
    if (!mime) { return false; }
    this.chunks = [];
    this.media = new MediaRecorder(this.stream, { mimeType: mime });
    this.media.ondataavailable = (ev) => { if (ev.data && ev.data.size > 0) { this.chunks.push(ev.data); } };
    this.media.onerror = () => { this._teardownMic(); this._teardownRecorder(); this.setState("idle"); this.onError("recorder error"); };
    this.media.onstop = () => this._recognizeClip();
    this.media.start(250);
    return true;
  }

  _stopClipRecorder() {
    try {
      if (this.media && this.media.state !== "inactive") { this.media.stop(); }
      else { this._recognizeClip(); }
    } catch {
      this._teardownRecorder();
      this._teardownMic();
      this._finishFinal("");
    }
  }

  async _recognizeClip() {
    const chunks = this.chunks;
    const type = this.media ? this.media.mimeType : "";
    this._teardownRecorder();
    this._teardownMic();
    if (!chunks.length) { this._finishFinal(""); return; }
    this.setState("decoding");
    try { this._finishFinal(await this._recognizeBlob(new Blob(chunks, { type }))); }
    catch { this._finishFinal(""); }
  }

  async _recognizeBlob(blob) {
    const m = model || await ensureModel();
    const Ctor = window.AudioContext || window.webkitAudioContext;
    const srcBuf = await new Ctor().decodeAudioData(await blob.arrayBuffer());
    const rate = 16000;
    const frames = Math.max(1, Math.ceil(srcBuf.duration * rate));
    const OfflineCtor = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const octx = new OfflineCtor(1, frames, rate);
    const node = octx.createBufferSource();
    node.buffer = srcBuf;
    node.connect(octx.destination);
    node.start(0);
    const buf = await octx.startRendering();
    const rec = new m.KaldiRecognizer(rate);
    const done = collect(rec, "", 900, 20000);
    try {
      rec.acceptWaveform(buf);
    } catch (e) { try { rec.remove(); } catch {} throw e; }
    try { rec.retrieveFinalResult(); } catch {}
    const text = await done;
    try { rec.remove(); } catch {}
    return text;
  }

  /* --- разбор общего --- */

  _teardownRecorder() { this.media = null; this.chunks = []; }

  _teardownStream() {
    if (this.processor) { try { this.processor.disconnect(); } catch {} this.processor.onaudioprocess = null; this.processor = null; }
    if (this.srcNode) { try { this.srcNode.disconnect(); } catch {} this.srcNode = null; }
    if (this.ctx) { try { this.ctx.close(); } catch {} this.ctx = null; }
    this.rec = null;
    this.parts = [];
    this.live = "";
  }

  _teardownMic() {
    if (this.stream) { for (const t of this.stream.getTracks()) { try { t.stop(); } catch {} } this.stream = null; }
  }
}

export function isSecure() {
  return location.protocol === "https:" || ["localhost", "127.0.0.1"].includes(location.hostname);
}
