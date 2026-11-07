import { mirrorJointAngles } from "./mirrorPose.js";
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
    this.smoothBlend = false;
    this.holdEnd = 0;
    this.simTime = 0;
    this.stepDoneAt = 0;

    // no_limit: сохраняем исходные ctrllimited, включаем на время шага.
    this.origLimited = Uint8Array.from(model.actuator_ctrllimited);
    // Позиционные приводы тянут сустав; MuJoCo жёстко клампит qpos по jnt_limited,
    // поэтому для no_limit-поз (кувырок) снимаем и пределы суставов, не только ctrl.
    this.actJoint = new Int32Array(model.nu);
    for (let i = 0; i < model.nu; i++) {
      const trnId = model.actuator_trnid[2 * i]; // trntype=position → trnid = id сустава
      this.actJoint[i] = (trnId >= 0 && trnId < model.njnt) ? trnId : -1;
    }
    this.origJntLimited = new Uint8Array(model.njnt);
    for (let i = 0; i < model.njnt; i++) {
      this.origJntLimited[i] = model.jnt_limited[i];
    }
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

    this.passiveFoldTendons = [];
    const decoder = new TextDecoder();
    for (let i = 0; i < model.ntendon; i++) {
      const start = model.name_tendonadr[i];
      const name = decoder.decode(model.names.subarray(start, model.names.indexOf(0, start)));
      if (name.startsWith("passive_fold_")) this.passiveFoldTendons.push(i);
    }
    this.floorGeom = -1;
    this.torsoGeom = -1;
    this.footGeoms = [];
    for (let i = 0; i < model.ngeom; i++) {
      const start = model.name_geomadr[i];
      const name = decoder.decode(model.names.subarray(start, model.names.indexOf(0, start)));
      if (name === "floor") this.floorGeom = i;
      if (name === "base_link_collision") this.torsoGeom = i;
      if (/^foot_(fl|fr|bl|br)_link_collision$/.test(name)) this.footGeoms.push(i);
    }
    this.waitingForRest = false;
    this.lyingContactBackup = null;
    this.restDuration = 0;
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
    this.waitingForRest = false;
    this.smoothBlend = false;
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
    this.waitingForRest = false;
    this.onStep(step.label || "", step);
    this.notifyActive();

    switch (step.kind) {
      case "pose": {
        // Приоритет — точные углы из таблицы робота (assets/pose_angles.json);
        // норм-цепочка остаётся для пользовательских поз и слайдеров.
        const resolvedAngles = typeof step.pose === "string" ? this.resolvePoseAngles(step.pose) : null;
        const angles = resolvedAngles && step.mirror ? mirrorJointAngles(resolvedAngles) : resolvedAngles;
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
        this.smoothBlend = !!step.smooth;
        this.blendDur = Math.max(1, step.blend ?? 400) / 1000.0;
        this.blendStart = this.simTime;
        this.stepDoneAt = this.simTime + this.blendDur + Math.max(0, (step.hold ?? 300) / 1000.0);
        break;
      }
      case "wait":
        this.stepDoneAt = this.simTime + Math.max(0, (step.ms ?? 300) / 1000.0);
        break;
      case "release":
        this.waitingForRest = !!step.waitForRest;
        this.restDuration = 0;
        this.restDeadline = this.simTime + (step.restTimeoutMs ?? 15000) / 1000;
        this.disableTorque();
        if (this.waitingForRest) this.beginLyingContact();
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
        // «Запасного варианта» нет: тротом ходьбу не подменяем (так просил не делать).
        if (step.stop) {
          // stopPolicy сам задаёт дедлайн: 0.4 с бленда к нулевой стойке.
          // Затирать его нельзя (this.stepDoneAt = simTime убивал бленд —
          // приводы замерзали в позе ходьбы, а не вставала стойка).
          this.stopPolicy();
        } else {
          this.startPolicy(step);
          // Управление сразу переходит к следующему шагу: ходьба продолжается,
          // пока идёт wait (он и задаёт длительность), затем policy-stop тормозит.
          this.stepDoneAt = this.simTime;
          // Модель ещё качается/поднимается — шаг просто ждёт её (policyRunner
          // докачивает сам); пойдём ровно с командой, когда сессия будет готова.
          if (!this.policy?.available) { this.policy?.load?.(); }
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
    this.updateLyingContact();
    if (this.policyOn) {
      this.tickPolicy(dt);
      // Дедлайн шага надо проверять и при активной политике: длительность
      // ходьбы задаёт wait-шаг, следующий за policy-шагом. Без этого wait и
      // policy-stop недостижимы и Панда «бежит» вечно. После конца программы
      // (cursor за пределами steps) advance не крутим — иначе спам notifyActive.
      if (this.policy?.available && this.simTime >= this.stepDoneAt && this.cursor < this.steps.length) {
        this.advance(0);
      }
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
    let span = this.blendDur > 0 ? Math.min(1, (this.simTime - this.blendStart) / this.blendDur) : 1;
    if (this.smoothBlend) span = span * span * span * (10 + span * (-15 + 6 * span));
    const ctrl = this.data.ctrl;
    for (let i = 0; i < this.model.nu; i++) {
      ctrl[i] = this.from[i] + (this.to[i] - this.from[i]) * span;
    }

    if (this.simTime >= this.stepDoneAt) {
      if (this.waitingForRest) {
        this.restDuration = this.isSupportedAndStill() ? this.restDuration + dt : 0;
        if (this.restDuration < 0.25) {
          if (this.simTime >= this.restDeadline) {
            this.stop();
            this.onStep("Не удалось закончить укладку: робот ещё движется или лапы не опущены", { kind: "settle_timeout" });
          }
          return;
        }
        this.waitingForRest = false;
        this.onStep("лежит: корпус и лапы опущены", { kind: "settled" });
      }
      const finished = this.steps[this.cursor];
      this.advance(0);
      if (finished && this.running) {
        // «release» держит приводы обесточенными, пока следующая поза сама их не включит.
      }
    }
  }

  /** A contact shell covers the CAD bottom protruding 2 mm below the box.
   * Only the passive lie-down uses it; powered commands retain the model settings.
   */
  beginLyingContact() {
    if (this.lyingContactBackup || this.floorGeom < 0 || this.torsoGeom < 0) return;
    const m = this.model;
    this.lyingContactBackup = {
      margin: m.geom_margin[this.torsoGeom],
      noslip: m.opt.noslip_iterations,
    };
    m.geom_margin[this.torsoGeom] = Math.max(this.lyingContactBackup.margin, 0.0025);
  }

  torsoSupportCount() {
    if (this.floorGeom < 0 || this.torsoGeom < 0) return 0;
    const m = this.model, d = this.data;
    const margin = Math.max(m.geom_margin[this.floorGeom], m.geom_margin[this.torsoGeom]);
    let supports = 0;
    for (let i = 0; i < d.ncon; i++) {
      const c = d.contact.get(i);
      // With a margin, a supporting constraint starts before geometric overlap.
      if (c.dist < margin && ((c.geom1 === this.floorGeom && c.geom2 === this.torsoGeom) ||
          (c.geom2 === this.floorGeom && c.geom1 === this.torsoGeom))) supports++;
    }
    return supports;
  }

  updateLyingContact() {
    if (!this.lyingContactBackup) return;
    // Apply the friction refinement after the body has landed, not while the
    // feet are folding. Early refinement can hinder the passive descent.
    this.model.opt.noslip_iterations = this.torsoSupportCount() >= 3
      ? Math.max(5, this.lyingContactBackup.noslip) : this.lyingContactBackup.noslip;
  }

  restoreLyingContact() {
    if (!this.lyingContactBackup) return;
    this.model.geom_margin[this.torsoGeom] = this.lyingContactBackup.margin;
    this.model.opt.noslip_iterations = this.lyingContactBackup.noslip;
    this.lyingContactBackup = null;
  }

  /** Physical completion, not a fixed delay or a forced final pose. */
  isSupportedAndStill() {
    const m = this.model, d = this.data;
    if (this.floorGeom < 0 || this.torsoGeom < 0 || this.footGeoms.length !== 4) return false;
    const v = d.qvel;
    if (Math.hypot(v[0], v[1], v[2]) > 0.0002 || Math.hypot(v[3], v[4], v[5]) > 0.01) return false;
    for (let i = 6; i < v.length; i++) if (Math.abs(v[i]) > 0.015) return false;
    if (this.torsoSupportCount() < 3) return false;
    // Foot colliders in this model are cylinders. Compute their lowest point
    // using their current orientation; foot-center height alone is misleading.
    const positions = d.geom_xpos, rotations = d.geom_xmat, sizes = m.geom_size;
    for (const g of this.footGeoms) {
      const extent = sizes[3*g] * Math.hypot(rotations[9*g+6], rotations[9*g+7]) +
        sizes[3*g+1] * Math.abs(rotations[9*g+8]);
      if (positions[3*g+2] - extent > 0.001) return false;
    }
    return true;
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

  /** Обновить команду скорости (ручное вождение стрелками + Shift). */
  setPolicyCmd(cmd) {
    if (!cmd) { return; }
    this.policyCmd = [cmd[0] ?? 0, cmd[1] ?? 0, cmd[2] ?? 0];
  }

  /** 50 Гц: собрать obs → отправить в worker → ctrl из последнего ответа. */
  tickPolicy(dt = 0) {
    if (!this.policy?.available) {
      // Воркер политики упал/поднимается — НЕ откат на трот: просим подняться
      // заново и мягко сводим приводы к нулевой стойке, пока ждём (секунды:
      // байты модели уже скачаны, сессия пересоздаётся на главном потоке).
      this.policy?.load?.();
      const ctrl = this.data.ctrl;
      const decay = Math.min(1, dt * 2.5);
      for (let i = 0; i < this.model.nu; i++) { ctrl[i] *= (1 - decay); }
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
    const jl = this.model.jnt_limited;
    for (let i = 0; i < this.actJoint.length; i++) {
      const jid = this.actJoint[i];
      if (jid < 0) { continue; }
      jl[jid] = on ? 0 : this.origJntLimited[jid];
    }
    this.limitRelaxed = on;
  }

  disableTorque() {
    if (this.torqueOff) { return; }
    const m = this.model;
    this.gainBackup = Float64Array.from(m.actuator_gainprm);
    this.biasBackup = Float64Array.from(m.actuator_biasprm);
    if (this.passiveFoldTendons.length) {
      this.foldDampingBackup = Float64Array.from(m.tendon_damping);
      this.integratorBackup = m.opt.integrator;
      // Implicit integration is needed for the coupled viscous dampers.
      m.opt.integrator = this.mujoco.mjtIntegrator.mjINT_IMPLICITFAST.value;
      for (const i of this.passiveFoldTendons) m.tendon_damping[i] = 10;
    }
    m.actuator_gainprm.fill(0);
    m.actuator_biasprm.fill(0);
    this.torqueOff = true;
  }

  enableTorque() {
    this.restoreLyingContact();
    if (!this.torqueOff) { return; }
    const m = this.model;
    if (this.foldDampingBackup) {
      m.tendon_damping.set(this.foldDampingBackup);
      m.opt.integrator = this.integratorBackup;
      this.foldDampingBackup = null;
    }
    // Torque-off lets the legs move independently of the previous ctrl target.
    // Recompute transmission positions before restoring gains, then start the
    // next blend from the actual pose. mj_forward does not advance time.
    this.mujoco.mj_forward(m, this.data);
    this.data.ctrl.set(this.data.actuator_length.subarray(0, m.nu));
    m.actuator_gainprm.set(this.gainBackup);
    m.actuator_biasprm.set(this.biasBackup);
    this.torqueOff = false;
  }

  isTorqueOff() { return this.torqueOff; }
}

function clampR(x, lo, hi) { return Math.min(hi, Math.max(lo, x)); }

