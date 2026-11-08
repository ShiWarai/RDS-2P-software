"""Regenerate the bundled shin collision compound (offline authoring only).
Requires numpy and coacd==1.0.14. Browser/runtime installation is unnecessary.
Usage: python tools/generate_shin_collisions.py
All four source shin meshes have identical vertices in their mesh frames.
"""
from pathlib import Path
import argparse
import numpy as np
import coacd

ROOT = Path(__file__).resolve().parents[1]

def generate(source: Path, output: Path):
    vertices, polygons = [], []
    for line in source.read_text(encoding='utf-8').splitlines():
        if line.startswith('v '):
            vertices.append([float(x) for x in line.split()[1:4]])
        elif line.startswith('f '):
            polygons.append([int(x.split('/')[0]) - 1 for x in line.split()[1:]])
    points = np.asarray(vertices)
    parents = list(range(len(vertices)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for polygon in polygons:
        for i in polygon[1:]:
            parents[find(i)] = find(polygon[0])
    # Weld duplicated positions along normal/UV seams before finding components.
    seen = {}
    for i, point in enumerate(vertices):
        key = tuple(point)
        if key in seen:
            parents[find(i)] = find(seen[key])
        else:
            seen[key] = i
    components = {}
    for i in range(len(vertices)):
        components.setdefault(find(i), []).append(i)
    # The longest component is the load-bearing frame. Tiny screw heads remain
    # in the visual mesh; they need not become separate collision obstacles.
    frame = max(components.values(), key=lambda ids: np.linalg.norm(points[ids].max(0) - points[ids].min(0)))
    keep = set(frame)
    triangles = []
    for polygon in polygons:
        if polygon[0] in keep:
            triangles.extend([[polygon[0], polygon[k], polygon[k + 1]] for k in range(1, len(polygon) - 1)])
    used = np.array(sorted({i for face in triangles for i in face}))
    remap = {old: new for new, old in enumerate(used)}
    points = points[used]
    triangles = np.array([[remap[i] for i in face] for face in triangles], dtype=np.int32)
    points, inverse = np.unique(points, axis=0, return_inverse=True)
    triangles = inverse[triangles]
    triangles = triangles[(triangles[:, 0] != triangles[:, 1]) &
                          (triangles[:, 1] != triangles[:, 2]) & (triangles[:, 0] != triangles[:, 2])]
    coacd.set_log_level('warn')
    parts = coacd.run_coacd(coacd.Mesh(points, triangles), threshold=0.03, max_convex_hull=16,
        preprocess_resolution=60, resolution=2000, mcts_nodes=10, mcts_iterations=60,
        mcts_max_depth=3, decimate=True, max_ch_vertex=64, seed=1)
    if len(parts) != 16:
        raise RuntimeError(f'Expected 16 parts for the bundled MJCF/loader; got {len(parts)}')
    output.mkdir(parents=True, exist_ok=True)
    for i, (points, faces) in enumerate(parts):
        content = ''.join('v %.9f %.9f %.9f\n' % tuple(v) for v in points)
        content += ''.join('f %d %d %d\n' % tuple(f + 1) for f in faces)
        (output / f'shin_collision_{i:02d}.obj').write_text(content, encoding='ascii')
    print(f'Wrote {len(parts)} convex frame pieces to {output}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / '../../urdf_src/export/rds-2p/meshes/obj/shin_fl.obj')
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/scenes/meshes')
    args = parser.parse_args()
    generate(args.source, args.output)
