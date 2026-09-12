import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    package_dir = get_package_share_directory('aura_exploration')
    params_file = os.path.join(package_dir, 'config', 'frontier_explorer.yaml')

    return LaunchDescription([
        Node(
            package='aura_exploration',
            executable='frontier_explorer',
            name='frontier_explorer',
            output='screen',
            parameters=[params_file],
        ),
    ])