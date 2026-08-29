#!/usr/bin/env python3
"""
AURA Human Follow Launch File

Launches the human_follow_node.

The face authentication system must be launched separately:
  ros2 launch aura_face_auth face_auth.launch.py development_mode:=true

Parameters:
    disable_motors (bool): If true, do NOT publish /cmd_vel
                           (default: false)
"""

import os

from launch import LaunchDescription
from launch.actions import SetEnvironmentVariable
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    # ---------------------------------------------------------
    # Virtual-environment support (same as face_auth launch)
    # ---------------------------------------------------------

    venv_site = os.path.expanduser(
        "~/venv_aura/lib/python3.12/site-packages"
    )

    existing_pp = os.environ.get("PYTHONPATH", "")

    new_pp = (
        venv_site + os.pathsep + existing_pp
        if existing_pp
        else venv_site
    )

    set_pythonpath = SetEnvironmentVariable(
        "PYTHONPATH", new_pp
    )

    # ---------------------------------------------------------
    # Human follow node
    # ---------------------------------------------------------

    config_path = os.path.join(
        get_package_share_directory('aura_follow'),
        'config',
        'follow_params.yaml'
    )

    follow_node = Node(
        package="aura_follow",
        executable="human_follow_node",
        name="human_follow_node",
        output="screen",
        parameters=[config_path],
    )

    return LaunchDescription([
        set_pythonpath,
        follow_node,
    ])
