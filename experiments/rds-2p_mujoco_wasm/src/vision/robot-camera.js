
import * as THREE from "three";

const CAMERA_CONFIG = {
  name: "camera",
  width: 640,
  height: 480,
  fov: 90,
  near: 0.001,
  far: 100,
  position: [0.152412, 0.002539, 0.004207],

  // MuJoCo MJCF quaternion: w, x, y, z.
  quaternion: [-0.5, -0.5, 0.5, 0.5],
};

/**
 * Создаёт камеру в локальной системе base_link.
 *
 * S = поворот системы координат MJCF -> Three.js на -90°
 * вокруг X.
 *
 * Для камеры используется умножение S * R_camera,
 * поскольку локальная камера Three.js смотрит вдоль -Z.
 */
export function createRobotVisionCamera(sim) {
  const baseBody = Object.values(sim.bodies).find(
    (body) => body?.name === "base_link"
  );

  if (!baseBody) {
    throw new Error("Не найдено тело base_link в MuJoCo-сцене");
  }

  const config = CAMERA_CONFIG;

  const camera = new THREE.PerspectiveCamera(
    config.fov,
    config.width / config.height,
    config.near,
    config.far
  );

  camera.name = "robot-vision-camera";

  // MJCF (x,y,z) -> Three.js (x,z,-y).
  camera.position.set(
    config.position[0],
    config.position[2],
    -config.position[1]
  );

  const [w, x, y, z] = config.quaternion;

  const mjcfRotation = new THREE.Quaternion(x, y, z, w);

  const basisRotation = new THREE.Quaternion(
    -Math.SQRT1_2,
    0,
    0,
    Math.SQRT1_2
  );

  camera.quaternion
    .copy(basisRotation)
    .multiply(mjcfRotation)
    .normalize();

  baseBody.add(camera);
  camera.updateProjectionMatrix();

  return camera;
}
