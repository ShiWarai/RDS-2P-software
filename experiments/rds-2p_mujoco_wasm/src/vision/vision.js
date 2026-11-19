
import * as THREE from "three";
import { createRobotVisionCamera, CAMERA_CONFIG } from "./robot-camera.js";

// Full sensor resolution; YOLO has its own independent 320×320 input.
const WIDTH = CAMERA_CONFIG.width;
const HEIGHT = CAMERA_CONFIG.height;
const FPS_LIMIT = 15;
const FRAME_INTERVAL = 1000 / FPS_LIMIT;

const CLASS_DEFINITIONS = [
  { key: "tree", singular: "Дерево", plural: "Деревья" },
  { key: "bush", singular: "Куст", plural: "Кусты" },
  { key: "rock", singular: "Камень", plural: "Камни" },
  { key: "flower", singular: "Цветок", plural: "Цветы" },
  { key: "blue_ball", singular: "Синий шарик", plural: "Синие шарики" },
  { key: "red_ball", singular: "Красный шарик", plural: "Красные шарики" },
  { key: "green_ball", singular: "Зелёный шарик", plural: "Зелёные шарики" },
];

function getClassIndex(box) {
  const label = String(box?.label || "").trim().toLowerCase();

  return CLASS_DEFINITIONS.findIndex(
    (item) => item.key === label
  );
}

function drawDetections(ctx, detections) {
  const fontSize = ctx.canvas.width <= 320 ? 9 : 15;
  const labelHeight = fontSize + 5;
  const colors = { blue_ball: "#174bc4", red_ball: "#b62424", green_ball: "#087a34" };
  const boxes = (detections || []).filter(box => box.x2 > box.x1 && box.y2 > box.y1);
  ctx.lineWidth = 1;
  ctx.font = `bold ${fontSize}px Arial`;
  for (const box of boxes) {
    ctx.strokeStyle = colors[box.label] || "#00ff80";
    ctx.strokeRect(box.x1, box.y1, box.x2-box.x1, box.y2-box.y1);
  }
  const placed = [];
  // Keep target labels readable before laying out the surrounding scenery labels.
  const ordered = [...boxes].sort((a,b) => Number(b.label.endsWith("_ball"))-Number(a.label.endsWith("_ball")) || b.confidence-a.confidence);
  for (const box of ordered) {
    const index = getClassIndex(box);
    const name = index >= 0 ? CLASS_DEFINITIONS[index].singular : "Объект";
    const label = `${name} ${(box.confidence*100).toFixed(0)}%`;
    const width = Math.min(ctx.canvas.width,ctx.measureText(label).width+6);
    const x = Math.max(0,Math.min(ctx.canvas.width-width,box.x1));
    const positions = [box.y1-labelHeight-2,box.y2+2,box.y1+2];
    const y = positions.map(value=>Math.max(0,Math.min(ctx.canvas.height-labelHeight,value)))
      .find(value=>!placed.some(r=>x<r.x+r.width+2 && x+width+2>r.x && value<r.y+labelHeight+2 && value+labelHeight+2>r.y));
    if (y === undefined) continue;
    placed.push({x,y,width});
    ctx.fillStyle = colors[box.label] || "#00ff80";
    ctx.fillRect(x,y,width,labelHeight);
    ctx.fillStyle = colors[box.label] ? "#ffffff" : "#030608";
    ctx.fillText(label,x+3,y+fontSize+1);
  }
}

export class VisionPipeline {
  constructor(sim) {
    this.sim = sim;

    this.camera = null;
    this.target = null;
    this.worker = null;

    this.running = false;
    this.paused = false;
    this.disposed = false;

    this.captureTimer = null;

    this.backendRequested = this.getRequestedBackend();
    this.backend = "initializing";

    this.rawPixels = new Uint8Array(WIDTH * HEIGHT * 4);
    this.displayPixels = null;

    this.latestDetections = [];
    this.ready = false;
    this.modelError = null;
    this.readyWaiters = new Set();

    this.lastError = null;
    this.errors = [];

    this.metrics = {
      captureFps: 0,
      inferenceFps: 0,
      captureMs: 0,
      preprocessMs: 0,
      inferenceMs: 0,
      postprocessMs: 0,
      totalMs: 0,
      detections: 0,
    };

    this.captureFrames = 0;
    this.inferenceFrames = 0;
    this.lastFpsUpdate = performance.now();
    this.lastCaptureTime = 0;
  }

  getRequestedBackend() {
    const value = new URLSearchParams(location.search).get("backend");

    return ["webgpu", "webgl", "wasm"].includes(value)
      ? value
      : "auto";
  }

