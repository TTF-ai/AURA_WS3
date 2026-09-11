import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    bringup_dir = get_package_share_directory('aura_bringup')
    slam_dir = get_package_share_directory('aura_slam')
    
    # 1. Robot Bringup (RSP, HW bridge, Odom, Lidar)
    robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_dir, 'launch', 'robot.launch.py')
        )
    )

    # 2. SLAM Toolbox
    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(slam_dir, 'launch', 'slam.launch.py')
        )
    )

    return LaunchDescription([
        robot_launch,
        slam_launch
    ])
