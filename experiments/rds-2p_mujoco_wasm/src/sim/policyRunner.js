/**
 * Политика ходьбы RDS-2P из rospkg rds_2p_inference (models/rds2p_policy.onnx).
 * Порт src/inference_controller.cpp: obs[48] → continuous_actions[12], 50 Гц.
 *
 * obs = linvel(3, база) + gyro(3, база) + gravity(3, база) + joint_angles(12)
 *       + joint_velocities(12) + last_action(12) + cmd_vel(3)
 * cmd_vel масштабируется как у контроллера (0.5 / 0.5 / 1.0);
 * default_angles = нули (home keyframe, как в inference_node.cpp).
 * Фильтр 0.8 + клип ±1 + scale 0.18 — в policyWorker.js.
 * Инференс живёт в Web Worker, чтобы не дроссировать контур (50 Гц).
 *
 * Загрузка: модель скачивается на главном потоке докачиваемым загрузчиком
 * (Range + прогресс, см. modelDownload.js) и передаётся в воркер байтами —
 * пилюля показывает честный процент, а обрыв сети не превращается в «сбой»:
 * трансферные ошибки ретраятся бесконечно с бэкоффом и докачкой с места
 * обрыва. Терминальной считается только явная HTTP 4xx (файла нет на
 * сервере). Никакого «запасного варианта»: пока модель не докачана —
 * ходьба ждёт, а не подменяется процедурной походкой.
 */

import { downloadResumable } from "./modelDownload.js";

const CMD_SCALE = [0.5, 0.5, 1.0];

const ORT_URL = new URL("node_modules/onnxruntime-web/dist/ort.wasm.min.mjs", document.baseURI).href;
const ORT_DIR = new URL("node_modules/onnxruntime-web/dist/", document.baseURI).href;
const MODEL_URL = new URL("models/policy/rds2p_policy.onnx", document.baseURI).href;

const RETRY_MIN_MS = 1500;
const RETRY_MAX_MS = 10000;
const SESSION_ATTEMPTS = 6;
const SESSION_TIMEOUT_MS = 60000;

export class PolicyRunner {
  constructor() {
    this.worker = null;
    this.ready = false;
    this.error = null;
    this.lastAction = new Float32Array(12);
    this.onActions = null;
    this.onStatus = null;
    // state: idle | downloading | starting | retry | ready | error
    this.status = { state: "idle", progress: 0, attempt: 0, retryUntil: 0, error: null };
    this._load = null;
    this._done = false;
    this._model = null;
    this._dlState = null;
  }

  get available() {
    return this.ready;
  }

  _emit(patch) {
    this.status = { ...this.status, ...patch };
    try { this.onStatus?.(this.status); } catch { /* подписчик не должен ломать загрузку */ }
  }

  /** Идемпотентный запуск: во время попытки — ждёт её; после терминального
   *  провала — начинает новую (так «клик — повторить» реально повторяет). */
  load() {
    if (this.ready) { return Promise.resolve(true); }
    if (this._load && !this._done) { return this._load; }
    this._done = false;
    this._load = this._run().then((ok) => {
      this._done = true;
      return ok;
    });
    return this._load;
  }

  async _run() {
    try {
      const model = this._model || await this._downloadModel();
      await this._startSession(model);
    } catch (err) {
      this.error = describeError(err);
      this.ready = false;
      this._emit({ state: "error", error: this.error, retryUntil: 0 });
      return false;
    }
    this.ready = true;
    this.error = null;
    this._emit({ state: "ready", progress: 1, error: null, retryUntil: 0 });
    return true;
  }

  /** Скачивание модели: трансферные ошибки — бесконечные ретраи с докачкой,
   *  терминальные HTTP 4xx — наверх (сервер явно не отдаёт файл). */
  async _downloadModel() {
    if (this._model) { return this._model; }
    const state = this._dlState || (this._dlState = { chunks: [], got: 0, size: 0 });
    let attempt = 0;
    for (;;) {
      attempt += 1;
      this._emit({ state: "downloading", attempt, error: null, retryUntil: 0 });
      try {
        const buf = await downloadResumable(MODEL_URL, state, (frac) => {
          this._emit({ state: "downloading", progress: frac });
        });
        this._model = buf;
        this._dlState = null;
        return buf;
      } catch (err) {
        const status = err?.status;
        const permanent = status >= 400 && status < 500 && status !== 408 && status !== 429;
        this.error = describeError(err);
        if (permanent) { throw err; }
        const delay = Math.min(RETRY_MAX_MS, RETRY_MIN_MS * 2 ** Math.min(attempt - 1, 3));
        this._emit({ state: "retry", error: this.error, retryUntil: Date.now() + delay });
        await sleep(delay);
      }
    }
  }

  /** Подъём воркера + ORT-сессии по уже скачанным байтам. */
  async _startSession(model) {
    for (let attempt = 1; ; attempt += 1) {
      this._emit({ state: "starting", attempt, error: null, retryUntil: 0 });
      try {
        await this._spawnWorker(model);
        return;
      } catch (err) {
        this.error = describeError(err);
        this._terminateWorker();
        if (attempt >= SESSION_ATTEMPTS) { throw err; }
        const delay = Math.min(RETRY_MAX_MS, RETRY_MIN_MS * 2 ** Math.min(attempt - 1, 2));
        this._emit({ state: "retry", error: this.error, retryUntil: Date.now() + delay });
        await sleep(delay);
      }
    }
  }