  async init() {
    if (!this.sim?.renderer || !this.sim?.scene) {
      throw new Error("Симулятор ещё не готов");
    }

    this.camera = createRobotVisionCamera(this.sim);

    this.target = new THREE.WebGLRenderTarget(WIDTH, HEIGHT, {
      format: THREE.RGBAFormat,
      type: THREE.UnsignedByteType,
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      depthBuffer: true,
      stencilBuffer: false,
      samples: 0,
    });

    this.createUI();
    this.createWorker();

    this.running = true;
    this.scheduleCapture();

    return this;
  }

  createWorker() {
    this.worker = new Worker(
      new URL("./vision.worker.js", import.meta.url),
      { type: "module" }
    );

    this.worker.onmessage = (event) => this.handleWorkerMessage(event.data);

    this.worker.onerror = (event) => {
      this.recordError(event.message || "Ошибка Web Worker");
    };

    const modelUrl = new URL(
      "../../models/vision/yolov8n_balls.onnx",
      import.meta.url
    ).href;

    this.worker.postMessage({
      type: "init",
      backend: this.backendRequested,
      modelUrl,
    });
  }

  createUI() {
    const root = document.createElement("div");
    root.id = "vision-controls";
    root.className = "vision-controls";

    root.innerHTML = `
      <div class="vision-panel-heading">
        <div class="vision-heading-main">
          <span class="vision-title">ЗРЕНИЕ РОБОТА</span>
          <span class="vision-subtitle">YOLOv8n · 7 классов · RGB ${WIDTH}×${HEIGHT} · вход модели 320×320</span>
        </div>

        <div
          id="vision-status"
          class="vision-status"
          role="status"
          aria-live="polite"
        >
          Инициализация камеры...
        </div>
      </div>

      <div class="vision-panel-body">
        <section
          id="vision-fallback"
          class="vision-fallback"
          aria-label="Изображение с камеры робота"
        >
          <div class="vision-fallback-head">
            <span>RGB · ${WIDTH}×${HEIGHT}</span>
            <span id="vision-preview-count">Объектов: 0</span>
          </div>

          <div class="vision-preview-viewport">
            <canvas
              id="vision-preview"
              width="${WIDTH}"
              height="${HEIGHT}"
            ></canvas>
          </div>
        </section>

        <aside class="vision-stats">
          <h3>Распознавание в реальном времени</h3>
          <div id="vision-hud" class="vision-hud">
            Ожидание первых кадров...
          </div>
        </aside>
      </div>
    `;

    const mount = document.querySelector("#vision-mount");
    if (!mount) {
      throw new Error("Не найден контейнер вкладки «Компьютерное зрение»");
    }

    mount.appendChild(root);

    this.ui = root;
    this.statusNode = root.querySelector("#vision-status");
    this.hudNode = root.querySelector("#vision-hud");

    this.previewCanvas = root.querySelector("#vision-preview");
    this.previewContext = this.previewCanvas.getContext("2d");

    this.fallbackNode = root.querySelector("#vision-fallback");
    this.previewCountNode = root.querySelector("#vision-preview-count");
  }  setStatus(message) {
    if (this.statusNode) {
      this.statusNode.textContent = message;
    }
  }

  recordError(message) {
    const error = String(message || "Неизвестная ошибка");

    this.lastError = error;
    this.errors.push({
      time: new Date().toISOString(),
      message: error,
    });

    if (this.errors.length > 10) {
      this.errors.shift();
    }

    this.setStatus(`Ошибка: ${error}`);
    this.updateHud();
  }

  handleWorkerMessage(message) {
    switch (message.type) {
      case "status":
        if (message.state === "ready") {
          this.ready = true;
          for (const waiter of this.readyWaiters) waiter.resolve();
          this.readyWaiters.clear();
        }
        if (message.backend && message.backend !== "initializing") {
          this.backend = message.backend;
        }

        this.setStatus(message.message || "Работа модели");
        this.updateHud();
        break;

      case "backend-failed":
        this.errors.push({
          time: new Date().toISOString(),
          backend: message.backend,
          message: message.error,
        });

        this.setStatus(
          `${message.backend}: ошибка запуска, пробую резервный backend`
        );
        break;

      case "result":
        this.backend = message.backend;
        this.latestDetections = message.detections || [];
        this.sim.ballFollower?.receiveDetections(this.latestDetections, WIDTH, HEIGHT, message.timestamp);

        this.metrics.preprocessMs = message.metrics.preprocessMs;
        this.metrics.inferenceMs = message.metrics.inferenceMs;
        this.metrics.postprocessMs = message.metrics.postprocessMs;
        this.metrics.totalMs = message.metrics.totalMs;
        this.metrics.detections = this.latestDetections.length;

        this.inferenceFrames++;
        this.updateHud();
        if (this.displayPixels) {
          this.drawLocalPreview();
        }
        break;

      case "frame-error":
        this.sim.ballFollower?.receiveDetections([], WIDTH, HEIGHT, performance.now());
        this.recordError(message.error);
        break;

      case "fatal":
        this.modelError = new Error(message.error);
        for (const waiter of this.readyWaiters) waiter.reject(this.modelError);
        this.readyWaiters.clear();
        this.sim.ballFollower?.receiveDetections([], WIDTH, HEIGHT, performance.now());
        this.recordError(message.error);
        break;

      default:
        break;
    }
  }

