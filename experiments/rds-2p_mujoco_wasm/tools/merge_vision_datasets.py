#!/usr/bin/env python3
"""Merge labelled splits without moving any image between train/val/test."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from ultralytics.utils import YAML

NAMES = ['tree', 'bush', 'rock', 'flower', 'blue_ball', 'red_ball', 'green_ball']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if (root/'data.yaml').exists():
        raise ValueError('Choose a fresh combined dataset directory')
    hashes, names, sources = {}, set(), []
    counts = dict.fromkeys(['train', 'val', 'test'], 0)
    for dataset in args.dataset:
        dataset = dataset.resolve()
        if YAML.load(str(dataset/'data.yaml'))['names'] != NAMES:
            raise ValueError(f'Wrong class order in {dataset}')
        sources.append(json.loads((dataset/'provenance.json').read_text()))
        for split in counts:
            for image in sorted((dataset/'images'/split).glob('*.jpg')):
                if image.name in names:
                    raise ValueError(f'Duplicate image name: {image.name}')
                digest = hashlib.sha256(image.read_bytes()).hexdigest()
                if digest in hashes and hashes[digest] != split:
                    raise ValueError(f'Image content leaks between splits: {image}')
                hashes[digest] = split
                names.add(image.name)
                label = dataset/'labels'/split/image.with_suffix('.txt').name
                for kind, source in [('images', image), ('labels', label)]:
                    target = root/kind/split/source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                counts[split] += 1
    (root/'data.yaml').write_text('path: '+root.as_posix()+'\ntrain: images/train\nval: images/val\ntest: images/test\nnames: '+json.dumps(NAMES)+'\n', encoding='utf-8')
    provenance = dict(sources=sources, split_images=counts,
                      labels='; '.join(dict.fromkeys(source.get('labels','unspecified') for source in sources)),
                      split_integrity='Original split membership preserved; duplicate image names and cross-split image hashes rejected.')
    (root/'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    print(root, counts, flush=True)


if __name__ == '__main__':
    main()
