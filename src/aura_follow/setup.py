import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'aura_follow'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'),
            glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='thirumalesh',
    maintainer_email='thirumaleshk549@gmail.com',
    description='AURA human-following subsystem for ROS 2',
    license='Apache-2.0',
    extras_require={
        'test': ['pytest'],
    },
    entry_points={
        'console_scripts': [
            "human_follow_node = aura_follow.human_follow_node:main",
        ],
    },
)
