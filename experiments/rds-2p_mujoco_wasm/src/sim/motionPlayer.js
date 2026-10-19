import { PoseManager } from "./poseManager.js";
import { buildObs } from "./policyRunner.js";

/**
 * Исполнитель программ движений поверх данных MuJoCo.
 *
 * Плеер хранит очередь шагов (see src/robot/motions.js) и в каждый кадр
 * рассчитывает ctrl-целевую позу: линейный бленд поза-в-позу за blend ms,
 * затем удержание hold ms. no_limit-шаги временно снимают ctrllimited
 * с мягким предохранителем (см. PoseManager).
 *
 * Компоновщик правил (src/rules/to_program.js) приводит действие правила
 * к тому же формату шагов, поэтому «дай лапу» из кнопки и из правила
 * исполняются одинаково.
 */
export class MotionPlayer {
  /**
   * @param {object} opts
   * @param {import("mujoco-js").default} opts.mujoco
   * @param {object} opts.model
   * @param {object} opts.data
   * @param {PoseManager} opts.poses
   * @param {(name: string) => number[] | null} opts.resolvePose имя → 12 норм.значений
   * @param {(name: string) => number[] | null} [opts.resolvePoseAngles] имя → 12 углов (рад)
   * @param {(id: string) => object[] | null} [opts.resolveCommand] команда → её программа шагов
   * @param {(label: string, step: object) => void} opts.onStep
   */
  constructor({ mujoco, model, data, poses, resolvePose, resolvePoseAngles, resolveCommand, onStep }) {
    this.mujoco = mujoco;
    this.model = model;
    this.data = data;
    this.poses = poses;
    this.resolvePose = resolvePose;
    this.resolvePoseAngles = resolvePoseAngles || (() => null);
    this.resolveCommand = resolveCommand || (() => null);
    this.onStep = onStep || (() => {});

    this.steps = [];
    this.cursor = -1;
    this.running = false;
    this.onActive = null;

    // Текущий линейный переход ctrl.
    this.from = Float64Array.from(data.ctrl.subarray(0, model.nu));
    this.to = Float64Array.from(this.from);
    this.blendStart = 0;
    this.blendDur = 0;
    this.holdEnd = 0;
    this.simTime = 0;
    this.stepDoneAt = 0;

    // no_limit: сохраняем исходные ctrllimited, включаем на время шага.
    this.origLimited = Uint8Array.from(model.actuator_ctrllimited);
    this.limitRelaxed = false;

    // Procedural trot.
    this.gaitOn = false;
    this.gaitPhase = 0;

    // Нейросетевая политика ходьбы (rds2p_policy.onnx).
    this.policy = null;
    this.policyOn = false;
    this.policyNextAt = 0;
    this.policyTarget = null;
    this.policyCmd = [0, 0, 0];

    this.torqueOff = false;
    this.gainBackup = null;
    this.biasBackup = null;

  }

  /** Подключить PolicyRunner (см. policyRunner.js). */
  attachPolicy(runner) {
    this.policy = runner;
    runner.onActions = (cmd) => {
      if (this.policyOn && this.policyTarget) {
        this.policyTarget.set(cmd.subarray(0, this.model.nu));
      }
    };
  }

  /** @param {Array<object>} steps */
  play(steps) {
    this.stopGait();
    this.stopPolicy();
    this.steps = steps || [];
    this.cursor = 0;
    this.running = this.steps.length > 0;
    this.notifyActive();
    this.from = Float64Array.from(this.data.ctrl.subarray(0, this.model.nu));
    this.applyStep(this.steps[0]);
  }

  stop() {
    this.running = false;
    this.steps = [];
    this.cursor = -1;
    this.stopPolicy();
    this.stopGait();
    this.relaxLimits(false);
    this.notifyActive();
  }

  /** Активна ли какая-либо программа/походка (для кнопки ▶/⏹). */
  get active() {
    return this.running || this.gaitOn || this.policyOn;
  }

  notifyActive() {
    if (this.onActive) { this.onActive(this.running); }
  }

  isRunning() {
    return this.running;
  }

