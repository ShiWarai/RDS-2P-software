
import { VisionPipeline } from "./vision.js";

const state = { started: false, starting: false, attempts: 0 };

function tryStart() {
  if (state.started || state.starting) return;

  const sim = window.__panda?.sim;

  if (!(sim?.model && sim?.renderer && sim?.scene)) {
    state.attempts++;

    if (state.attempts > 3600) {
      console.error("Vision: симулятор не стал готов за 60 секунд");
      return;
    }

    requestAnimationFrame(tryStart);
    return;
  }

  state.starting = true;

  const pipeline = new VisionPipeline(sim);

  pipeline.init()
    .then(() => {
      state.started = true;
      state.starting = false;
      window.__visionPipeline = pipeline;
      console.info("Vision pipeline initialized");
    })
    .catch((error) => {
      state.starting = false;
      console.error("Vision pipeline initialization failed:", error);

      const node = document.createElement("div");
      node.className = "vision-init-error";
      node.textContent =
        `Камера компьютерного зрения не запустилась: ${error.message}`;

      document.getElementById("vision-mount")?.appendChild(node);
    });
}

// Ленивый контроллер: конвейер запускается только при первом открытии
// вкладки «Компьютерное зрение», а не при загрузке страницы.
window.__vision = {
  ensureStarted() {
    state.attempts = 0;
    tryStart();
  },
  resume() { window.__visionPipeline?.resume(); },
  pause() { window.__visionPipeline?.pause(); },
  isRunning() { return Boolean(window.__visionPipeline); },
};

window.addEventListener("pagehide", () => {
  window.__visionPipeline?.dispose();
});
