from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'aura_voice'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='thirumalesh',
    maintainer_email='thirumaleshk549@gmail.com',
    description='AURA Multilingual Voice Interaction (STT + LLM + TTS)',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'voice_node = aura_voice.voice_node:main',
        ],
    },
)
