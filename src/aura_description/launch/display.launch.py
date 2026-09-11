"""
Launch robot_state_publisher with the AURA URDF.

Publishes /robot_description and all static TFs defined in the URDF:
  base_link -> chassis_link
  base_link -> wheel_fl_link, wheel_fr_link, wheel_rl_link, wheel_rr_link
  base_link -> imu_link
  base_link -> laser_link

Does NOT publish odom -> base_link (that is owned by aura_odom/wheel_odom).
"""

import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.substitutions import Command
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    pkg_share = get_package_share_directory('aura_description')
    xacro_file = os.path.join(pkg_share, 'urdf', 'aura.urdf.xacro')

    robot_description = Command(['xacro ', xacro_file])

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_description,
            'publish_frequency': 30.0,
        }],
    )

    return LaunchDescription([
        robot_state_publisher,
    ])