  applyStep(step) {
    if (!step) {
      this.running = false;
      return;
    }
    this.onStep(step.label || "", step);
    this.notifyActive();

    switch (step.kind) {
      case "pose": {
        // Приоритет — точные углы из таблицы робота (assets/pose_angles.json);
        // норм-цепочка остаётся для пользовательских поз и слайдеров.
        const angles = typeof step.pose === "string" ? this.resolvePoseAngles(step.pose) : null;
        let target = null;
        let noLimit = false;
        if (angles) {
          noLimit = step.noLimit ?? this.poses.anglesOutOfRange(angles);
          this.relaxLimits(noLimit);
          target = this.poses.clampToCtrl(angles, { noLimit });
        } else {
          const norm = typeof step.pose === "string" ? this.resolvePose(step.pose) : step.pose;
          if (!norm) {
            // Неизвестная поза — пропускаем шаг.
            this.advance(0);
            return;
          }
          noLimit = step.noLimit ?? PoseManager.isNoLimit(norm);
          this.relaxLimits(noLimit);
          target = this.poses.normToCtrl(norm, { noLimit });
        }
        this.enableTorque();
        this.from = Float64Array.from(this.data.ctrl.subarray(0, this.model.nu));
        this.to = target;
        this.blendDur = Math.max(1, step.blend ?? 400) / 1000.0;
        this.blendStart = this.simTime;
        this.stepDoneAt = this.simTime + this.blendDur + Math.max(0, (step.hold ?? 300) / 1000.0);
        break;
      }
      case "wait":
        this.stepDoneAt = this.simTime + Math.max(0, (step.ms ?? 300) / 1000.0);
        break;
      case "release":
        this.disableTorque();
        this.stepDoneAt = this.simTime + Math.max(0, (step.ms ?? 600) / 1000.0);
        break;
      case "gait":
        if (step.on) { this.startGait(); this.stepDoneAt = Infinity; }
        else { this.stopGait(); this.stepDoneAt = this.simTime; }
        this.notifyActive();
        break;
      case "command": {
        // Шаг-команда («дай лапу», «лежать», «шаг вперёд»…) разворачивается в свою
        // программу прямо в очереди. Без этого случая команды молча пропускались —
        // в интерфейсе появлялась только подпись, а панда не двигалась.
        const prog = this.resolveCommand(step.command);
        if (prog && prog.length) {
          this.steps.splice(this.cursor + 1, 0, ...prog.map((s) => ({ ...s })));
        }
        this.stepDoneAt = this.simTime; // сразу переходим к вставленным шагам (или дальше)
        break;
      }
      case "policy": {
        // Нейросетевая походка: stop=true — выключить, иначе включить с cmd_vel.
        if (step.stop) {
          this.stopPolicy();
          this.stepDoneAt = this.simTime;
        } else if (this.policy?.available) {
          this.startPolicy(step);
          this.stepDoneAt = Infinity;
        } else {
          // Политики нет — честный фолбэк на процедурный трот.
          this.startGait();
          this.stepDoneAt = Infinity;
        }
        this.notifyActive();
        break;
      }
      case "say": {
        const len = String(step.text || "").length;
        this.stepDoneAt = this.simTime + Math.max(0.8, Math.min(4.2, 0.9 + len * 0.055));
        break;
      }
      default:
        this.stepDoneAt = this.simTime;
    }
  }

  advance(ignored) {
    void ignored;
    this.cursor += 1;
    if (this.cursor >= this.steps.length) {
      this.running = false;
      this.notifyActive();
      return;
    }
    this.applyStep(this.steps[this.cursor]);
  }

  /** Вызывается из цикла симуляции с приращением модельного времени (сек). */
  tick(dt) {
    this.simTime += dt;
    if (this.policyOn && this.policy?.available) {
      this.tickPolicy();
      return;
    }
    if (this.gaitOn) {
      this.gaitPhase += dt * 2.0 * Math.PI * 1.7; // частота trot ≈ 1.7 Гц
      this.writeGaitCtrl();
      return;
    }
    if (!this.running) {
      return;
    }

    // Линейный бленд from → to за blendDur.
    const span = this.blendDur > 0 ? Math.min(1, (this.simTime - this.blendStart) / this.blendDur) : 1;
    const ctrl = this.data.ctrl;
    for (let i = 0; i < this.model.nu; i++) {
      ctrl[i] = this.from[i] + (this.to[i] - this.from[i]) * span;
    }

    if (this.simTime >= this.stepDoneAt) {
      const finished = this.steps[this.cursor];
      this.advance(0);
      if (finished && this.running) {
        // «release» держит приводы обесточенными, пока следующая поза сама их не включит.
      }
    }
  }

