import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import load_mujoco from "mujoco-js";
import {
  downloadSceneFolder,
  drawTendonsAndFlex,
  getPosition,
  getQuaternion,
  loadSceneFromURL,
} from "./mujocoUtils.js";
import { PoseManager } from "./poseManager.js";
import { MotionPlayer } from "./motionPlayer.js";
import { PolicyRunner } from "./policyRunner.js";
import { DragStateManager } from "./utils/DragStateManager.js";
import { toMujocoPos } from "./mujocoUtils.js";

const SCENE_FILE = "rds2p_feetonly_scene.xml";
const HOME_KEYFRAME = 0; // keyframe «home» в rds-2p_feetonly.mjcf

/**
 * Обёртка MuJoCo-сцены: рендер в контейнер (правая половина экрана),
 * физика в реальном времени, исполнение программ движений, ручное управление.
 */
export class Simulator {
  constructor() {
    this.mujoco = null;
    this.model = null;
    this.data = null;
    this.bodies = {};
    this.lights = [];
    this.poseManager = null;
    this.player = null;
    this.paused = false;
    this.resolvePose = () => null;
    this.resolvePoseAngles = () => null;
    this.resolveCommand = () => null;
    this.onStep = () => {};
    this.simClockMs = 0;
    this.tmpVec = new THREE.Vector3();
    this.tmpQuat = new THREE.Quaternion();
    this.headBody = null;
    this.bubbleUntil = 0;
  }

  /** @param {HTMLElement} container */
  async init(container) {
    this.container = container;
    this.mujoco = await load_mujoco();

    this.mujoco.FS.mkdir("/working");
    this.mujoco.FS.mount(this.mujoco.MEMFS, { root: "." }, "/working");
    await downloadSceneFolder(this.mujoco);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0.88, 0.92, 0.97);
    this.scene.fog = new THREE.Fog(this.scene.background, 15, 25.5);

    const w = container.clientWidth || 640;
    const h = container.clientHeight || 480;
    this.camera = new THREE.PerspectiveCamera(45, w / h, 0.001, 100);
    this.camera.position.set(0.6, 0.4, 0.6);
    this.scene.add(this.camera);

    // Небо/земля — мягкая цветная подложка (уличное освещение «зоопарка»).
    this.hemiLight = new THREE.HemisphereLight(0xcfe4ff, 0x87a06a, 0.9);
    this.scene.add(this.hemiLight);
    this.ambientLight = new THREE.AmbientLight(0xffffff, 0.35);
    this.scene.add(this.ambientLight);
    // Ключевой свет — с fronts (морда панды смотрит на +x), чтобы лицо было светлым.
    this.spotlight = new THREE.DirectionalLight(0xfff4e0, 2.2);
    this.spotlight.castShadow = true;
    this.spotlight.position.set(2.4, 2.6, 0.9);
    const targetObject = new THREE.Object3D();
    targetObject.position.set(0, 0.12, 0);
    this.scene.add(targetObject);
    this.spotlight.target = targetObject;
    this.scene.add(this.spotlight);
    // Холодный контровой сзади-слева — отделяет панду от травы.
    this.rimLight = new THREE.DirectionalLight(0xbfd6ff, 0.5);
    this.rimLight.position.set(-2, 1.4, -1.6);
    this.scene.add(this.rimLight);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(1.0);
    // CSS сам тянет canvas по контейнеру — макет не распирается его размером.
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    THREE.ColorManagement.enabled = false;
    this.renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 0.15, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.1;
    this.controls.screenSpacePanning = true;
    this.controls.update();

    [this.model, this.data, this.bodies, this.lights] =
      await loadSceneFromURL(this.mujoco, SCENE_FILE, this);

    // Голова для облачка диалога (panda_visual_link), запасной якорь — base_link.
    this.headBody = Object.values(this.bodies).find((b) => b.name === "panda_visual_link")
      || this.bodies[1] || null;

