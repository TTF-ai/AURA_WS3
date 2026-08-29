#!/bin/bash

# AURA System Bringup Script
# This script launches all 5 AURA subsystems in the background and stops them all together if you press Ctrl+C.

echo "=========================================="
echo "          Starting AURA Robot             "
echo "=========================================="

# Trap Ctrl+C (SIGINT) to kill all background processes spawned by this script
trap "echo -e '\nStopping all AURA nodes...'; kill 0" SIGINT SIGTERM EXIT

# Function to source the required ROS and virtual environments
source_env() {
    source /opt/ros/jazzy/setup.bash
    source ~/venv_aura/bin/activate
    source ~/AURA_WS3/install/setup.bash
}

# 1. Load API Keys
# Assuming your keys are in a .env file located at the root of the workspace
if [ -f "$HOME/AURA_WS3/src/aura_alert/.env" ]; then
    export $(grep -v '^#' $HOME/AURA_WS3/src/aura_alert/.env | xargs)
    echo "✅ Loaded API keys from src/aura_alert/.env"
elif [ -f "$HOME/AURA_WS3/.env" ]; then
    export $(grep -v '^#' $HOME/AURA_WS3/.env | xargs)
    echo "✅ Loaded API keys from .env"
else
    echo "⚠️  WARNING: No .env file found. Make sure API keys (GROQ_API_KEY, TELEGRAM_BOT_TOKEN, etc.) are exported in your bashrc."
fi

echo "------------------------------------------"

# 2. Launch nodes in the background
echo "🚀 [1/5] Starting Face Authentication..."
(source_env && ros2 launch aura_face_auth face_auth.launch.py development_mode:=true) &
sleep 3

echo "🚀 [2/5] Starting Human Following..."
(source_env && ros2 launch aura_follow human_follow.launch.py) &
sleep 2

echo "🚀 [3/5] Starting Behavior Estimation..."
(source_env && ros2 launch aura_behavior behavior.launch.py) &
sleep 2

echo "🚀 [4/5] Starting Voice Interaction..."
(source_env && ros2 launch aura_voice voice.launch.py) &
sleep 2

echo "🚀 [5/5] Starting Emergency Alerts..."
(source_env && ros2 launch aura_alert alert.launch.py) &

echo "=========================================="
echo " ✅ All AURA subsystems are running!"
echo " 🛑 Press Ctrl+C at any time to stop all nodes."
echo "=========================================="

# Wait indefinitely until Ctrl+C is pressed
wait
