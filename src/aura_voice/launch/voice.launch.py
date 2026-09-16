import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def load_env_file(path):
    """Load a simple KEY=VALUE .env file without requiring python-dotenv."""
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                text = line.strip()
                if not text or text.startswith('#') or '=' not in text:
                    continue
                key, value = text.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                os.environ.setdefault(key, value)
    except FileNotFoundError:
        pass


workspace_root = Path(__file__).resolve().parents[3]
load_env_file(workspace_root / '.env')
load_env_file(Path.home() / '.env')


def generate_launch_description():
    """Generate launch description for aura_voice."""
    input_mode = LaunchConfiguration('input_mode')

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

    env_actions = [
        SetEnvironmentVariable('PYTHONPATH', new_pp),
    ]

    for key in ['GROQ_API_KEY', 'ELEVENLABS_API_KEY', 'OPENROUTER_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']:
        val = os.environ.get(key, '')
        if val:
            env_actions.append(SetEnvironmentVariable(key, val))

    voice_node = Node(
        package='aura_voice',
        executable='voice_node',
        name='voice_node',
        output='screen',
        parameters=[config_path, {'input_mode': input_mode}],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument('input_mode', default_value='speech', description='speech or text'),
            *env_actions,
            voice_node,
        ]
    )
