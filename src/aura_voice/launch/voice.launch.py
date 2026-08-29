import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import SetEnvironmentVariable
from launch_ros.actions import Node


def generate_launch_description():
    """Generate launch description for aura_voice."""
    # Inject PYTHONPATH for Virtual Environment packages (httpx, etc.)
    venv_site = os.path.expanduser('~/venv_aura/lib/python3.12/site-packages')
    existing_pp = os.environ.get('PYTHONPATH', '')
    new_pp = (
        venv_site + os.pathsep + existing_pp
        if existing_pp
        else venv_site
    )

    config_path = os.path.join(
        get_package_share_directory('aura_voice'),
        'config',
        'voice_params.yaml'
    )

    # Collect environment variable forwarding actions
    env_actions = [
        SetEnvironmentVariable('PYTHONPATH', new_pp),
    ]

    # Forward API keys from the current shell environment into the node
    for key in ['GROQ_API_KEY', 'ELEVENLABS_API_KEY', 'OPENROUTER_API_KEY']:
        val = os.environ.get(key, '')
        if val:
            env_actions.append(SetEnvironmentVariable(key, val))

    voice_node = Node(
        package='aura_voice',
        executable='voice_node',
        name='voice_node',
        output='screen',
        parameters=[config_path],
    )

    return LaunchDescription(env_actions + [voice_node])
