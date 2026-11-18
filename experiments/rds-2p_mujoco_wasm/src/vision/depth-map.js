import * as THREE from "three";
import { createRobotVisionCamera } from "./robot-camera.js";
import { colorizeDepth } from "./depth-math.js";

/** Synthetic axial depth of the rendered scene. Independent of RGB/YOLO. */
export class DepthMap {
  constructor(sim, canvas, { width = 320, height = 240, hz = 12, panel = null, button = null } = {}) {
    this.sim = sim;
    this.canvas = canvas;
    this.width = width;
    this.height = height;
    this.hz = hz;
    this.panel = panel;
    this.panelPositioned = Boolean(panel?.style.left);
    this.button = button;
    this.status = panel?.querySelector("[data-depth-status]");
    this.state = "closed";
    this.contextLost = false;
    this.nextFrameAt = 0;
    this.metrics = { frameCount: 0, captureMs: 0, colorizeMs: 0, actualHz: 0 };
    this.clearColor = new THREE.Color();
    this.listeners = new AbortController();
    const signal = this.listeners.signal;
    this.dragHandle = panel?.querySelector(".depth-heading");
    this.dragHandle?.addEventListener("pointerdown", event => {
      if (!event.isPrimary || event.button !== 0 || this.panelDrag ||
          event.target.closest("button, a, input, select, textarea")) return;
      const rect = this.panel.getBoundingClientRect();
      this.panelDrag = { pointerId: event.pointerId, x: event.clientX - rect.left, y: event.clientY - rect.top };
      this.dragHandle.setPointerCapture(event.pointerId);
      this.panel.setAttribute("data-dragging", "");
      event.preventDefault();
    }, { signal });
    this.dragHandle?.addEventListener("pointermove", event => {
      if (event.pointerId !== this.panelDrag?.pointerId) return;
      this.placePanel(event.clientX - this.panelDrag.x, event.clientY - this.panelDrag.y);
    }, { signal });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
      this.dragHandle?.addEventListener(type, event => {
        if (event.pointerId === this.panelDrag?.pointerId) this.endPanelDrag();
      }, { signal });
    }
    window.addEventListener("resize", () => {
      if (this.panelPositioned && this.state !== "closed" && this.state !== "disposed") this.clampPanel();
    }, { signal });
    button?.addEventListener("click", () => this.state === "closed" ? this.open() : this.close(), { signal });
    panel?.querySelector("[data-depth-close]")?.addEventListener("click", () => this.close(), { signal });
    panel?.addEventListener("keydown", event => {
      if (event.key === "Escape") this.close(); // Bubble: Escape must still stop robot motion.
    }, { signal });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        this.startedAt = performance.now();
        this.startedCount = this.metrics.frameCount;
        this.invalidate();
      }
    }, { signal });
    sim.renderer.domElement.addEventListener("webglcontextlost", () => {
      this.contextLost = true;
      this.fail(new Error("Потерян графический контекст"));
    }, { signal });
    sim.renderer.domElement.addEventListener("webglcontextrestored", () => {
      this.contextLost = false;
      this.releaseResources();
      if (this.state !== "closed") this.setStatus("Графика восстановлена. Закрой и открой карту снова.");
    }, { signal });
  }

  setStatus(message) { if (this.status) this.status.textContent = message; }

  placePanel(left, top) {
    const rect = this.panel.getBoundingClientRect();
    const margin = 12;
    this.panel.style.left = `${Math.max(margin, Math.min(left, innerWidth - rect.width - margin))}px`;
    this.panel.style.top = `${Math.max(margin, Math.min(top, innerHeight - rect.height - margin))}px`;
    this.panel.style.right = "auto";
    this.panelPositioned = true;
  }

  clampPanel() {
    const rect = this.panel.getBoundingClientRect();
    this.placePanel(rect.left, rect.top);
  }

  endPanelDrag() {
    const drag = this.panelDrag;
    this.panelDrag = null;
    this.panel?.removeAttribute("data-dragging");
    if (drag && this.dragHandle.hasPointerCapture(drag.pointerId)) this.dragHandle.releasePointerCapture(drag.pointerId);
  }

  initResources() {
    if (this.target) return;
    this.camera = createRobotVisionCamera(this.sim);
    this.camera.name = "robot-depth-camera";
    this.camera.near = 0.001;
    this.camera.far = 3;
    this.camera.updateProjectionMatrix();
    this.target = new THREE.WebGLRenderTarget(this.width, this.height, {
      format: THREE.RGBAFormat, type: THREE.UnsignedByteType,
      minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter,
      depthBuffer: true, stencilBuffer: false, generateMipmaps: false,
    });
    this.target.texture.colorSpace = THREE.NoColorSpace;
    this.material = new THREE.MeshDepthMaterial({
      depthPacking: THREE.RGBADepthPacking, blending: THREE.NoBlending, toneMapped: false,
    });
    this.canvas.width = this.width;
    this.canvas.height = this.height;
    this.context = this.canvas.getContext("2d");
    if (!this.context) throw new Error("Canvas 2D недоступен");
    this.rawPixels = new Uint8Array(this.width * this.height * 4);
    this.depthMeters = new Float32Array(this.width * this.height);
    this.image = this.context.createImageData(this.width, this.height);
  }

  open() {
    if (this.state === "disposed") return;
    this.panel?.removeAttribute("hidden");
    this.button?.setAttribute("aria-expanded", "true");
    this.state = "open";
    this.startedAt = performance.now();
    this.startedCount = this.metrics.frameCount;
    this.invalidate();
    try {
      if (this.contextLost) throw new Error("Графика ещё не восстановлена");
      this.initResources();
      this.setStatus(`Симулятор · ${this.width}×${this.height} · до 2 м`);
    } catch (error) { this.fail(error); }
    if (this.panelPositioned) this.clampPanel();
    this.panel?.querySelector("[data-depth-close]")?.focus({ preventScroll: true });
  }

  close() {
    if (this.state === "disposed") return;
    this.endPanelDrag();
    const hadError = this.state === "error";
    this.state = "closed";
    this.panel?.setAttribute("hidden", "");
    this.button?.setAttribute("aria-expanded", "false");
    if (hadError) this.releaseResources();
    this.button?.focus({ preventScroll: true });
  }

  invalidate() {
    this.nextFrameAt = 0;
    this.canvas.style.visibility = "hidden";
  }

  update(timeMS) {
    if (this.state !== "open" || document.hidden || timeMS < this.nextFrameAt) return;
    // Keep cadence across display frames, without a catch-up rendering loop.
    const interval = 1000 / this.hz;
    this.nextFrameAt = timeMS + interval - (this.nextFrameAt ? (timeMS - this.nextFrameAt) % interval : 0);
    try {
      this.capture();
      this.canvas.style.visibility = "visible";
      this.metrics.frameCount++;
      this.metrics.actualHz = (this.metrics.frameCount - this.startedCount) * 1000 / Math.max(1, performance.now() - this.startedAt);
    } catch (error) { this.fail(error); }
  }

  /** Public for the independent GPU fixture; errors deliberately propagate to its assertions. */
  capture() {
    const { renderer, scene } = this.sim;
    const start = performance.now();
    const previous = {
      target: renderer.getRenderTarget(), face: renderer.getActiveCubeFace(), mip: renderer.getActiveMipmapLevel(),
      autoClear: renderer.autoClear,
      clearColor: renderer.getClearColor(this.clearColor), clearAlpha: renderer.getClearAlpha(),
      outputColorSpace: renderer.outputColorSpace, toneMapping: renderer.toneMapping,
      shadowAutoUpdate: renderer.shadowMap.autoUpdate,
      background: scene.background, fog: scene.fog, overrideMaterial: scene.overrideMaterial,
    };
    const hidden = [];
    try {
      scene.updateMatrixWorld(true);
      this.camera.updateWorldMatrix(true, false);
      scene.traverse(object => {
        if (object.visible && (object.isLine || object.isPoints || object.isSprite || object.userData.depthExclude)) {
          object.visible = false;
          hidden.push(object);
        }
      });
      scene.background = null;
      scene.fog = null;
      scene.overrideMaterial = this.material;
      renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
      renderer.toneMapping = THREE.NoToneMapping;
      renderer.shadowMap.autoUpdate = false;
      renderer.autoClear = false;
      // Target owns viewport/scissor. Leave the renderer's global definitions untouched.
      renderer.setRenderTarget(this.target);
      renderer.setClearColor(0xffffff, 1);
      renderer.clear(true, true, true);
      renderer.render(scene, this.camera);
      renderer.readRenderTargetPixels(this.target, 0, 0, this.width, this.height, this.rawPixels);
    } finally {
      for (const object of hidden) object.visible = true;
      scene.background = previous.background;
      scene.fog = previous.fog;
      scene.overrideMaterial = previous.overrideMaterial;
      renderer.setRenderTarget(previous.target, previous.face, previous.mip);
      renderer.autoClear = previous.autoClear;
      renderer.setClearColor(previous.clearColor, previous.clearAlpha);
      renderer.outputColorSpace = previous.outputColorSpace;
      renderer.toneMapping = previous.toneMapping;
      renderer.shadowMap.autoUpdate = previous.shadowAutoUpdate;
    }
    this.metrics.captureMs = performance.now() - start;
    const colorStart = performance.now();
    colorizeDepth(this.rawPixels, this.width, this.height, this.camera.near, this.camera.far,
      this.depthMeters, this.image.data);
    this.context.putImageData(this.image, 0, 0);
    this.metrics.colorizeMs = performance.now() - colorStart;
  }

  fail(error) {
    if (this.state === "disposed") return;
    const first = this.state !== "error";
    // Context loss while closed must not open the window.
    if (this.state !== "closed") this.state = "error";
    this.invalidate();
    this.setStatus("Карта глубины недоступна. Закрой и открой окно для повторной попытки.");
    if (first) console.error("Карта глубины:", error);
  }

  releaseResources() {
    this.target?.dispose();
    this.material?.dispose();
    this.camera?.removeFromParent();
    this.target = this.material = this.camera = null;
    this.rawPixels = this.depthMeters = this.image = null;
  }

  dispose() {
    if (this.state === "disposed") return;
    this.close();
    this.state = "disposed";
    this.listeners.abort();
    this.releaseResources();
  }
}
