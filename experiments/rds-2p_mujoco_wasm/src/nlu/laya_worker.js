/**
 * Web Worker: сессия ONNX Runtime Web (WebGPU → WASM) + токенизатор mmBERT.
 * Основной поток не блокируется. Импорты — только относительные модули src/
 * и динамические URL, переданные главным потоком (import maps в воркерах не действуют).
 */

import {
  QTYPES,
  LimitError,
  buildSequence,
  choiceConfidence,
  normalizeChoiceQuestion,
  renderOptions,
  padBuffers,
  softmax,
} from "./laya_encode.js";

let ort = null;
let initUrls = null;
let session = null;
let tokenizer = null;
let temperatures = [1.0, 1.0, 1.0];
let inputsInt32 = true;
let activeEp = "—";

function post(msg) {
  self.postMessage(msg);
}

async function initRuntime(data) {
  initUrls = data;
  ort = await import(data.ortUrl);
  // warning'и вида «nodes not assigned to preferred EP» — норма для fp16 на WebGPU,
  // не мешают; в консоль пусть попадает только реальная ошибка.
  ort.env.logLevel = "error";
  ort.env.wasm.wasmPaths = data.ortWasmPath;
  ort.env.wasm.numThreads = data.crossOriginIsolated
    ? Math.min(4, navigator.hardwareConcurrency || 1)
    : 1;
  post({ type: "runtime", state: "ok" });
}

async function loadModel(data) {
  const attempts = navigator.gpu ? [["webgpu", "wasm"], ["wasm"]] : [["wasm"]];
  let lastError = null;
  for (let a = 0; a < attempts.length; a++) {
    const providers = attempts[a];
    try {
      session = await ort.InferenceSession.create(data.modelBytes, {
        executionProviders: providers,
        graphOptimizationLevel: "basic",
      });
      activeEp = providers.join(",");
      inputsInt32 = data.inputs !== "int64";
      post({ type: "model", state: "ready", ep: activeEp });
      return;
    } catch (err) {
      lastError = err;
      if (a === attempts.length - 1) {
        post({ type: "model", state: "error", error: String(err?.message || err) });
        throw err;
      }
    }
  }
}

function makeTokInterface() {
  return {
    mask_token: "<mask>",
    mask_token_id: 4,
    cls_token_id: 2,
    sep_token_id: 1,
    encode(text) {
      const enc = tokenizer.encode(String(text), { add_special_tokens: false });
      return { ids: enc.ids };
    },
  };
}

async function loadTokenizer(data) {
  const mod = await import(data.tokenizersUrl || initUrls?.tokenizersUrl);
  const Tokenizer = mod.Tokenizer || mod.default?.Tokenizer;
  tokenizer = new Tokenizer(data.tokenizerJson, data.configJson || {});
  if (data.temperature) { temperatures = data.temperature; }
  post({ type: "tokenizer", state: "ready" });
}

function asInt64(int32Arr) {
  const out = new BigInt64Array(int32Arr.length);
  for (let i = 0; i < int32Arr.length; i++) { out[i] = BigInt(int32Arr[i]); }
  return out;
}

function normalizeGate(qtype, instructions, criteria) {
  if (qtype === "score") {
    const levels = (Array.isArray(criteria) ? criteria : Object.values(criteria || {})).map(String);
    const item = { id: "gate", kind: "score", instructions, labels: levels, options: levels, criteria: {} };
    item.options = renderOptions(item);
    return item;
  }
  const item = { id: "gate", kind: "noul", instructions, labels: ["false", "true"], criteria: criteria || {} };
  item.options = renderOptions(item);
  return item;
}

async function classify(msg) {
  if (!session || !tokenizer) {
    post({ type: "result", id: msg.id, error: "сессия не готова" });
    return;
  }
  const qtype = msg.qtype || "choice";
  const started = performance.now();
  try {
    const item = qtype === "choice"
      ? normalizeChoiceQuestion("command", { type: "choice", instructions: msg.instructions, criteria: msg.criteria })
      : normalizeGate(qtype, msg.instructions, msg.criteria);
    const tok = makeTokInterface();
    const [ids, markers] = buildSequence(tok, msg.state, item);
    const padded = padBuffers(ids, markers, QTYPES[qtype]);

    const makeTensor = (arr, shape) => {
      const data = inputsInt32 ? arr : asInt64(arr);
      const type = inputsInt32 ? "int32" : "int64";
      return new ort.Tensor(type, data, shape);
    };

    const makeBool = (arr, shape) => {
      const b = new Uint8Array(arr.length);
      for (let i = 0; i < arr.length; i++) { b[i] = arr[i] ? 1 : 0; }
      return new ort.Tensor("bool", b, shape);
    };

    const feeds = {
      input_ids: makeTensor(padded.inputIds, [1, 512]),
      attention_mask: makeTensor(padded.attention, [1, 512]),
      marker_pos: makeTensor(padded.markerPos, [1, 64]),
      marker_mask: makeBool(padded.markerMask, [1, 64]),
      qtype: makeTensor(Int32Array.of(QTYPES[qtype]), [1]),
    };

    const results = await session.run(feeds);
    const logits = results[msg.outputName || "logits"];
    if (!logits) {
      post({ type: "result", id: msg.id, error: "нет выхода logits" });
      return;
    }
    const all = Array.from(logits.data.slice(0, item.labels.length));
    const temp = temperatures[QTYPES[qtype]] ?? 1.0;
    const probs = softmax(all, temp);
    const rounded = {};
    item.labels.forEach((label, i) => { rounded[label] = Math.round(probs[i] * 10000) / 10000; });
    let picked = 0;
    for (let i = 1; i < probs.length; i++) { if (probs[i] > probs[picked]) { picked = i; } }
    post({
      type: "result",
      id: msg.id,
      answer: {
        type: qtype,
        choice: item.labels[picked],
        confidence: Math.round(choiceConfidence(probs) * 10000) / 10000,
        probabilities: rounded,
        order: item.labels.slice(),
      },
      tokens: ids.length,
      ms: Math.round(performance.now() - started),
    });
  } catch (err) {
    post({
      type: "result",
      id: msg.id,
      error: String(err?.message || err),
      limit: err instanceof LimitError,
    });
  }
}

self.onmessage = async (e) => {
  const msg = e.data || {};
  try {
    switch (msg.type) {
      case "init":
        await initRuntime(msg);
        break;
      case "tokenizer":
        await loadTokenizer(msg);
        break;
      case "model":
        await loadModel(msg);
        break;
      case "classify":
        await classify(msg);
        break;
      default:
        break;
    }
  } catch (err) {
    post({ type: "fatal", error: String(err?.message || err) });
  }
};