  scheduleCapture() {
    if (!this.running || this.disposed || this.paused) return;

    this.captureTimer = setTimeout(() => {
      this.captureTimer = null;
      void this.captureFrame();
    }, FRAME_INTERVAL);
  }

  /** Ставит захват кадров на паузу (вкладка ЗРения скрыта). */
  pause() {
    if (!this.sim.ballFollower?.remote && (this.sim.ballFollower?.active || this.sim.ballFollower?.starting)) return;
    if (!this.running || this.disposed || this.paused) return;
    this.paused = true;
    if (this.captureTimer) {
      clearTimeout(this.captureTimer);
      this.captureTimer = null;
    }
  }

  /** Возобновляет захват кадров (вкладка ЗРения снова видна). */
  resume() {
    if (!this.running || this.disposed || !this.paused) return;
    this.paused = false;
    this.scheduleCapture();
  }

  waitUntilReady() {
    if (this.ready) return Promise.resolve();
    if (this.modelError) return Promise.reject(this.modelError);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.readyWaiters.delete(waiter);
        reject(new Error("YOLO не запустилась за 60 секунд"));
      }, 60000);
      const waiter = {
        resolve: () => { clearTimeout(timer); resolve(); },
        reject: error => { clearTimeout(timer); reject(error); },
      };
      this.readyWaiters.add(waiter);
    });
  }

  async captureFrame() {
    if (!this.running || this.disposed || this.paused) return;

    const started = performance.now();

    try {
      const renderer = this.sim.renderer;

      if (!this.camera || !this.target || !this.sim.model) {
        this.scheduleCapture();
        return;
      }

      const previousTarget = renderer.getRenderTarget();
      const previousShadowUpdate = renderer.shadowMap.autoUpdate;
      const previousColorSpace = renderer.outputColorSpace;
      const previousToneMapping = renderer.toneMapping;

      try {
        renderer.shadowMap.autoUpdate = false;
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.NoToneMapping;

        renderer.setRenderTarget(this.target);
        renderer.clear(true, true, true);
        renderer.render(this.sim.scene, this.camera);

        renderer.readRenderTargetPixels(
          this.target,
          0,
          0,
          WIDTH,
          HEIGHT,
          this.rawPixels
        );
      } finally {
        renderer.setRenderTarget(previousTarget);
        renderer.shadowMap.autoUpdate = previousShadowUpdate;
        renderer.outputColorSpace = previousColorSpace;
        renderer.toneMapping = previousToneMapping;
      }

      this.metrics.captureMs = performance.now() - started;

      const workerPixels = this.rawPixels.slice();

      this.worker?.postMessage(
        {
          type: "frame",
          width: WIDTH,
          height: HEIGHT,
          timestamp: performance.now(),
          buffer: workerPixels.buffer,
        },
        [workerPixels.buffer]
      );


      // Данные для окна просмотра: обычный порядок строк сверху вниз.
      const displayPixels = new Uint8ClampedArray(this.rawPixels.length);

      for (let y = 0; y < HEIGHT; y++) {
        const sourceStart = (HEIGHT - 1 - y) * WIDTH * 4;
        const targetStart = y * WIDTH * 4;

        displayPixels.set(
          this.rawPixels.subarray(
            sourceStart,
            sourceStart + WIDTH * 4
          ),
          targetStart
        );
      }

      this.displayPixels = displayPixels;
      // Основное окно симулятора.
      this.drawLocalPreview();

      this.captureFrames++;
      this.updateFps();
      this.updateHud();
    } catch (error) {
      this.recordError(error?.message || error);
    } finally {
      this.scheduleCapture();
    }
  }

  drawLocalPreview() {
    if (!this.displayPixels || !this.previewContext) return;

    const image = new ImageData(
      new Uint8ClampedArray(this.displayPixels),
      WIDTH,
      HEIGHT
    );

    this.previewContext.putImageData(image, 0, 0);

    // Рисуем рамки последних результатов YOLO.
    drawDetections(
      this.previewContext,
      this.latestDetections
    );

    // Обновляем количество обнаруженных объектов.
    if (this.previewCountNode) {
      this.previewCountNode.textContent =
        `Объектов: ${this.latestDetections.length}`;
    }
  }

  updateFps() {
    const now = performance.now();
    const elapsed = now - this.lastFpsUpdate;

    if (elapsed < 1000) return;

    this.metrics.captureFps = this.captureFrames * 1000 / elapsed;
    this.metrics.inferenceFps = this.inferenceFrames * 1000 / elapsed;

    this.captureFrames = 0;
    this.inferenceFrames = 0;
    this.lastFpsUpdate = now;
  }

  updateHud() {
    if (!this.hudNode) return;

    const m = this.metrics;
    const counts = CLASS_DEFINITIONS.map(() => 0);

    for (const box of this.latestDetections || []) {
      const index = getClassIndex(box);

      if (index >= 0) {
        counts[index]++;
      }
    }

    const backendNames = {
      webgpu: "WebGPU",
      webgl: "WebGL",
      wasm: "WASM",
      initializing: "Инициализация",
    };

    const backendName =
      backendNames[this.backend] || String(this.backend);

    const lines = [
      `Вычисления: ${backendName}`,
      `Частота камеры: ${m.captureFps.toFixed(1)} кадр/с`,
      `Частота распознавания: ${m.inferenceFps.toFixed(1)} кадр/с`,
      `Всего обнаружено: ${m.detections}`,
      "",
      ...CLASS_DEFINITIONS.map((item, index) => `${item.plural}: ${counts[index]}`),
    ];

    if (new URLSearchParams(location.search).get("debug") === "1") {
      lines.push(
        "",
        `Захват кадра: ${m.captureMs.toFixed(1)} мс`,
        `Подготовка изображения: ${m.preprocessMs.toFixed(1)} мс`,
        `Распознавание модели: ${m.inferenceMs.toFixed(1)} мс`,
        `Постобработка: ${m.postprocessMs.toFixed(1)} мс`,
        `Полный цикл: ${m.totalMs.toFixed(1)} мс`
      );

      if (this.lastError) {
        lines.push(`Последняя ошибка: ${this.lastError}`);
      }
    }

    this.hudNode.textContent = lines.join("\n");
  }  async getDiagnostics() {
    let adapterInfo = null;

    try {
      if (navigator.gpu) {
        const adapter = await navigator.gpu.requestAdapter();

        if (adapter?.info) {
          adapterInfo = {
            vendor: adapter.info.vendor || "",
            architecture: adapter.info.architecture || "",
            device: adapter.info.device || "",
            description: adapter.info.description || "",
          };
        }
      }
    } catch (error) {
      adapterInfo = {
        error: String(error?.message || error),
      };
    }

    return {
      timestamp: new Date().toISOString(),
      page: location.href,
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      language: navigator.language,
      hardwareConcurrency: navigator.hardwareConcurrency,
      deviceMemory: navigator.deviceMemory ?? null,
      crossOriginIsolated: self.crossOriginIsolated,
      sharedArrayBuffer: typeof SharedArrayBuffer !== "undefined",
      webgpuAvailable: Boolean(navigator.gpu),
      webgpuAdapter: adapterInfo,
      requestedBackend: this.backendRequested,
      actualBackend: this.backend,
      model: "models/vision/yolov8n_balls.onnx",
      resolution: `${WIDTH}x${HEIGHT}`,
      metrics: { ...this.metrics },
      detections: this.latestDetections,
      lastError: this.lastError,
      recentErrors: [...this.errors],
    };
  }

  async copyDiagnostics() {
    const diagnostics = await this.getDiagnostics();
    const json = JSON.stringify(diagnostics, null, 2);

    try {
      await navigator.clipboard.writeText(json);
      this.setStatus("Диагностика скопирована в буфер обмена.");
    } catch (error) {
      console.error("Не удалось скопировать диагностику:", error);
      this.setStatus(
        "Буфер обмена недоступен. JSON диагностики выведен в Console."
      );
      console.log("VISION DIAGNOSTICS:", json);
    }
  }

  async dispose() {
    if (this.disposed) return;

    this.disposed = true;
    for (const waiter of this.readyWaiters) waiter.reject(new Error("Камера закрыта"));
    this.readyWaiters.clear();
    this.running = false;

    if (this.captureTimer) {
      clearTimeout(this.captureTimer);
      this.captureTimer = null;
    }

    this.worker?.postMessage({ type: "dispose" });
    this.worker?.terminate();
    this.worker = null;

    if (this.target) {
      this.target.dispose();
      this.target = null;
    }

    if (this.camera?.parent) {
      this.camera.parent.remove(this.camera);
    }

    this.ui?.remove();
  }
}