    // Заводские kp/kv модели (kp=4.16 Н·м/рад) слишком мягкие: стойки на трёх
    // лапах (дай лапу, служить) заваливаются. Для мастер-класса усиливаем PD×3,
    // чтобы панда уверенно держала позы. Настоящий робот использует свой контроллер.
    const STIFFNESS = 3.0;
    for (let i = 0; i < this.model.nu; i++) {
      this.model.actuator_gainprm[3 * i] *= STIFFNESS;
      this.model.actuator_biasprm[3 * i + 1] *= STIFFNESS;
      this.model.actuator_biasprm[3 * i + 2] *= STIFFNESS;
    }

    this.resetToHome();

    this.poseManager = new PoseManager(this.model);
    this.player = new MotionPlayer({
      mujoco: this.mujoco,
      model: this.model,
      data: this.data,
      poses: this.poseManager,
      resolvePose: (name) => this.resolvePose(name),
      resolvePoseAngles: (name) => this.resolvePoseAngles(name),
      resolveCommand: (id) => this.resolveCommand(id),
      onStep: (label, step) => this.onStep(label, step),
    });
    // Нейросетевая походка (грузится лениво при первой команде «беги»).
    this.policy = new PolicyRunner();
    this.player.attachPolicy(this.policy);

    new ResizeObserver(() => this.resize()).observe(container);
    this.containerEl = container;

    // Можно тянуть панду за тело мышью (как в wasm_demo).
    this.drag = new DragStateManager(this.scene, this.renderer, this.camera, container, this.controls);
    this.tmpDragVec = new THREE.Vector3();

    this.buildZoo();
    this.improveShadows();

