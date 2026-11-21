import { selectBlueBall, blueBallCommand, BALL_COLORS } from "./blue-ball.js";
import { RosBallFollow } from "./ros-ball-follow.js";

/** Follow only YOLO detections, from the simulated camera or the real ROS node. */
export class BallFollower {
  constructor(sim) {
    this.sim = sim;
    this.detection = null;
    this.capturedAt = -Infinity;
    this.active = false;
    this.starting = false;
    this.generation = 0;
    this.remote = null;
    this.color = "blue";
    this.button = document.getElementById("btn-follow-blue");
    this.status = document.getElementById("hud-status");
    this.button.disabled = false;
    this.button.onclick = () => {
      if (this.active || this.starting) this.stop();
      else void this.start();
    };
    this.connectionButton = document.getElementById("btn-robot-connect");
    this.connectionStatus = document.getElementById("robot-connection-status");
    this.connectionButton.onclick = () => { void this.toggleConnection(); };
    this.onPageHide = () => this.dispose();
    window.addEventListener("pagehide", this.onPageHide, { once:true });
    this.updateUI();
  }

  async toggleConnection() {
    this.stop();
    if (this.remote) { this.remote.close(); this.remote = null; this.updateConnectionUI(); return; }
    this.connectionButton.disabled = true;
    this.connectionStatus.textContent = "Подключаю ROS…";
    const remote = new RosBallFollow(status => {
      if (this.remote !== remote) return;
      this.connectionStatus.textContent = status.error || `YOLO робота: ${status.inference_ms.toFixed(0)} мс`;
      this.detection = status.target;
      if (this.active && !status.enabled && performance.now() - this.remoteStartedAt > 800) this.stop();
    }, () => {
      if (this.remote !== remote) return;
      this.stop();
      this.remote = null;
      this.updateConnectionUI();
      this.setStatus("Связь с роботом потеряна — преследование остановлено");
    }, source => {
      if (this.remote !== remote) return;
      this.showRemotePreview();
      this.remoteImage.src = source;
    });
    try {
      await remote.connect(document.getElementById("robot-rosbridge-url").value.trim());
      this.remote = remote;
      this.sim.stopProgram();
      window.__visionPipeline?.pause();
      this.updateConnectionUI();
      this.setStatus("Подключена реальная панда. Кнопка запускает преследование на роботе");
    } catch (error) {
      remote.close();
      this.connectionStatus.textContent = error.message;
    } finally { this.connectionButton.disabled = false; }
  }

  updateConnectionUI() {
    this.detection = null;
    this.capturedAt = -Infinity;
    this.connectionButton.textContent = this.remote ? "Отключить робота" : "Подключить робота";
    this.connectionStatus.textContent = this.remote ? "Реальная камера и YOLO подключены" : "Управление симулятором";
    if (this.remote) this.showRemotePreview();
    else {
      this.remotePreview?.remove();
      this.remotePreview = null;
      const panel = document.getElementById("vision-controls");
      if (panel) panel.hidden = false;
      if (!document.getElementById("tab-cv")?.classList.contains("hidden")) window.__vision?.resume();
    }
    this.updateUI();
  }

  showRemotePreview() {
    if (!this.remotePreview) {
      this.remotePreview = document.createElement("section");
      this.remotePreview.className = "vision-controls";
      this.remotePreview.innerHTML = '<h3>Камера реальной панды · YOLO</h3><img alt="Реальная RGB-камера панды с рамками YOLO" style="display:block;width:100%;height:auto">';
      document.getElementById("vision-mount").appendChild(this.remotePreview);
      this.remoteImage = this.remotePreview.querySelector("img");
    }
    const panel = document.getElementById("vision-controls");
    if (panel) panel.hidden = true;
  }

  async start() {
    if (!this.remote && this.sim.paused) { this.setStatus("Сначала снимите панду с паузы"); return; }
    const generation = ++this.generation;
    this.starting = true;
    this.updateUI();
    try {
      if (this.remote) {
        this.remote.start();
        this.remoteStartedAt = performance.now();
      } else {
        const pipeline = await window.__vision.ensureStarted();
        if (generation !== this.generation) {
          if (document.getElementById("tab-cv")?.classList.contains("hidden")) pipeline.pause();
          return;
        }
        pipeline.resume();
        const [ready] = await Promise.all([this.sim.policy.load(), pipeline.waitUntilReady()]);
        if (generation !== this.generation) return;
        if (!ready) throw new Error("Не удалось загрузить ходьбу");
        if (this.sim.paused) throw new Error("Панда на паузе");
        this.sim.player.stop();
        this.sim.player.startPolicy();
        this.sim.player.notifyActive();
      }
      this.active = true;
      this.starting = false;
      this.updateUI();
    } catch (error) {
      if (generation !== this.generation) return;
      this.stop();
      this.setStatus(`Преследование недоступно: ${error.message}`);
    }
  }

  receiveDetections(detections, width, height, capturedAt) {
    if (this.remote || capturedAt < this.capturedAt) return;
    this.detection = selectBlueBall(detections, width, height, this.color);
    this.capturedAt = capturedAt;
    if (!this.active && !this.starting) {
      const ru = BALL_COLORS[this.color].ru;
      this.setStatus(this.detection ? `YOLO видит ${ru} шарик` : `YOLO: ${ru} шарик не найден`);
    }
  }

  setColor(color) {
    if (!BALL_COLORS[color] || color === this.color) return;
    this.color = color;
    this.detection = null;
    this.capturedAt = -Infinity;
    this.updateUI();
  }

  stop({ keepPolicy = false } = {}) {
    ++this.generation;
    const wasActive = this.active;
    this.active = false;
    this.starting = false;
    if (this.remote) this.remote.stop();
    else if (wasActive && !keepPolicy) this.sim.player.stopPolicy();
    if (document.getElementById("tab-cv")?.classList.contains("hidden")) window.__vision?.pause();
    this.updateUI();
  }

  setStatus(text) { if (this.status.textContent !== text) this.status.textContent = text; }

  updateUI() {
    const color = BALL_COLORS[this.color];
    this.button.style.setProperty("--ball-color", color.hex);
    this.button.setAttribute("aria-pressed", String(this.active || this.starting));
    this.button.classList.toggle("accent", this.active || this.starting);
    this.button.textContent = this.starting ? "⏳ запуск" : this.active ? "🛑 стоп"
      : this.remote ? "🤖 следовать" : "🎯 следовать";
    this.setStatus(this.starting ? "Готовлю YOLO и ходьбу…" : this.active
      ? `Ищу ${color.ru} шарик через YOLO…` : "Цель определяет YOLO по изображению камеры");
  }

  tick(now) {
    if (!this.active) return;
    if (this.remote) {
      if (!this.remote.connected || now-this.remote.lastStatusAt>700) {
        this.stop(); this.setStatus("Нет свежего статуса робота — преследование остановлено"); return;
      }
    } else {
      if (this.sim.paused || !this.sim.player.policyOn || !this.sim.policy.available) { this.stop(); return; }
      this.sim.player.setPolicyCmd(blueBallCommand(this.detection, now, this.capturedAt));
    }
    const visible = this.detection && (this.remote || now-this.capturedAt<=700);
    const ru = BALL_COLORS[this.color].ru;
    this.setStatus(!visible ? `YOLO: ${ru} не виден — стою и жду`
      : this.detection.relativeWidth>=.18 ? `YOLO: ${ru} рядом — жду его движения` : `YOLO: вижу ${ru} — следую за ним`);
  }

  dispose() {
    this.stop();
    this.remote?.close();
    window.removeEventListener("pagehide", this.onPageHide);
  }
}
