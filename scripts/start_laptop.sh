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

if tmux has-session -t aura_laptop 2>/dev/null; then
  echo "AURA Laptop session already running"
  echo "Attach: tmux attach -t aura_laptop"
  exit 0
fi

tmux new-session -d -s aura_laptop -n face_detector

send_cmd() {
  local target="$1"
  local cmd="$2"
  tmux send-keys -t "${target}" "$cmd" C-m
}

send_cmd "aura_laptop:face_detector" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 run aura_face_auth face_detector_node --ros-args -p det_thresh:=0.5 -p det_size:=640 -p process_every_n_frames:=2 -p execution_provider:='auto'"

tmux new-window -t aura_laptop -n recognizer
send_cmd "aura_laptop:recognizer" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 run aura_face_auth recognizer_node --ros-args -p recognition_interval:=0.5 -p execution_provider:='auto' -p model_path:='~/.insightface/models/buffalo_s/w600k_mbf.onnx'"

tmux new-window -t aura_laptop -n liveness
send_cmd "aura_laptop:liveness" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 run aura_face_auth liveness_node --ros-args -p liveness_threshold:=0.5 -p liveness_interval:=0.5 -p development_mode:=false -p dev_liveness_score:=1.0"

tmux new-window -t aura_laptop -n auth
send_cmd "aura_laptop:auth" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 run aura_face_auth auth_node --ros-args -p similarity_threshold:=0.4 -p authentication_timeout:=60.0 -p reverify_interval:=10.0 -p allow_multiple_faces:=false -p min_quality:=0.3"

tmux new-window -t aura_laptop -n behavior
send_cmd "aura_laptop:behavior" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 launch aura_behavior behavior.launch.py"

tmux new-window -t aura_laptop -n follow
send_cmd "aura_laptop:follow" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 launch aura_follow human_follow.launch.py"

tmux new-window -t aura_laptop -n voice
send_cmd "aura_laptop:voice" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 launch aura_voice voice.launch.py"

tmux new-window -t aura_laptop -n alerts
send_cmd "aura_laptop:alerts" "cd \"${WORKSPACE}\" && source \"${ROS_SETUP}\" && source \"${VENV_ACTIVATE}\" && source \"${INSTALL_SETUP}\" && export ROS_DOMAIN_ID=42 && export ROS_LOCALHOST_ONLY=0 && ros2 launch aura_alert alert.launch.py"

echo "AURA laptop startup initiated"
echo "Session: aura_laptop"
echo "Windows: face_detector | recognizer | liveness | auth | behavior | follow | voice | alerts"
echo "Attach: tmux attach -t aura_laptop"
