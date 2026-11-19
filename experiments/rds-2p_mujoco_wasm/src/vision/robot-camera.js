
import * as THREE from "three";
import { ASTRA_MINI_PRO, DEPTH_RANGE } from "./astra-mini-pro.js";

export const CAMERA_CONFIG = {
  name: "camera",
  width: ASTRA_MINI_PRO.width,
  height: ASTRA_MINI_PRO.height,
  fov: ASTRA_MINI_PRO.rgb.verticalFov,
  horizontalFov: ASTRA_MINI_PRO.rgb.horizontalFov,
  near: 0.001,
  far: 100,
  position: [0.152412, 0.002539, 0.004207],

  // MuJoCo MJCF quaternion: w, x, y, z.
  quaternion: [-0.5, -0.5, 0.5, 0.5],
};

export const DEPTH_CAMERA_CONFIG = {
  ...CAMERA_CONFIG,
  fov: ASTRA_MINI_PRO.depth.verticalFov,
  horizontalFov: ASTRA_MINI_PRO.depth.horizontalFov,
  // Render close occluders too; range filtering happens after readback.
  // Keep the near plane positive for perspective projection, and the far
  // plane beyond the working range so exactly 2 m remains measurable.
  near: 0.001,
  far: DEPTH_RANGE.max + 1,
};

class SensorCamera extends THREE.PerspectiveCamera {
  updateProjectionMatrix() {
    super.updateProjectionMatrix();
    if (this.horizontalFov) {
      // The published H/V angles are independent of the 4:3 pixel aspect.
      this.projectionMatrix.elements[0] = 1 / Math.tan(THREE.MathUtils.degToRad(this.horizontalFov / 2));
      this.projectionMatrixInverse.copy(this.projectionMatrix).invert();
    }
  }
}

/**
 * Создаёт камеру в локальной системе base_link.
 *
 * S = поворот системы координат MJCF -> Three.js на -90°
 * вокруг X.
 *
 * Для камеры используется умножение S * R_camera,
 * поскольку локальная камера Three.js смотрит вдоль -Z.
 */
export function createRobotVisionCamera(sim, config = CAMERA_CONFIG) {
  const baseBody = Object.values(sim.bodies).find(
    (body) => body?.name === "base_link"
  );

  if (!baseBody) {
    throw new Error("Не найдено тело base_link в MuJoCo-сцене");
  }

  const camera = new SensorCamera(
    config.fov,
    config.width / config.height,
    config.near,
    config.far
  );
  camera.horizontalFov = config.horizontalFov;

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
