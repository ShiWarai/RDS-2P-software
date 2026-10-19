import * as THREE from 'three';

/**
 * Адаптированная версия утилит из experiments/wasm_demo:
 *  - loadSceneFromURL  — построение three.js-сцены по модели MuJoCo;
 *  - downloadSceneFolder — загрузка сцены и мешей в Emscripten FS;
 *  - getPosition / getQuaternion / toMujocoPos — свизл Z-up → Y-up.
 * Убраны lil-gui и перетаскивание тел — вместо них панели приложения.
 */

export async function downloadSceneFolder(mujoco, urlBase = "./assets/scenes/") {
  const allFiles = [
    "rds2p_feetonly_scene.xml",
    "rds-2p_feetonly.mjcf",
    "meshes/base.obj",
    "meshes/hip_bl.obj",
    "meshes/hip_br.obj",
    "meshes/hip_fl.obj",
    "meshes/hip_fr.obj",
    "meshes/leg_block_bl.obj",
    "meshes/leg_block_br.obj",
    "meshes/leg_block_fl.obj",
    "meshes/leg_block_fr.obj",
    "meshes/panda_visual.obj",
    "meshes/shin_bl.obj",
    "meshes/shin_br.obj",
    "meshes/shin_fl.obj",
    "meshes/shin_fr.obj",
  ];

  const responses = await Promise.all(allFiles.map((f) => fetch(urlBase + f)));
  for (let i = 0; i < responses.length; i++) {
    if (!responses[i].ok) {
      throw new Error(`Не удалось загрузить ${allFiles[i]}: HTTP ${responses[i].status}`);
    }
    let working = "/working/";
    const parts = allFiles[i].split("/");
    for (let d = 0; d < parts.length - 1; d++) {
      working += parts[d];
      if (!mujoco.FS.analyzePath(working).exists) {
        mujoco.FS.mkdir(working);
      }
      working += "/";
    }
    mujoco.FS.writeFile("/working/" + allFiles[i], await responses[i].text());
  }
}

