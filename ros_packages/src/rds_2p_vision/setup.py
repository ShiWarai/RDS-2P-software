from glob import glob
from setuptools import find_packages, setup

setup(name='rds_2p_vision', version='0.1.0', packages=find_packages(),
      data_files=[('share/ament_index/resource_index/packages', ['resource/rds_2p_vision']),
                  ('share/rds_2p_vision', ['package.xml']),
                  ('share/rds_2p_vision/launch', glob('launch/*.py')),
                  ('share/rds_2p_vision/config', glob('config/*.yaml')),
                  ('share/rds_2p_vision/models', glob('models/*'))],
      install_requires=['setuptools'], zip_safe=True,
      entry_points={'console_scripts': ['ball_follow = rds_2p_vision.ball_follow_node:main']})
