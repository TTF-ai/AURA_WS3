import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import SetEnvironmentVariable

def generate_launch_description():
    venv_site = os.path.expanduser("~/venv_aura/lib/python3.12/site-packages")
    existing_pp = os.environ.get("PYTHONPATH", "")
    new_pp = (
        venv_site + os.pathsep + existing_pp
        if existing_pp
        else venv_site
    )
    set_pythonpath = SetEnvironmentVariable("PYTHONPATH", new_pp)

    config_path = os.path.join(
        get_package_share_directory('aura_behavior'),
        'config',
        'behavior_params.yaml'
    )

    behavior_node = Node(
        package="aura_behavior",
        executable="behavior_node",
        name="behavior_node",
        output="screen",
        parameters=[config_path],
    )

    return LaunchDescription([
        set_pythonpath,
        behavior_node,
    ])