export async function loadSceneFromURL(mujoco, filename, parent) {
  if (parent.data != null) {
    parent.data.delete();
    parent.model = null;
    parent.data = null;
  }

  parent.model = mujoco.MjModel.loadFromXML("/working/" + filename);
  parent.data = new mujoco.MjData(parent.model);

  const model = parent.model;
  const data = parent.data;

  const textDecoder = new TextDecoder("utf-8");
  const names_array = new Uint8Array(model.names);
  const fullString = textDecoder.decode(model.names);
  const names = fullString.split(textDecoder.decode(new ArrayBuffer(1)));

  const mujocoRoot = new THREE.Group();
  mujocoRoot.name = "MuJoCo Root";
  parent.scene.add(mujocoRoot);

  /** @type {Object.<number, THREE.Group>} */
  const bodies = {};
  /** @type {Object.<number, THREE.BufferGeometry>} */
  const meshes = {};
  /** @type {THREE.Light[]} */
  const lights = [];

  for (let g = 0; g < model.ngeom; g++) {
    if (!(model.geom_group[g] < 3)) { continue; }

    const b = model.geom_bodyid[g];
    const type = model.geom_type[g];
    const size = [
      model.geom_size[(g * 3) + 0],
      model.geom_size[(g * 3) + 1],
      model.geom_size[(g * 3) + 2],
    ];

    if (!(b in bodies)) {
      bodies[b] = new THREE.Group();
      const start_idx = model.name_bodyadr[b];
      let end_idx = start_idx;
      while (end_idx < names_array.length && names_array[end_idx] !== 0) { end_idx++; }
      bodies[b].name = textDecoder.decode(names_array.subarray(start_idx, end_idx));
      bodies[b].bodyID = b;
      bodies[b].has_custom_mesh = false;
    }

    let geometry = new THREE.SphereGeometry(size[0] * 0.5);
    if (type == mujoco.mjtGeom.mjGEOM_PLANE.value) {
      // plane — спец-обработка ниже
    } else if (type == mujoco.mjtGeom.mjGEOM_SPHERE.value) {
      geometry = new THREE.SphereGeometry(size[0]);
    } else if (type == mujoco.mjtGeom.mjGEOM_CAPSULE.value) {
      geometry = new THREE.CapsuleGeometry(size[0], size[1] * 2.0, 20, 20);
    } else if (type == mujoco.mjtGeom.mjGEOM_ELLIPSOID.value) {
      geometry = new THREE.SphereGeometry(1);
    } else if (type == mujoco.mjtGeom.mjGEOM_CYLINDER.value) {
      geometry = new THREE.CylinderGeometry(size[0], size[0], size[1] * 2.0);
    } else if (type == mujoco.mjtGeom.mjGEOM_BOX.value) {
      geometry = new THREE.BoxGeometry(size[0] * 2.0, size[2] * 2.0, size[1] * 2.0);
    } else if (type == mujoco.mjtGeom.mjGEOM_MESH.value) {
      const meshID = model.geom_dataid[g];
      if (!(meshID in meshes)) {
        geometry = new THREE.BufferGeometry();

        const vertex_buffer = model.mesh_vert.subarray(
          model.mesh_vertadr[meshID] * 3,
          (model.mesh_vertadr[meshID] + model.mesh_vertnum[meshID]) * 3);
        for (let v = 0; v < vertex_buffer.length; v += 3) {
          const temp = vertex_buffer[v + 1];
          vertex_buffer[v + 1] = vertex_buffer[v + 2];
          vertex_buffer[v + 2] = -temp;
        }

        const normal_buffer = model.mesh_normal.subarray(
          model.mesh_normaladr[meshID] * 3,
          (model.mesh_normaladr[meshID] + model.mesh_normalnum[meshID]) * 3);
        for (let v = 0; v < normal_buffer.length; v += 3) {
          const temp = normal_buffer[v + 1];
          normal_buffer[v + 1] = normal_buffer[v + 2];
          normal_buffer[v + 2] = -temp;
        }

        const uv_buffer = model.mesh_texcoord.subarray(
          model.mesh_texcoordadr[meshID] * 2,
          (model.mesh_texcoordadr[meshID] + model.mesh_texcoordnum[meshID]) * 2);

        const face_to_vertex_buffer = model.mesh_face.subarray(
          model.mesh_faceadr[meshID] * 3,
          (model.mesh_faceadr[meshID] + model.mesh_facenum[meshID]) * 3);
        const face_to_uv_buffer = model.mesh_facetexcoord.subarray(
          model.mesh_faceadr[meshID] * 3,
          (model.mesh_faceadr[meshID] + model.mesh_facenum[meshID]) * 3);
        const face_to_normal_buffer = model.mesh_facenormal.subarray(
          model.mesh_faceadr[meshID] * 3,
          (model.mesh_faceadr[meshID] + model.mesh_facenum[meshID]) * 3);

        const swizzled_uv_buffer = new Float32Array((vertex_buffer.length / 3) * 2);
        const swizzled_normal_buffer = new Float32Array(vertex_buffer.length);
        for (let t = 0; t < face_to_vertex_buffer.length / 3; t++) {
          const vi0 = face_to_vertex_buffer[(t * 3) + 0];
          const vi1 = face_to_vertex_buffer[(t * 3) + 1];
          const vi2 = face_to_vertex_buffer[(t * 3) + 2];
          const uvi0 = face_to_uv_buffer[(t * 3) + 0];
          const uvi1 = face_to_uv_buffer[(t * 3) + 1];
          const uvi2 = face_to_uv_buffer[(t * 3) + 2];
          const nvi0 = face_to_normal_buffer[(t * 3) + 0];
          const nvi1 = face_to_normal_buffer[(t * 3) + 1];
          const nvi2 = face_to_normal_buffer[(t * 3) + 2];
          swizzled_uv_buffer[(vi0 * 2) + 0] = uv_buffer[(uvi0 * 2) + 0];
          swizzled_uv_buffer[(vi0 * 2) + 1] = uv_buffer[(uvi0 * 2) + 1];
          swizzled_uv_buffer[(vi1 * 2) + 0] = uv_buffer[(uvi1 * 2) + 0];
          swizzled_uv_buffer[(vi1 * 2) + 1] = uv_buffer[(uvi1 * 2) + 1];
          swizzled_uv_buffer[(vi2 * 2) + 0] = uv_buffer[(uvi2 * 2) + 0];
          swizzled_uv_buffer[(vi2 * 2) + 1] = uv_buffer[(uvi2 * 2) + 1];
          swizzled_normal_buffer[(vi0 * 3) + 0] = normal_buffer[(nvi0 * 3) + 0];
          swizzled_normal_buffer[(vi0 * 3) + 1] = normal_buffer[(nvi0 * 3) + 1];
          swizzled_normal_buffer[(vi0 * 3) + 2] = normal_buffer[(nvi0 * 3) + 2];
          swizzled_normal_buffer[(vi1 * 3) + 0] = normal_buffer[(nvi1 * 3) + 0];
          swizzled_normal_buffer[(vi1 * 3) + 1] = normal_buffer[(nvi1 * 3) + 1];
          swizzled_normal_buffer[(vi1 * 3) + 2] = normal_buffer[(nvi1 * 3) + 2];
          swizzled_normal_buffer[(vi2 * 3) + 0] = normal_buffer[(nvi2 * 3) + 0];
          swizzled_normal_buffer[(vi2 * 3) + 1] = normal_buffer[(nvi2 * 3) + 1];
          swizzled_normal_buffer[(vi2 * 3) + 2] = normal_buffer[(nvi2 * 3) + 2];
        }
        geometry.setAttribute("position", new THREE.BufferAttribute(vertex_buffer, 3));
        geometry.setAttribute("normal", new THREE.BufferAttribute(swizzled_normal_buffer, 3));
        geometry.setAttribute("uv", new THREE.BufferAttribute(swizzled_uv_buffer, 2));
        geometry.setIndex(Array.from(face_to_vertex_buffer));
        geometry.computeVertexNormals();
        meshes[meshID] = geometry;
      } else {
        geometry = meshes[meshID];
      }
      bodies[b].has_custom_mesh = true;
    }

    let texture = undefined;
    const color = [
      model.geom_rgba[(g * 4) + 0],
      model.geom_rgba[(g * 4) + 1],
      model.geom_rgba[(g * 4) + 2],
      model.geom_rgba[(g * 4) + 3],
    ];
    if (model.geom_matid[g] != -1) {
      const matId = model.geom_matid[g];
      color[0] = model.mat_rgba[(matId * 4) + 0];
      color[1] = model.mat_rgba[(matId * 4) + 1];
      color[2] = model.mat_rgba[(matId * 4) + 2];
      color[3] = model.mat_rgba[(matId * 4) + 3];

      const mjNTEXROLE = 10;
      const mjTEXROLE_RGB = 1;
      const texId = model.mat_texid[(matId * mjNTEXROLE) + mjTEXROLE_RGB];
      if (texId != -1) {
        const width = model.tex_width[texId];
        const height = model.tex_height[texId];
        const offset = model.tex_adr[texId];
        const channels = model.tex_nchannel[texId];
        const texData = model.tex_data;
        const rgbaArray = new Uint8Array(width * height * 4);
        for (let p = 0; p < width * height; p++) {
          rgbaArray[(p * 4) + 0] = texData[offset + ((p * channels) + 0)];
          rgbaArray[(p * 4) + 1] = channels > 1 ? texData[offset + ((p * channels) + 1)] : rgbaArray[(p * 4) + 0];
          rgbaArray[(p * 4) + 2] = channels > 2 ? texData[offset + ((p * channels) + 2)] : rgbaArray[(p * 4) + 0];
          rgbaArray[(p * 4) + 3] = channels > 3 ? texData[offset + ((p * channels) + 3)] : 255;
        }
        texture = new THREE.DataTexture(rgbaArray, width, height, THREE.RGBAFormat, THREE.UnsignedByteType);
        if (texId == 2) {
          texture.repeat = new THREE.Vector2(50, 50);
        } else {
          texture.repeat = new THREE.Vector2(
            model.mat_texrepeat[(model.geom_matid[g] * 2) + 0],
            model.mat_texrepeat[(model.geom_matid[g] * 2) + 1]);
        }
        texture.wrapS = THREE.RepeatWrapping;
        texture.wrapT = THREE.RepeatWrapping;
        texture.needsUpdate = true;
      }
    }

    const mat = { color: new THREE.Color(color[0], color[1], color[2]), transparent: color[3] < 1.0, opacity: color[3] / 255.0 };
    if (model.geom_matid[g] != -1) {
      mat.specularIntensity = model.mat_specular[model.geom_matid[g]];
      mat.reflectivity = model.mat_reflectance[model.geom_matid[g]];
      mat.roughness = 1.0 - model.mat_shininess[model.geom_matid[g]];
      mat.metalness = 0.1;
      if (texture) { mat.map = texture; }
    }
    const currentMaterial = new THREE.MeshPhysicalMaterial(mat);

    let mesh;
    if (type == 0) {
      mesh = new THREE.Mesh(new THREE.PlaneGeometry(100, 100), currentMaterial);
      mesh.rotateX(-Math.PI / 2);
    } else {
      mesh = new THREE.Mesh(geometry, currentMaterial);
    }
    mesh.castShadow = g == 0 ? false : true;
    mesh.receiveShadow = type != 7;
    mesh.bodyID = b;
    bodies[b].add(mesh);
    getPosition(model.geom_pos, g, mesh.position);
    if (type != 0) { getQuaternion(model.geom_quat, g, mesh.quaternion); }
    if (type == 4) { mesh.scale.set(size[0], size[2], size[1]); }
  }

  const tendonMat = new THREE.MeshPhongMaterial();
  tendonMat.color = new THREE.Color(0.8, 0.3, 0.3);
  mujocoRoot.cylinders = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 1), tendonMat, 1023);
  mujocoRoot.cylinders.receiveShadow = true;
  mujocoRoot.cylinders.castShadow = true;
  mujocoRoot.add(mujocoRoot.cylinders);
  mujocoRoot.spheres = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 10, 10), tendonMat, 1023);
  mujocoRoot.spheres.receiveShadow = true;
  mujocoRoot.spheres.castShadow = true;
  mujocoRoot.add(mujocoRoot.spheres);

  for (let l = 0; l < model.nlight; l++) {
    let light;
    if (model.light_type[l] == 0) {
      light = new THREE.SpotLight();
      light.angle = 1.51;
    } else if (model.light_type[l] == 1) {
      light = new THREE.DirectionalLight();
    } else if (model.light_type[l] == 2) {
      light = new THREE.PointLight();
    } else {
      light = new THREE.HemisphereLight();
    }
    light.angle = 1.11;
    light.decay = model.light_attenuation[l] * 100;
    light.penumbra = 0.5;
    light.castShadow = true;
    light.intensity = light.intensity * 3.14 * 1.0;
    light.shadow.mapSize.width = 1024;
    light.shadow.mapSize.height = 1024;
    light.shadow.camera.near = 0.1;
    light.shadow.camera.far = 10;
    if (bodies[0]) { bodies[0].add(light); } else { mujocoRoot.add(light); }
    lights.push(light);
  }
  if (model.nlight == 0) {
    const light = new THREE.DirectionalLight();
    mujocoRoot.add(light);
  }

  for (let b = 0; b < model.nbody; b++) {
    if (b == 0 || !bodies[0]) {
      mujocoRoot.add(bodies[b]);
    } else if (bodies[b]) {
      bodies[0].add(bodies[b]);
    } else {
      bodies[b] = new THREE.Group();
      bodies[b].name = names[b + 1];
      bodies[b].bodyID = b;
      bodies[b].has_custom_mesh = false;
      bodies[0].add(bodies[b]);
    }
  }

  parent.mujocoRoot = mujocoRoot;

  return [model, data, bodies, lights];
}

