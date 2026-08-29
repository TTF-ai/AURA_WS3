#!/usr/bin/env python3
"""
AURA Face Authentication Launch File

Launches all face authentication nodes.

Parameters:
    use_internal_camera (bool): Launch camera_node (default: true)
    development_mode (bool): Liveness dev mode (default: false)
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    # ---------------------------------------------------------
    # Virtual-environment support
    # ---------------------------------------------------------
    # ROS 2 node scripts use #!/usr/bin/python3, which bypasses
    # the venv.  Prepend the venv site-packages so that every
    # child process can import insightface, onnxruntime, etc.
    # ---------------------------------------------------------

    import os
    import sys

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
    # Launch arguments
    # ---------------------------------------------------------

    use_camera_arg = DeclareLaunchArgument(
        "use_internal_camera",
        default_value="true",
        description="Launch the internal camera node"
    )

    dev_mode_arg = DeclareLaunchArgument(
        "development_mode",
        default_value="false",
        description="Enable liveness development mode"
    )

    # ---------------------------------------------------------
    # Nodes
    # ---------------------------------------------------------

    camera_node = Node(
        package="aura_face_auth",
        executable="camera_node",
        name="camera_node",
        output="screen",
        parameters=[{
            "camera_index": 0,
            "frame_width": 640,
            "frame_height": 480,
            "fps": 30,
        }],
        condition=IfCondition(
            LaunchConfiguration("use_internal_camera")
        ),
    )

    detector_node = Node(
        package="aura_face_auth",
        executable="face_detector_node",
        name="face_detector_node",
        output="screen",
        parameters=[{
            "det_thresh": 0.5,
            "det_size": 640,
            "process_every_n_frames": 2,
            "execution_provider": "auto",
        }],
    )

    recognizer_node = Node(
        package="aura_face_auth",
        executable="recognizer_node",
        name="recognizer_node",
        output="screen",
        parameters=[{
            "recognition_interval": 0.5,
            "execution_provider": "auto",
            "model_path": "",
        }],
    )

    liveness_node = Node(
        package="aura_face_auth",
        executable="liveness_node",
        name="liveness_node",
        output="screen",
        parameters=[{
            "liveness_threshold": 0.5,
            "liveness_interval": 0.5,
            "development_mode": LaunchConfiguration(
                "development_mode"
            ),
            "dev_liveness_score": 1.0,
        }],
    )

    auth_node = Node(
        package="aura_face_auth",
        executable="auth_node",
        name="auth_node",
        output="screen",
        parameters=[{
            "similarity_threshold": 0.4,
            "authentication_timeout": 60.0,
            "reverify_interval": 10.0,
            "allow_multiple_faces": False,
            "min_quality": 0.3,
        }],
    )

    # ---------------------------------------------------------
    # Launch description
    # ---------------------------------------------------------

    return LaunchDescription([
        set_pythonpath,
        use_camera_arg,
        dev_mode_arg,
        camera_node,
        detector_node,
        recognizer_node,
        liveness_node,
        auth_node,
    ])
