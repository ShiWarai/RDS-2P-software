
import { preprocessRgbaBottomUp } from "./preprocess.js";
import { decodeYoloV8 } from "./postprocess.js";

const RUNTIME_FILES = {
  webgpu: "ort.webgpu.bundle.min.mjs",
  webgl: "ort.webgl.min.mjs",
  wasm: "ort.wasm.bundle.min.mjs",
};

let session = null;
let ort = null;
let selectedBackend = null;
let inputName = null;
let outputName = null;

let latestFrame = null;
let processing = false;
let disposed = false;

function sendStatus(message, extra = {}) {
  self.postMessage({
    type: "status",
    message,
    backend: selectedBackend,
    ...extra,
  });
}

async function loadRuntime(backend) {
  const file = RUNTIME_FILES[backend];

  if (!file) {
    throw new Error(`Неизвестный backend: ${backend}`);
  }

  const runtimeUrl = new URL(
    `../../node_modules/onnxruntime-web/dist/${file}`,
    import.meta.url
  );

  const runtime = await import(runtimeUrl.href);

  // Отдельные runtime-файлы WASM/JSEP из того же npm-пакета.
  runtime.env.wasm.wasmPaths = new URL(
    "../../node_modules/onnxruntime-web/dist/",
    import.meta.url
  ).href;

  runtime.env.wasm.numThreads =
    self.crossOriginIsolated && backend === "wasm"
      ? Math.max(1, Math.min(4, self.navigator.hardwareConcurrency || 1))
      : 1;

  return runtime;
}

async function initialize(message) {
  if (session) {
    return;
  }

  const requested = message.backend;
  const candidates =
    requested === "auto"
      ? ["webgpu", "webgl", "wasm"]
      : [requested];

  let lastError = null;

  for (const backend of candidates) {
    try {
      sendStatus(`Пробую backend ${backend}…`, {
        state: "loading-backend",
      });

      if (backend === "webgpu" && !self.navigator.gpu) {
        throw new Error("WebGPU недоступен в Worker");
      }

      ort = await loadRuntime(backend);

      const modelUrl = message.modelUrl;

      sendStatus("Загружаю YOLO ONNX…", {
        state: "loading-model",
      });

      session = await ort.InferenceSession.create(modelUrl, {
        executionProviders: [backend],
        graphOptimizationLevel: "all",
        enableMemPattern: true,
      });

      inputName = session.inputNames[0];
      outputName = session.outputNames[0];
      selectedBackend = backend;

      if (!inputName || !outputName) {
        throw new Error("ONNX-модель не содержит ожидаемых входов/выходов");
      }

      sendStatus(`YOLO готова (${backend})`, {
        state: "ready",
        inputName,
        outputName,
      });

      void drainFrames();
      return;
    } catch (error) {
      lastError = error;

      try {
        await session?.release?.();
      } catch {
        // Освобождение не должно ломать fallback.
      }

      session = null;
      ort = null;

      self.postMessage({
        type: "backend-failed",
        backend,
        error: String(error?.message || error),
      });
    }
  }

  throw new Error(
    `Не удалось запустить ONNX Runtime. Последняя ошибка: ` +
    String(lastError?.message || lastError || "неизвестная ошибка")
  );
}

async function processFrame(frame) {
  const t0 = performance.now();

  const rgba = new Uint8Array(frame.buffer);

  const tPreStart = performance.now();
  const prepared = preprocessRgbaBottomUp(
    rgba,
    frame.width,
    frame.height,
    640
  );
  const preprocessMs = performance.now() - tPreStart;

  const tensor = new ort.Tensor(
    "float32",
    prepared.data,
    [1, 3, 640, 640]
  );

  const tInferenceStart = performance.now();
  const outputs = await session.run({
    [inputName]: tensor,
  });
  const inferenceMs = performance.now() - tInferenceStart;

  const tPostStart = performance.now();

  const output = outputs[outputName];

  if (!output?.data || !output?.dims) {
    throw new Error("YOLO вернула пустой выходной тензор");
  }

  const detections = decodeYoloV8(
    output.data,
    output.dims,
    prepared.geometry,
    {
      confidenceThreshold: 0.35,
      iouThreshold: 0.45,
      maxDetections: 50,
    }
  );

  const postprocessMs = performance.now() - tPostStart;
  const totalMs = performance.now() - t0;

  self.postMessage({
    type: "result",
    timestamp: frame.timestamp,
    backend: selectedBackend,
    detections,
    metrics: {
      preprocessMs,
      inferenceMs,
      postprocessMs,
      totalMs,
    },
  });
}

async function drainFrames() {
  if (processing || !session || disposed) {
    return;
  }

  processing = true;

  try {
    while (latestFrame && session && !disposed) {
      const frame = latestFrame;
      latestFrame = null;

      try {
        await processFrame(frame);
      } catch (error) {
        self.postMessage({
          type: "frame-error",
          error: String(error?.message || error),
        });
      }
    }
  } finally {
    processing = false;
  }
}

self.addEventListener("message", async (event) => {
  const message = event.data;

  if (!message || typeof message !== "object") {
    return;
  }

  if (message.type === "init") {
    try {
      await initialize(message);
    } catch (error) {
      self.postMessage({
        type: "fatal",
        error: String(error?.message || error),
      });
    }
    return;
  }

  if (message.type === "frame") {
    // Новый кадр вытесняет старый ожидающий кадр.
    latestFrame = message;
    void drainFrames();
    return;
  }

  if (message.type === "dispose") {
    disposed = true;
    latestFrame = null;

    try {
      await session?.release?.();
    } catch {
      // Worker всё равно завершается.
    }

    session = null;
    self.postMessage({ type: "disposed" });
    self.close();
  }
});
