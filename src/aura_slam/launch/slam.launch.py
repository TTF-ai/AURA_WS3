import os
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg_dir = get_package_share_directory('aura_slam')
    params_file = os.path.join(pkg_dir, 'config', 'slam_toolbox.yaml')

    slam_toolbox = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[params_file, {'use_sim_time': False}]
    )

    return LaunchDescription([
        slam_toolbox
    ])
