import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'aura_sem_map'

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
        (os.path.join('lib', package_name),
            ['aura_sem_map/semantic_mapper']),
    ],
    install_requires=['setuptools', 'ultralytics>=8.0.0'],
    zip_safe=True,
    maintainer='thirumalesh',
    maintainer_email='thirumaleshk549@gmail.com',
    description='AURA semantic mapping prototype',
    license='Apache-2.0',
    extras_require={
        'test': ['pytest'],
    },
    entry_points={
        'console_scripts': [
            'semantic_mapper = aura_sem_map.semantic_mapper:main',
        ],
    },
)
