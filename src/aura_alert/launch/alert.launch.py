import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import SetEnvironmentVariable
from launch_ros.actions import Node


def generate_launch_description():
    """Generate launch description for aura_alert."""
    # Inject PYTHONPATH for Virtual Environment packages (httpx, etc.)
    venv_site = os.path.expanduser('~/venv_aura/lib/python3.12/site-packages')
    existing_pp = os.environ.get('PYTHONPATH', '')
    new_pp = (
        venv_site + os.pathsep + existing_pp
        if existing_pp
        else venv_site
    )

    # Path to parameter YAML
    config_path = os.path.join(
        get_package_share_directory('aura_alert'),
        'config',
        'alert_params.yaml'
    )

    # Collect environment variable forwarding actions
    env_actions = [
        SetEnvironmentVariable('PYTHONPATH', new_pp),
    ]

    # Forward Telegram API keys from the current shell environment into the node
    for key in ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']:
        val = os.environ.get(key, '')
        if val:
            env_actions.append(SetEnvironmentVariable(key, val))

    alert_node = Node(
        package='aura_alert',
        executable='alert_node',
        name='alert_node',
        output='screen',
        parameters=[config_path],
    )

    return LaunchDescription(env_actions + [alert_node])
