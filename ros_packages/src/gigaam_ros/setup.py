from setuptools import setup
import os
from glob import glob

package_name = 'gigaam_ros'


def get_model_files():
    model_files = []
    model_dir = 'models'
    if os.path.exists(model_dir):
        for root, dirs, files in os.walk(model_dir):
            for file in files:
                model_files.append(os.path.join(root, file))
    return model_files


setup(
    name=package_name,
    version='0.1.0',
    packages=[],
    py_modules=['gigaam_node', 'vad_node', 'rknn_engine'],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ] + [(os.path.join('share', package_name, os.path.dirname(f)), [f]) for f in get_model_files()],
    install_requires=['setuptools', 'numpy', 'torch', 'torchaudio'],
    zip_safe=True,
    maintainer='Zhuravliov Pavel',
    maintainer_email='zhuravliov.pav@yandex.ru',
    description='ROS2 package for GigaAM CTC speech recognition (RKNN / RK3588 NPU)',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'gigaam_node = gigaam_node:main',
            'vad_node = vad_node:main',
        ],
    },
)
