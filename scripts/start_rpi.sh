#!/usr/bin/env bash

set -u

WORKSPACE="${HOME}/AURA_WS3"
ROS_SETUP="/opt/ros/jazzy/setup.bash"
VENV_ACTIVATE="${HOME}/venv_aura/bin/activate"
INSTALL_SETUP="${WORKSPACE}/install/setup.bash"

safe_source() {
  local file="$1"
  if [[ -f "${file}" ]]; then
    set +u
    source "${file}"
    set -u
  else
    echo "ERROR: required file not found: ${file}"
    exit 1
  fi
}

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required for AURA startup on this machine. Please install tmux and try again."
  exit 1
fi

if [[ ! -d "${WORKSPACE}" ]]; then
  echo "ERROR: workspace not found: ${WORKSPACE}"
  exit 1
fi

if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "ERROR: ROS 2 Jazzy not found at ${ROS_SETUP}"
  exit 1
fi

if [[ ! -f "${VENV_ACTIVATE}" ]]; then
  echo "ERROR: Python virtual environment not found: ${VENV_ACTIVATE}"
  exit 1
fi

if [[ ! -f "${INSTALL_SETUP}" ]]; then
  echo "ERROR: ROS workspace install setup not found: ${INSTALL_SETUP}"
  exit 1
fi

export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0

safe_source "${ROS_SETUP}"
safe_source "${VENV_ACTIVATE}"
safe_source "${INSTALL_SETUP}"

if tmux has-session -t aura_rpi 2>/dev/null; then
  echo "AURA Pi session already running"
  echo "Attach: tmux attach -t aura_rpi"
  exit 0
fi

tmux new-session -d -s aura_rpi -n hardware

send_cmd() {
  local target="$1"
  local cmd="$2"
  tmux send-keys -t "${target}" "$cmd" C-m
}

send_cmd "aura_rpi:hardware" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 launch aura_bringup robot.launch.py"

tmux new-window -t aura_rpi -n camera
send_cmd "aura_rpi:camera" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 run aura_face_auth camera_node" # --ros-args -p camera_index:=0 -p frame_width:=640 -p frame_height:=480 -p fps:=30"

tmux new-window -t aura_rpi -n slam
send_cmd "aura_rpi:slam" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 launch aura_slam slam.launch.py"

tmux new-window -t aura_rpi -n nav2
if [[ -n "${NAV2_MAP_PATH:-}" ]]; then
  send_cmd "aura_rpi:nav2" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 launch aura_navigation navigation.launch.py map:=${NAV2_MAP_PATH} use_rviz:=false"
else
  send_cmd "aura_rpi:nav2" "echo 'Navigation requires a map file. Set NAV2_MAP_PATH=/absolute/path/to/map.yaml before starting nav2.'"
fi

tmux new-window -t aura_rpi -n frontier
send_cmd "aura_rpi:frontier" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 launch aura_exploration exploration.launch.py"

echo "AURA Pi startup initiated"
echo "Session: aura_rpi"
echo "Windows: hardware | camera | slam | nav2 | frontier"
echo "Attach: tmux attach -t aura_rpi"
