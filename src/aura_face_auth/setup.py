import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'aura_face_auth'

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
    description='AURA face authentication subsystem for ROS 2',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            "camera_node = aura_face_auth.camera_node:main",
            "face_detector_node = aura_face_auth.face_detector_node:main",
            "recognizer_node = aura_face_auth.recognizer_node:main",
            "liveness_node = aura_face_auth.liveness_node:main",
            "auth_node = aura_face_auth.auth_node:main",
            "enroll_node = aura_face_auth.enroll_node:main",
        ],
    },
)
