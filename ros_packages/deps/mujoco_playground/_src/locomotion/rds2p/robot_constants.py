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
"""Defines Unitree Go1 quadruped constants."""

from etils import epath

ROOT_PATH = epath.Path(__file__).parent
FEET_ONLY_FLAT_TERRAIN_XML = (
    ROOT_PATH / "xmls" / "scene_feetonly.mjcf"
)
FEET_ONLY_ROUGH_TERRAIN_XML = (
    ROOT_PATH / "xmls" / "scene_feetonly.mjcf"
)
FULL_FLAT_TERRAIN_XML = (
    ROOT_PATH / "xmls" / "scene_feetonly.xml"
)
FULL_COLLISIONS_FLAT_TERRAIN_XML = (
    ROOT_PATH / "xmls" / "scene_feetonly.mjcf"
)


def task_to_xml(task_name: str) -> epath.Path:
  return {
      "flat_terrain": FEET_ONLY_FLAT_TERRAIN_XML,
      "rough_terrain": FEET_ONLY_ROUGH_TERRAIN_XML,
  }[task_name]


FEET_SITES = [
    "foot_fl_site",
    "foot_fr_site",
    "foot_bl_site",
    "foot_br_site",
]

FEET_GEOMS = [
    "foot_fl_link_collision",
    "foot_fr_link_collision",
    "foot_bl_link_collision",
    "foot_br_link_collision",
]

FEET_POS_SENSOR = [f"{site}_pos" for site in FEET_SITES]

ROOT_BODY = "base_link"

UPVECTOR_SENSOR = "base_link_site_upvector"
GLOBAL_LINVEL_SENSOR = "base_link_site_global_linvel"
GLOBAL_ANGVEL_SENSOR = "base_link_site_global_angvel"
LOCAL_LINVEL_SENSOR = "base_link_site_vel"
ACCELEROMETER_SENSOR = "base_link_acc"
GYRO_SENSOR = "base_link_gyro"
