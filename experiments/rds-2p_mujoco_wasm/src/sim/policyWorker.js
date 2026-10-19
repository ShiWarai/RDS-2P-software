/**
 * Воркер политики ходьбы: ORT-wasm сессия rds2p_policy.onnx живёт здесь,
 * инференс не блокирует главный поток с физикой. Порт inference_controller.cpp:
 * фильтр alpha=0.8 → клип ±1 → cmd = action*0.18 (+ default=0).
 */

const ACTION_SCALE = 0.18;
const FILTER_ALPHA = 0.8;

let ort = null;
let session = null;
const lastAction = new Float32Array(12);

self.onmessage = async (e) => {
  const m = e.data;
  if (m.type === "load") {
    try {
      ort = await import(/* webpackIgnore: true */ m.ortUrl);
      ort.env.wasm.wasmPaths = m.ortDir;
      ort.env.logLevel = "error";
      session = await ort.InferenceSession.create(m.modelUrl, {
        executionProviders: ["wasm"],
        graphOptimizationLevel: "all",
      });
      self.postMessage({ type: "ready" });
    } catch (err) {
      self.postMessage({ type: "error", message: String(err?.message || err) });
    }
    return;
  }
  if (m.type === "reset") {
    lastAction.fill(0);
    return;
  }
  if (m.type === "act") {
    if (!session) { return; }
    try {
      const obs = new Float32Array(m.obs);
      const out = await session.run({ obs: new ort.Tensor("float32", obs, [1, 48]) });
      const key = out.continuous_actions ? "continuous_actions" : Object.keys(out)[0];
      const raw = out[key].data;
      const act = new Float32Array(12);
      const cmd = new Float32Array(12);
      for (let i = 0; i < 12; i++) {
        let v = FILTER_ALPHA * raw[i] + (1 - FILTER_ALPHA) * lastAction[i];
        v = Math.max(-1, Math.min(1, v));
        act[i] = v;
        lastAction[i] = v;
        cmd[i] = v * ACTION_SCALE;
      }
      self.postMessage({ type: "actions", cmd, act }, [cmd.buffer, act.buffer]);
    } catch (err) {
      self.postMessage({ type: "error", message: String(err?.message || err) });
    }
  }
};