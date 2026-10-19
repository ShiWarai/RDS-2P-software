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
 */

const CMD_SCALE = [0.5, 0.5, 1.0];

const ORT_URL = "/node_modules/onnxruntime-web/dist/ort.wasm.min.mjs";
const ORT_DIR = "/node_modules/onnxruntime-web/dist/";
const MODEL_URL = "/models/policy/rds2p_policy.onnx";

export class PolicyRunner {
  constructor() {
    this.worker = null;
    this.ready = false;
    this.error = null;
    this.lastAction = new Float32Array(12);
    this.onActions = null;
    this._load = null;
  }

  get available() {
    return this.ready;
  }

  load() {
    if (this._load) { return this._load; }
    this._load = new Promise((resolve) => {
      try {
        this.worker = new Worker(new URL("./policyWorker.js", import.meta.url), { type: "module" });
      } catch (err) {
        this.error = String(err?.message || err);
        resolve(false);
        return;
      }
      this.worker.onmessage = (e) => {
        const m = e.data || {};
        if (m.type === "ready") {
          this.ready = true;
          this.error = null;
          resolve(true);
        } else if (m.type === "actions") {
          this.lastAction = new Float32Array(m.act);
          if (this.onActions) { this.onActions(new Float32Array(m.cmd)); }
        } else if (m.type === "error") {
          this.error = m.message;
          this.ready = false;
          resolve(false);
        }
      };
      this.worker.onerror = (e) => {
        this.error = String(e?.message || "worker error");
        this.ready = false;
        resolve(false);
      };
      this.worker.postMessage({ type: "load", ortUrl: ORT_URL, ortDir: ORT_DIR, modelUrl: MODEL_URL });
    });
    return this._load;
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