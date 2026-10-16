# Copyright 2025 DeepMind Technologies Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Asset loading for the vendored rds2p walking subset.

Trimmed to get_assets() only; MJX training environments live in the full
mujoco_playground package and are intentionally not vendored here.
"""

from typing import Any, Dict, Union

from etils import epath

from mujoco_playground._src.locomotion.rds2p import robot_constants as consts


def _update_assets(
    assets: Dict[str, Any],
    path: Union[str, epath.Path],
    glob: str = "*",
    recursive: bool = False,
):
  for f in epath.Path(path).glob(glob):
    if f.is_file():
      assets[f.name] = f.read_bytes()
    elif f.is_dir() and recursive:
      _update_assets(assets, f, glob, recursive)


def get_assets() -> Dict[str, bytes]:
  assets = {}
  _update_assets(assets, consts.ROOT_PATH / "xmls", "*.xml")
  _update_assets(assets, consts.ROOT_PATH / "xmls", "*.mjcf")
  _update_assets(assets, consts.ROOT_PATH / "xmls" / "meshes")
  return assets
