from setuptools import setup
from glob import glob
import os

package_name = 'rds_2p_dance'

setup(
    name=package_name,
    version='0.0.0',
    packages=[],
    data_files=[
        ('share/' + package_name, ['package.xml']),
        # Устанавливаем папку animations
        (os.path.join('share', package_name, 'animations'),
            glob('animations/*.csv')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ubuntu',
    maintainer_email='zhuravlev.p.r@edu.mirea.ru',
    description='ROS2 пакет для проигрывания танцев робота RDS-2P через Action сервер',
    license='MIT',
    tests_require=['pytest'],
)

