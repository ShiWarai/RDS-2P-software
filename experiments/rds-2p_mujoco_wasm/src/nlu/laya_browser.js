/**
 * Laya в браузере (PLAN.md 4.3): загрузка ONNX с прогрессом, Cache Storage,
 * сессия в Web Worker (см. laya_worker.js), статус EP.
 */

const DB_NAME = "panda-laya-files";

/* IndexedDB вместо Cache Storage: 646-МБ блобы в SW-кэсе браузер сливает молча. */
function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => { req.result.createObjectStore("files"); };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet(key) {
  try {
    const db = await idb();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("files", "readonly");
      const req = tx.objectStore("files").get(key);
      req.onsuccess = () => { resolve(req.result ?? null); };
      req.onerror = () => { reject(req.error); };
      tx.oncomplete = () => db.close();
    });
  } catch { return null; }
}

async function idbPutRaw(key, value) {
  const db = await idb();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction("files", "readwrite");
      tx.objectStore("files").put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || new Error("transaction aborted"));
    });
    return true;
  } finally {
    db.close();
  }
}

async function idbEvictOthers(keepKey) {
  const db = await idb();
  try {
    const keys = await new Promise((resolve, reject) => {
      const tx = db.transaction("files", "readonly");
      const req = tx.objectStore("files").getAllKeys();
      req.onsuccess = () => resolve(req.result.map(String));
      req.onerror = () => reject(req.error);
    });
    const stale = keys.filter((k) => k !== keepKey);
    if (!stale.length) { return; }
    await new Promise((resolve, reject) => {
      const tx = db.transaction("files", "readwrite");
      for (const k of stale) { tx.objectStore("files").delete(k); }
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

async function idbFits(bytes) {
  try {
    const est = await navigator.storage.estimate();
    if (!est.quota) { return true; }
    return est.usage + bytes < est.quota - 32 * 1048576;
  } catch { return true; }
}

async function idbPut(key, value) {
  const bytes = value?.byteLength ?? value?.size ?? 0;
  if (bytes > 4 * 1048576 && !(await idbFits(bytes))) {
    console.info(`idbPut(${key.slice(0, 40)}): место в квоте кончится — не кэшируем, перезагрузка возьмёт из HTTP-кэша (immutable)`);
    return false;
  }
  try {
    return await idbPutRaw(key, value);
  } catch (err) {
    if (err && err.name === "QuotaExceededError") {
      try {
        await idbEvictOthers(key);
        return await idbPutRaw(key, value);
      } catch { /* места нет даже после очистки — перекачаем в следующий раз */ }
    }
    console.warn(`idbPut(${key.slice(0, 40)}) не записался:`, err && (err.name || err.message || err));
    return false;
  }
}

export class LayaBrowserBackend {
  constructor() {
    this.worker = null;
    this.state = "idle"; // idle | downloading | ready | failed
    this.progress = 0;
    this.ep = "—";
    this.error = null;
    this.pending = new Map();
    this.nextId = 1;
  }

  subscribe(listener) {
    this.listeners = this.listeners || [];
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }

  emit() {
    for (const l of this.listeners || []) {
      l({ state: this.state, progress: this.progress, ep: this.ep, error: this.error });
    }
  }

  set(next) {
    Object.assign(this, next);
    this.emit();
  }

  /**
   * @param {string} rootUrl корень статки с завершающим слешем (для worker и node_modules-путей)
   */
  async start(rootUrl) {
    const baseUrl = rootUrl.endsWith("/") ? rootUrl : `${rootUrl}/`;
    // worker резолвит "./..." от своего пути (src/nlu/) — только абсолютные URL
    const absBase = new URL(baseUrl, document.baseURI).href;
    this.set({ state: "downloading", progress: 0 });
    try {
      const manifest = await this.fetchManifest(baseUrl);
      // Ключи кэша — абсолютные URL: относительные («./…») меняются от страницы к
      // странице и никогда не совпадают при перечитывании.
      const modelUrl = new URL(`models/laya/${manifest.file}`, absBase).href;
      const tokenizerUrl = new URL(`models/laya/${manifest.tokenizer ?? "tokenizer.json"}`, absBase).href;

      // Кэш читаем ДО сетки: попадание — без скачивания вообще.
      if (navigator.storage?.persist) { try { await navigator.storage.persist(); } catch { /* отказ */ } }
      await this.purgeLegacyKeys();
      const cachedModel = await idbGet(`model:${modelUrl}`);
      let modelBytes;
      if (cachedModel) {
        this.set({ progress: 0.5 });
        modelBytes = new Uint8Array(cachedModel);
        this.set({ progress: 1 });
      } else {
        const resp = await fetch(modelUrl);
        if (!resp.ok) { throw new Error(`HTTP ${resp.status} для ${modelUrl}`); }
        this.set({ progress: 0 });
        modelBytes = await this.streamWithProgress(resp, (p) => this.set({ progress: p }));
        await idbPut(`model:${modelUrl}`, modelBytes.slice(0).buffer);
      }
      const cachedTok = await idbGet(`tokenizer:${tokenizerUrl}`);
      const tokenizerJson = cachedTok
        ? JSON.parse(cachedTok)
        : await (async () => {
            const r = await fetch(tokenizerUrl);
            if (!r.ok) { throw new Error(`HTTP ${r.status} для ${tokenizerUrl}`); }
            const j = await r.json();
            await idbPut(`tokenizer:${tokenizerUrl}`, JSON.stringify(j));
            return j;
          })();
      const temperature = manifest.temperature
        ? await (await fetch(`${baseUrl}models/laya/${manifest.temperature}`)).json()
        : { temperature: [1, 1, 1] };

      const workerUrl = new URL("laya_worker.js", import.meta.url);
      this.worker = new Worker(workerUrl, { type: "module" });
      this.worker.onmessage = (e) => this.onWorkerMessage(e.data);

      await this.callWorker({
        type: "init",
        ortUrl: `${absBase}node_modules/onnxruntime-web/dist/${navigator.gpu ? "ort.webgpu.min.mjs" : "ort.wasm.min.mjs"}`,
        ortWasmPath: `${absBase}node_modules/onnxruntime-web/dist/`,
        tokenizersUrl: `${absBase}node_modules/@huggingface/tokenizers/dist/tokenizers.min.mjs`,
        crossOriginIsolated: self.crossOriginIsolated === true,
      }, "runtime");

      await this.callWorker({
        type: "tokenizer",
        tokenizerJson,
        temperature: Array.isArray(temperature.temperature) ? temperature.temperature : [1, 1, 1],
      }, "tokenizer");

      // Байты есть — дальше воркер компилирует граф на GPU/CPU. Это не «обучение».
      this.set({ state: "starting", progress: 1 });

      await this.callWorker({
        type: "model",
        modelBytes,
        inputs: manifest.inputs ?? "int32",
      }, "model", [modelBytes.buffer]);

      this.set({ state: "ready", progress: 1 });
    } catch (err) {
      console.warn("Модель ИИ не загрузилась:", err);
      this.set({ state: "failed", error: String(err?.message || err) });
    }
  }

  /** Удаляем записи со старыми относительными ключами («model:./…») — мусор от прежней схемы. */
  async purgeLegacyKeys() {
    try {
      const db = await idb();
      const keys = await new Promise((res, rej) => {
        const tx = db.transaction("files", "readonly");
        const req = tx.objectStore("files").getAllKeys();
        req.onsuccess = () => res(req.result.map(String));
        req.onerror = () => rej(req.error);
      });
      const stale = keys.filter((k) => /:\.{1,2}\//.test(k));
      if (stale.length) {
        await new Promise((res, rej) => {
          const tx = db.transaction("files", "readwrite");
          for (const k of stale) { tx.objectStore("files").delete(k); }
          tx.oncomplete = res;
          tx.onerror = () => rej(tx.error);
        });
      }
      db.close();
    } catch { /* не страшно */ }
  }

  async fetchManifest(baseUrl) {
    try {
      const res = await fetch(`${baseUrl}models/laya/manifest.json`);
      if (res.ok) { return await res.json(); }
    } catch { /* нет манифеста — стандартные имена */ }
    return { file: "laya_multilingual_seq512.onnx", inputs: "int32", tokenizer: "tokenizer.json" };
  }



  async streamWithProgress(resp, onProgress) {
    const total = Number(resp.headers.get("Content-Length") || 0);
    if (!resp.body || !total) {
      const buf = await resp.arrayBuffer();
      onProgress(1);
      return new Uint8Array(buf);
    }
    const reader = resp.body.getReader();
    const chunks = [];
    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) { break; }
      chunks.push(value);
      received += value.length;
      onProgress(Math.min(0.99, received / total));
    }
    const out = new Uint8Array(received);
    let off = 0;
    for (const c of chunks) { out.set(c, off); off += c.length; }
    onProgress(1);
    return out;
  }

  callWorker(payload, expectType, transfer = []) {
    return new Promise((resolve, reject) => {
      const id = this.nextId++;
      payload.id = id;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`worker не ответил: ${expectType}`));
      }, expectType === "model" ? 600000 : 60000);
      this.pending.set(id, { resolve, reject, timer, expectType });
      this.worker.postMessage(payload, transfer);
    });
  }

  onWorkerMessage(msg) {
    if (msg.type === "model" && msg.state === "ready") {
      this.set({ ep: msg.ep || "wasm" });
    }
    if (msg.type === "fatal") {
      this.set({ state: "failed", error: msg.error });
      return;
    }
    // Ответы runtime/tokenizer/model приходят без id — считаем их частью handshake
    // через resolve по expectType (первый незакрытый).
    if (["runtime", "tokenizer", "model"].includes(msg.type)) {
      for (const [id, p] of this.pending) {
        if (p.expectType === msg.type) {
          clearTimeout(p.timer);
          this.pending.delete(id);
          if (msg.state === "error") { p.reject(new Error(msg.error)); } else { p.resolve(msg); }
          return;
        }
      }
    }
    if (msg.type === "result") {
      const p = this.pending.get(msg.id);
      if (!p) { return; }
      clearTimeout(p.timer);
      this.pending.delete(msg.id);
      if (msg.error) { p.reject(new Error(msg.error)); } else { p.resolve(msg); }
    }
  }

  /** @returns {Promise<{answer, tokens, ms}>} */
  /** Один независимый прогон: {qtype, instructions, criteria} + текст. */
  async ask(spec, text) {
    const msg = await this.callWorker({
      type: "classify",
      state: text,
      qtype: spec.qtype || "choice",
      instructions: spec.instructions,
      criteria: spec.criteria,
    }, "result");
    return msg;
  }

  get available() {
    return this.state === "ready" && !!this.worker;
  }
}