  _spawnWorker(model) {
    return new Promise((resolve, reject) => {
      let worker;
      try {
        worker = new Worker(new URL("./policyWorker.js", import.meta.url), { type: "module" });
      } catch (err) {
        reject(err);
        return;
      }
      let timer = null;
      const fail = (message) => {
        if (timer) { clearTimeout(timer); }
        try { worker.terminate(); } catch { /* noop */ }
        reject(new Error(message));
      };
      timer = setTimeout(() => fail("таймаут инициализации (60 с)"), SESSION_TIMEOUT_MS);
      worker.onmessage = (e) => {
        const m = e.data || {};
        if (m.type === "ready") {
          clearTimeout(timer);
          this.worker = worker;
          worker.onmessage = (ev) => this._onMessage(ev);
          worker.onerror = (ev) => {
            this.error = String(ev?.message || "worker error");
            this.ready = false;
            this._emit({ state: "error", error: this.error });
          };
          resolve();
        } else if (m.type === "error") {
          fail(m.message || "ошибка воркера");
        }
      };
      worker.onerror = (e) => fail(String(e?.message || "worker error"));
      // Байты модели передаём копией (без transfer): кэш this._model нужен
      // для повторного подъёма воркера, а structured clone 4 МБ незаметен.
      worker.postMessage({ type: "load", ortUrl: ORT_URL, ortDir: ORT_DIR, model });
    });
  }

  _onMessage(e) {
    const m = e.data || {};
    if (m.type === "actions") {
      this.lastAction = new Float32Array(m.act);
      if (this.onActions) { this.onActions(new Float32Array(m.cmd)); }
      return;
    }
    if (m.type === "error") {
      // Ошибка уже поднятой сессии (инференс): честно гасим готовность —
      // следующий load() поднимет воркер заново (модель уже скачана).
      this.error = m.message || "ошибка инференса";
      this.ready = false;
      this._emit({ state: "error", error: this.error });
    }
  }

  _terminateWorker() {
    if (this.worker) {
      try { this.worker.terminate(); } catch { /* noop */ }
      this.worker = null;
    }
  }

  reset() {
    this.lastAction = new Float32Array(12);
    try { this.worker?.postMessage({ type: "reset" }); } catch { /* noop */ }
  }

  /** Отправить наблюдение (без ожидания ответа — самый свежий применится сам). */
  send(obs) {
    if (!this.ready) { return false; }
    try {
      const buf = obs.buffer ?? obs;
      this.worker.postMessage({ type: "act", obs: buf }, [buf]);
      return true;
    } catch {
      return false;
    }
  }
}

function describeError(err) {
  if (err instanceof Error) { return err.message; }
  return String(err ?? "неизвестно");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Пакет наблюдений из данных MuJoCo (порт observation-части inference_controller). */
export function buildObs(data, cmdVel, lastAction) {
  const qpos = data.qpos;
  const qvel = data.qvel;
  const qw = qpos[3];
  const qx = qpos[4];
  const qy = qpos[5];
  const qz = qpos[6];

  // R (база ← мир) и её транспонирование для перевода в систему базы.
  const R = quatToMat(qw, qx, qy, qz);
  const Rt = transpose(R);

  const linvel = mulv(Rt, [qvel[0], qvel[1], qvel[2]]);
  // В MuJoCo угловая скорость free joint (qvel[3:6]) уже в системе координат
  // тела (IMU-система) — поворачивать нельзя, это ломает реакцию вперёд/назад.
  const gyro = [qvel[3], qvel[4], qvel[5]];
  const gravity = mulv(Rt, [0, 0, -1]);

  const obs = new Float32Array(48);
  let k = 0;
  for (let i = 0; i < 3; i++) { obs[k++] = linvel[i]; }
  for (let i = 0; i < 3; i++) { obs[k++] = gyro[i]; }
  for (let i = 0; i < 3; i++) { obs[k++] = gravity[i]; }
  // 12 суставов: qpos[7..18], qvel[6..17], порядок fl, fr, bl, br — как у приводов.
  for (let i = 0; i < 12; i++) { obs[k++] = qpos[7 + i]; }
  for (let i = 0; i < 12; i++) { obs[k++] = qvel[6 + i]; }
  for (let i = 0; i < 12; i++) { obs[k++] = lastAction[i]; }
  obs[k++] = cmdVel[0] * CMD_SCALE[0];
  obs[k++] = cmdVel[1] * CMD_SCALE[1];
  obs[k++] = cmdVel[2] * CMD_SCALE[2];
  return obs;
}

function quatToMat(w, x, y, z) {
  const n = Math.hypot(w, x, y, z) || 1;
  w /= n; x /= n; y /= n; z /= n;
  return [
    [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
  ];
}

function transpose(m) {
  return [
    [m[0][0], m[1][0], m[2][0]],
    [m[0][1], m[1][1], m[2][1]],
    [m[0][2], m[1][2], m[2][2]],
  ];
}

function mulv(m, v) {
  return [
    m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
    m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
    m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
  ];
}