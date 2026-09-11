import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node, LifecycleNode
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    bringup_dir = get_package_share_directory('aura_bringup')
    description_dir = get_package_share_directory('aura_description')
    
    # 1. Robot State Publisher (URDF + Static TFs)
    display_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(description_dir, 'launch', 'display.launch.py')
        )
    )

    # 2. ESP32 Bridge
    esp32_bridge = Node(
        package='aura_robot_hw',
        executable='esp32_bridge',
        name='esp32_bridge',
        output='screen'
    )

    # 3. Wheel Odometry
    wheel_odom = Node(
        package='aura_odom',
        executable='wheel_odom',
        name='wheel_odom',
        output='screen'
    )

    # 4. YDLidar Node (Directly launch node, avoid duplicate wrong TF from its own launch)
    ydlidar_params = os.path.join(bringup_dir, 'config', 'ydlidar.yaml')
    
    ydlidar_node = LifecycleNode(
        package='ydlidar_ros2_driver',
        executable='ydlidar_ros2_driver_node',
        name='ydlidar_ros2_driver_node',
        output='screen',
        emulate_tty=True,
        parameters=[ydlidar_params],
        namespace='/'
    )

    return LaunchDescription([
        display_launch,
        esp32_bridge,
        wheel_odom,
        ydlidar_node
    ])
