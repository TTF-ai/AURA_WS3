import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    package_dir = get_package_share_directory('aura_sem_map')
    param_file = os.path.join(package_dir, 'config', 'semantic_map_params.yaml')

    return LaunchDescription([
        Node(
            package='aura_sem_map',
            executable='semantic_mapper',
            name='semantic_mapper',
            output='screen',
            parameters=[param_file],
        )
    ])
