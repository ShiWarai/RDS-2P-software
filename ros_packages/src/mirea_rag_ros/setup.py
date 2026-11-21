import glob
import os

from setuptools import setup

package_name = "mirea_rag_ros"

setup(
    name=package_name,
    version="0.2.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages",
         ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch",
         glob.glob(os.path.join("launch", "*.launch.py"))),
        ("share/" + package_name + "/config",
         glob.glob(os.path.join("config", "*"))),
        ("share/" + package_name + "/bundle",
         glob.glob(os.path.join("bundle", "*"))),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ubuntu",
    maintainer_email="ubuntu@todo.todo",
    description="Голосовой RAG-помощник РТУ МИРЭА для робота-панды: "
                "транскрипция → RAG → TTS.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "mirea_rag_node = mirea_rag_ros.mirea_rag_node:main",
        ],
    },
)