  writeGaitCtrl() {
    // Процедурный трот «на месте»: диагональные пары (fl+br / fr+bl) в противофазе.
    // best-effort — походка внешнего сервиса робота тут не воспроизводится один-в-один.
    const base = this.baseGaitCtrl;
    const ctrl = this.data.ctrl;
    const lo = this.poses.lo;
    const hi = this.poses.hi;
    const A = 0.5;  // размах таза, рад
    const F = 0.7;  // сгибание голени на махе, рад
    const t = this.gaitPhase;
    // idx ног: 0=fl,1=fr,2=bl,3=br; phase: fl/br синхронны, fr/bl в противофазе
    const phase = [t, t + Math.PI, t + Math.PI, t];
    for (let leg = 0; leg < 4; leg++) {
      const hip = leg * 3 + 1;
      const knee = leg * 3 + 2;
      ctrl[hip] = clampR(base[hip] + A * Math.sin(phase[leg]), lo[hip], hi[hip]);
      ctrl[knee] = clampR(base[knee] - F * (0.5 - 0.5 * Math.cos(phase[leg])), lo[knee], hi[knee]);
    }
  }

  startGait() {
    this.enableTorque();
    // База — текущая поза (нейтральная, если стоит).
    this.baseGaitCtrl = Float64Array.from(this.data.ctrl.subarray(0, this.model.nu));
    this.gaitOn = true;
  }

  stopGait() {
    if (this.gaitOn && this.baseGaitCtrl) {
      // Плавно возвращаемся к базе.
      this.from = Float64Array.from(this.data.ctrl.subarray(0, this.model.nu));
      this.to = Float64Array.from(this.baseGaitCtrl);
      this.blendStart = this.simTime;
      this.blendDur = 0.4;
      this.stepDoneAt = this.simTime + 0.4;
    }
    this.gaitOn = false;
  }

  /* ── нейросетевая политика ───────────────────────── */

  startPolicy(step = {}) {
    this.enableTorque();
    this.stopGait();
    this.policy.reset();
    this.policyCmd = [step.vx ?? 0, step.vy ?? 0, step.wz ?? 0];
    this.policyTarget = Float64Array.from(this.data.ctrl.subarray(0, this.model.nu));
    this.policyNextAt = this.simTime;
    this.policyOn = true;
  }

  stopPolicy() {
    if (!this.policyOn) { return; }
    this.policyOn = false;
    this.policyCmd = [0, 0, 0];
    // Как на роботе (кнопка R1): плавно к нулевым углам (дефолтная стойка).
    this.from = Float64Array.from(this.data.ctrl.subarray(0, this.model.nu));
    this.to = new Float64Array(this.model.nu);
    this.blendStart = this.simTime;
    this.blendDur = 0.4;
    this.running = true;
    this.steps = [];
    this.cursor = -1;
    this.stepDoneAt = this.simTime + 0.4;
  }

  /** Обновить команду скорости (для ручного вождения WASD). */
  setPolicyCmd(cmd) {
    if (!cmd) { return; }
    this.policyCmd = [cmd[0] ?? 0, cmd[1] ?? 0, cmd[2] ?? 0];
  }

  /** 50 Гц: собрать obs → отправить в worker → ctrl из последнего ответа. */
  tickPolicy() {
    if (!this.policy?.available) {
      // Воркер политики умер/не готов — честный откат на процедурный трот.
      this.policyOn = false;
      this.startGait();
      this.notifyActive();
      return;
    }
    if (this.simTime >= this.policyNextAt) {
      this.policyNextAt = this.simTime + 0.02;
      const obs = buildObs(this.data, this.policyCmd, this.policy.lastAction);
      this.policy.send(obs);
    }
    if (this.policyTarget) {
      const ctrl = this.data.ctrl;
      const n = Math.min(this.model.nu, this.policyTarget.length);
      for (let i = 0; i < n; i++) { ctrl[i] = this.policyTarget[i]; }
    }
  }

  relaxLimits(on) {
    if (on === this.limitRelaxed) { return; }
    const lim = this.model.actuator_ctrllimited;
    for (let i = 0; i < lim.length; i++) {
      lim[i] = on ? 0 : this.origLimited[i];
    }
    this.limitRelaxed = on;
  }

  disableTorque() {
    if (this.torqueOff) { return; }
    const m = this.model;
    this.gainBackup = Float64Array.from(m.actuator_gainprm);
    this.biasBackup = Float64Array.from(m.actuator_biasprm);
    m.actuator_gainprm.fill(0);
    m.actuator_biasprm.fill(0);
    this.torqueOff = true;
  }

  enableTorque() {
    if (!this.torqueOff) { return; }
    const m = this.model;
    m.actuator_gainprm.set(this.gainBackup);
    m.actuator_biasprm.set(this.biasBackup);
    this.torqueOff = false;
  }

  isTorqueOff() { return this.torqueOff; }
}

function clampR(x, lo, hi) { return Math.min(hi, Math.max(lo, x)); }