export function drawTendonsAndFlex(mujocoRoot, model, data) {
  const identityQuat = new THREE.Quaternion();
  let numWraps = 0;
  if (mujocoRoot && mujocoRoot.cylinders) {
    const mat = new THREE.Matrix4();
    for (let t = 0; t < model.ntendon; t++) {
      const startW = data.ten_wrapadr[t];
      const r = model.tendon_width[t];
      for (let w = startW; w < startW + data.ten_wrapnum[t] - 1; w++) {
        const tendonStart = getPosition(data.wrap_xpos, w, new THREE.Vector3());
        const tendonEnd = getPosition(data.wrap_xpos, w + 1, new THREE.Vector3());
        const tendonAvg = new THREE.Vector3().addVectors(tendonStart, tendonEnd).multiplyScalar(0.5);

        const validStart = tendonStart.length() > 0.01;
        const validEnd = tendonEnd.length() > 0.01;

        if (validStart) { mujocoRoot.spheres.setMatrixAt(numWraps, mat.compose(tendonStart, identityQuat, new THREE.Vector3(r, r, r))); }
        if (validEnd) { mujocoRoot.spheres.setMatrixAt(numWraps + 1, mat.compose(tendonEnd, identityQuat, new THREE.Vector3(r, r, r))); }
        if (validStart && validEnd) {
          mat.compose(tendonAvg, identityQuat.setFromUnitVectors(
            new THREE.Vector3(0, 1, 0), tendonEnd.clone().sub(tendonStart).normalize()),
            new THREE.Vector3(r, tendonStart.distanceTo(tendonEnd), r));
          mujocoRoot.cylinders.setMatrixAt(numWraps, mat);
          numWraps++;
        }
      }
    }

    let curFlexSphereInd = numWraps;
    const tempvertPos = new THREE.Vector3();
    const tempvertRad = new THREE.Vector3();
    for (let i = 0; i < model.nflex; i++) {
      for (let j = 0; j < model.flex_vertnum[i]; j++) {
        const vertIndex = model.flex_vertadr[i] + j;
        getPosition(data.flexvert_xpos, vertIndex, tempvertPos);
        const r = 0.01;
        mat.compose(tempvertPos, identityQuat, tempvertRad.set(r, r, r));
        mujocoRoot.spheres.setMatrixAt(curFlexSphereInd, mat);
        curFlexSphereInd++;
      }
    }
    mujocoRoot.cylinders.count = numWraps;
    mujocoRoot.spheres.count = curFlexSphereInd;
    mujocoRoot.cylinders.instanceMatrix.needsUpdate = true;
    mujocoRoot.spheres.instanceMatrix.needsUpdate = true;
  }
}

export function getPosition(buffer, index, target, swizzle = true) {
  if (swizzle) {
    return target.set(
      buffer[(index * 3) + 0],
      buffer[(index * 3) + 2],
      -buffer[(index * 3) + 1]);
  }
  return target.set(
    buffer[(index * 3) + 0],
    buffer[(index * 3) + 1],
    buffer[(index * 3) + 2]);
}

export function getQuaternion(buffer, index, target, swizzle = true) {
  if (swizzle) {
    return target.set(
      -buffer[(index * 4) + 1],
      -buffer[(index * 4) + 3],
      buffer[(index * 4) + 2],
      -buffer[(index * 4) + 0]);
  }
  return target.set(
    buffer[(index * 4) + 0],
    buffer[(index * 4) + 1],
    buffer[(index * 4) + 2],
    buffer[(index * 4) + 3]);
}

export function toMujocoPos(target) { return target.set(target.x, -target.z, target.y); }
