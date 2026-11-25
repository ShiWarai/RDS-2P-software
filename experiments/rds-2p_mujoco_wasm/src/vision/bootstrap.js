import { VisionPipeline } from "./vision.js";
let starting = null;
window.__vision = {
  ensureStarted() {
    if (window.__visionPipeline) return Promise.resolve(window.__visionPipeline);
    if (starting) return starting;
    starting = (async () => {
      const deadline = performance.now() + 60000;
      while (!window.__panda?.sim?.model) {
        if (performance.now() > deadline) throw new Error("Симулятор не готов для камеры");
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      const pipeline = new VisionPipeline(window.__panda.sim);
      try {
        await pipeline.init();
        window.__visionPipeline = pipeline;
        return pipeline;
      } catch (error) {
        await pipeline.dispose();
        throw error;
      }
    })().finally(() => { starting = null; });
    return starting;
  },
  resume() { window.__visionPipeline?.resume(); },
  pause() { window.__visionPipeline?.pause(); },
  isRunning() { return Boolean(window.__visionPipeline); },
};
window.addEventListener("pagehide", () => { void window.__visionPipeline?.dispose(); });