    this.renderer.setAnimationLoop((timeMS) => this.render(timeMS));
  }

  /** Зоопарк: деревья, кусты, цветы, пруд — декор без физики. */
  buildZoo() {
    const zoo = new THREE.Group();
    zoo.name = "zoo";
    const trunkMat = new THREE.MeshLambertMaterial({ color: 0x8b5a2b });
    const leafMat = new THREE.MeshLambertMaterial({ color: 0x3e9e52 });
    const leafMat2 = new THREE.MeshLambertMaterial({ color: 0x2f8442 });
    const bushMat = new THREE.MeshLambertMaterial({ color: 0x54b06a });
    const rockMat = new THREE.MeshLambertMaterial({ color: 0x9aa0a6 });
    const pondMat = new THREE.MeshLambertMaterial({ color: 0x63c7f0 });
    const flowerMats = [0xf76f93, 0xf7c948, 0xffffff].map(
      (c) => new THREE.MeshLambertMaterial({ color: c })
    );

    const tree = (x, z, s) => {
      const g = new THREE.Group();
      const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.03 * s, 0.05 * s, 0.36 * s, 8), trunkMat);
      trunk.position.y = 0.18 * s;
      const c1 = new THREE.Mesh(new THREE.ConeGeometry(0.24 * s, 0.5 * s, 9), leafMat);
      c1.position.y = 0.5 * s;
      const c2 = new THREE.Mesh(new THREE.ConeGeometry(0.19 * s, 0.42 * s, 9), leafMat2);
      c2.position.y = 0.78 * s;
      g.add(trunk, c1, c2);
      g.position.set(x, 0, z);
      g.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
      zoo.add(g);
    };

    const bush = (x, z, s) => {
      const b = new THREE.Mesh(new THREE.SphereGeometry(0.16 * s, 10, 8), bushMat);
      b.scale.y = 0.7;
      b.position.set(x, 0.1 * s, z);
      b.castShadow = true;
      b.receiveShadow = true;
      zoo.add(b);
    };

    const rock = (x, z, s) => {
      const r = new THREE.Mesh(new THREE.DodecahedronGeometry(0.14 * s), rockMat);
      r.position.set(x, 0.09 * s, z);
      r.rotation.set(Math.random(), Math.random(), Math.random());
      r.castShadow = true;
      r.receiveShadow = true;
      zoo.add(r);
    };

    const flower = (x, z, i) => {
      const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 0.12, 5),
        new THREE.MeshLambertMaterial({ color: 0x4caf50 }));
      stem.position.set(x, 0.06, z);
      const head = new THREE.Mesh(new THREE.SphereGeometry(0.025, 8, 6), flowerMats[i % flowerMats.length]);
      head.position.set(x, 0.13, z);
      zoo.add(stem, head);
    };

    // Деревья по периметру (подальше от панды)
    tree(-1.9, -0.9, 1.2); tree(-2.2, 0.6, 1.0); tree(2.0, -1.1, 1.3);
    tree(2.3, 0.7, 0.9); tree(0.4, -2.2, 1.1); tree(-0.7, 2.1, 1.25);
    bush(-1.5, 0.2, 1.0); bush(1.4, 0.3, 1.2); bush(0.9, -1.6, 0.9); bush(-0.9, -1.7, 1.1);
    bush(1.7, 1.6, 1.0); bush(-1.8, 1.9, 0.8);
    rock(-1.1, 1.2, 1.0); rock(1.2, 1.9, 0.8); rock(2.4, -0.2, 1.1);
    // Пруд
    const pond = new THREE.Mesh(new THREE.CircleGeometry(0.55, 24), pondMat);
    pond.rotateX(-Math.PI / 2);
    pond.position.set(-2.1, 0.006, -1.6);
    zoo.add(pond);
    for (let i = 0; i < 26; i++) {
      const a = (i / 26) * Math.PI * 2;
      const r = 0.9 + (i % 3) * 0.35;
      flower(Math.cos(a) * r, Math.sin(a) * r - 0.2, i);
    }

    this.scene.add(zoo);
    this.zoo = zoo;
  }

  /** Мягкие тени: крупная карта + узкая ортоскопия вокруг панды (без «лесенок»). */
  improveShadows() {
    const cam = this.spotlight.shadow.camera;
    this.spotlight.shadow.mapSize.width = 2048;
    this.spotlight.shadow.mapSize.height = 2048;
    this.spotlight.shadow.radius = 3;
    this.spotlight.shadow.bias = -0.0004;
    this.spotlight.shadow.normalBias = 0.02;
    cam.near = 0.5;
    cam.far = 9;
    cam.left = -1.1;
    cam.right = 1.1;
    cam.top = 1.1;
    cam.bottom = -1.1;
    cam.updateProjectionMatrix();
    for (const light of this.lights || []) {
      if (!light?.shadow || light === this.spotlight) { continue; }
      light.shadow.mapSize.width = 1024;
      light.shadow.mapSize.height = 1024;
    }
  }

  resize() {
    const w = Math.max(1, Math.round(this.container.clientWidth || 1));
    const h = Math.max(1, Math.round(this.container.clientHeight || 1));
    // Без изменений — ничего не делаем: разрываем петлю resize↔scrollbar (дребезг в Edge).
    if (w === this._lastW && h === this._lastH) { return; }
    this._lastW = w;
    this._lastH = h;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    // updateStyle=false: three.js НЕ трогает CSS-размер канваса (он на 100%),
    // меняем только буфер отрисовки — иначе канвас распирает панель и качает макет.
    this.renderer.setSize(w, h, false);
  }

  resetToHome() {
    try {
      this.hideSay();
      if (this.drag) {
        this.drag.physicsObject = null;
        this.drag.active = false;
        if (this.drag.arrow) { this.drag.arrow.visible = false; }
      }
      this.mujoco.mj_resetData(this.model, this.data);
      if (this.model.nkey > HOME_KEYFRAME) {
        const nq = this.model.nq;
        const nu = this.model.nu;
        this.data.qpos.set(this.model.key_qpos.slice(HOME_KEYFRAME * nq, (HOME_KEYFRAME + 1) * nq));
        this.data.ctrl.set(this.model.key_ctrl.slice(HOME_KEYFRAME * nu, (HOME_KEYFRAME + 1) * nu));
      }
      this.data.qvel.fill(0);
      this.data.qfrc_applied.fill(0);
      if (this.player) {
        this.player.stop();
        this.player.enableTorque();
        this.player.relaxLimits(false);
      }
      this.mujoco.mj_forward(this.model, this.data);
    } catch (err) {
      console.error("Сброс не удался:", err);
    }
  }

  setPaused(v) {
    this.paused = v;
  }

  /* ── облачко диалога (как в игре) ─────────────────── */

  /** Показать облачко над головой; само скроется через ms. */
  say(text, ms) {
    const el = document.getElementById("say-bubble");
    if (!el) { return; }
    const clean = String(text ?? "").trim();
    if (!clean) { return; }
    el.textContent = clean;
    el.classList.remove("hidden");
    el.classList.add("show");
    const dur = ms ?? Math.min(4200, 900 + clean.length * 55);
    this.bubbleUntil = performance.now() + dur;
    this.placeBubble();
  }

  hideSay() {
    const el = document.getElementById("say-bubble");
    if (el) { el.classList.add("hidden"); el.classList.remove("show"); }
    this.bubbleUntil = 0;
  }

  /** Точка над головой → экранные координаты контейнера. */
  placeBubble() {
    const el = document.getElementById("say-bubble");
    if (!el || !this.headBody || !this.container) { return; }
    this.headBody.getWorldPosition(this.tmpVec);
    this.tmpVec.y += 0.22;
    const v = this.tmpVec.clone().project(this.camera);
    const w = this.container.clientWidth || 1;
    const h = this.container.clientHeight || 1;
    el.style.left = `${((v.x + 1) / 2) * w}px`;
    el.style.top = `${((-v.y + 1) / 2) * h}px`;
  }

  /** Исполнить программу (массив шагов). */
  play(steps) {
    if (!this.paused && steps && steps.length) {
      this.player.play(steps);
    }
  }

  stopProgram() {
    this.player?.stop();
  }

  /** Живая постановка ТОЧНЫХ углов (таблицы робота): без очереди, короткое сглаживание.
   *  Возвращает зажатый target (для обновления слайдеров редактора). */
  setLiveAngles(angles) {
    if (!this.poseManager || !angles) { return null; }
    const noLimit = this.poseManager.anglesOutOfRange(angles);
    const target = this.poseManager.clampToCtrl(angles, { noLimit });
    this.player.stop();
    this.player.enableTorque();
    this.player.relaxLimits(noLimit);
    this.player.from = Float64Array.from(this.data.ctrl.subarray(0, this.model.nu));
    this.player.to = target;
    this.player.blendStart = this.player.simTime;
    this.player.blendDur = 0.12;
    this.player.running = true;
    this.player.cursor = this.player.steps.length;
    this.player.steps = [];
    this.player.stepDoneAt = this.player.simTime + 0.13;
    return target;
  }

  /** Живая постановка позы из слайдеров: короткое сглаживание, без очереди. */
  setLivePose(normArr) {
    if (!this.poseManager) { return; }
    const target = this.poseManager.normToCtrl(normArr);
    this.player.stop();
    this.player.enableTorque();
    this.player.relaxLimits(false);
    this.player.from = Float64Array.from(this.data.ctrl.subarray(0, this.model.nu));
    this.player.to = target;
    this.player.blendStart = this.player.simTime;
    this.player.blendDur = 0.12;
    this.player.running = true;
    this.player.cursor = this.player.steps.length; // после бленда программа завершится сама
    this.player.steps = [];
    this.player.stepDoneAt = this.player.simTime + 0.13;
  }

  currentNormPose() {
    if (!this.poseManager) { return new Array(12).fill(0.5); }
    return this.poseManager.ctrlToNorm(this.data.ctrl);
  }

  applyDragForce() {
    const dragged = this.drag?.physicsObject;
    if (!dragged || dragged.bodyID !== 1) { return; }
    for (let b = 0; b < this.model.nbody; b++) {
      if (this.bodies[b]) {
        getPosition(this.data.xpos, b, this.bodies[b].position);
        getQuaternion(this.data.xquat, b, this.bodies[b].quaternion);
        this.bodies[b].updateWorldMatrix();
      }
    }
    this.drag.update();
    // Кинематическое перетаскивание: в этом wasm-сборке силы до физики не доходят
    // (mj_applyFT и запись qfrc_applied не двигают тела — проверено), поэтому
    // ведём корпус за мышью телепортом, а ноги продолжают жить в физике.
    const delta = toMujocoPos(this.drag.currentWorld.clone().sub(this.drag.worldHit));
    const k = 0.25;
    this.data.qpos[0] += delta.x * k;
    this.data.qpos[1] += delta.y * k;
    this.data.qpos[2] = Math.max(this.data.qpos[2] + delta.z * k, 0.02);
    this.data.qvel[0] = 0;
    this.data.qvel[1] = 0;
    this.data.qvel[2] = 0;
  }

  applyPausedDrag() {
    const dragged = this.drag?.physicsObject;
    if (!dragged || !dragged.bodyID) { return; }
    const b = dragged.bodyID;
    getPosition(this.data.xpos, b, this.tmpVec, false);
    getQuaternion(this.data.xquat, b, this.tmpQuat, false);
    const offset = toMujocoPos(this.drag.currentWorld.clone().sub(this.drag.worldHit).multiplyScalar(0.3));
    let addr;
    if (this.model.body_mocapid[b] >= 0) {
      addr = this.model.body_mocapid[b] * 3;
      const pos = this.data.mocap_pos;
      pos[addr] += offset.x; pos[addr + 1] += offset.y; pos[addr + 2] += offset.z;
    } else {
      const root = this.model.body_rootid[b];
      addr = this.model.jnt_qposadr[this.model.body_jntadr[root]];
      const pos = this.data.qpos;
      pos[addr] += offset.x; pos[addr + 1] += offset.y; pos[addr + 2] += offset.z;
    }
    this.mujoco.mj_forward(this.model, this.data);
  }

  render(timeMS) {
    this.controls.update();
    if (!this.model) return;

    const mujoco = this.mujoco;
    const timestep = this.model.opt.timestep;

    if (!this.paused) {
      // Если вкладка долго была в фоне — не догоняем всё время разом,
      // но и не сбрасываем часы (иначе на медленных машинах физика встанет).
      const maxCatchUpMs = 100;
      if (timeMS - this.simClockMs > 500) {
        this.simClockMs = timeMS - maxCatchUpMs;
      }
      let guard = 0;
      while (this.simClockMs < timeMS && guard < 500) {
        this.player.tick(timestep);

        // Перетаскивание тела мышью: сброс старых сил, применение новой.
        for (let i = 0; i < this.data.qfrc_applied.length; i++) {
          this.data.qfrc_applied[i] = 0.0;
        }
        this.applyDragForce();

        mujoco.mj_step(this.model, this.data);
        this.simClockMs += timestep * 1000.0;
        guard++;
      }
    } else {
      this.drag?.update();
      this.applyPausedDrag();
    }

    for (let b = 0; b < this.model.nbody; b++) {
      if (this.bodies[b]) {
        getPosition(this.data.xpos, b, this.bodies[b].position);
        getQuaternion(this.data.xquat, b, this.bodies[b].quaternion);
        this.bodies[b].updateWorldMatrix();
      }
    }
    for (let l = 0; l < this.model.nlight; l++) {
      if (this.lights[l]) {
        getPosition(this.data.light_xpos, l, this.lights[l].position);
        getPosition(this.data.light_xdir, l, this.tmpVec);
        this.lights[l].lookAt(this.tmpVec.add(this.lights[l].position));
      }
    }
    if (this.bubbleUntil) {
      if (performance.now() > this.bubbleUntil) { this.hideSay(); }
      else { this.placeBubble(); }
    }
    drawTendonsAndFlex(this.mujocoRoot, this.model, this.data);
    this.renderer.render(this.scene, this.camera);
  }
}
