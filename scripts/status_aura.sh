#!/usr/bin/env bash

set -u

WORKSPACE="${HOME}/AURA_WS3"
ROS_SETUP="/opt/ros/jazzy/setup.bash"
VENV_ACTIVATE="${HOME}/venv_aura/bin/activate"
INSTALL_SETUP="${WORKSPACE}/install/setup.bash"

RPI_USER="${RPI_USER:-robo}"
RPI_HOST="${RPI_HOST:-CHANGE_ME}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required for AURA session management on this machine. Please install tmux and try again."
  exit 1
fi

source "${ROS_SETUP}" 2>/dev/null || true
source "${VENV_ACTIVATE}" 2>/dev/null || true
source "${INSTALL_SETUP}" 2>/dev/null || true
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0

printf '\n===== LOCAL LAPTOP =====\n'
if tmux has-session -t aura_laptop 2>/dev/null; then
  echo "TMUX SESSION: aura_laptop exists"
  tmux list-windows -t aura_laptop
  echo ""
  echo "ROS NODES (local):"
  ros2 node list 2>/dev/null || echo "ROS 2 not available or not running on this machine"
  echo ""
  echo "ROS TOPICS (local):"
  ros2 topic list 2>/dev/null | head -200 || echo "ROS 2 not available or not running on this machine"
else
  echo "TMUX SESSION: aura_laptop does not exist"
fi

printf '\n===== RASPBERRY PI =====\n'
if [[ "${RPI_HOST}" == "CHANGE_ME" ]]; then
  echo "RPI_HOST is not set. Remote Pi status is unavailable."
  echo "Set RPI_HOST=... to inspect the Pi session."
else
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "${RPI_USER}@${RPI_HOST}" "echo SSH_OK" >/dev/null 2>&1; then
    echo "SSH: connected to ${RPI_USER}@${RPI_HOST}"
    if ssh -o ConnectTimeout=5 "${RPI_USER}@${RPI_HOST}" "tmux has-session -t aura_rpi 2>/dev/null" >/dev/null 2>&1; then
      echo "TMUX SESSION: aura_rpi exists on Pi"
      ssh -o ConnectTimeout=5 "${RPI_USER}@${RPI_HOST}" "tmux list-windows -t aura_rpi"
      echo ""
      echo "ROS NODES (remote Pi):"
      ssh -o ConnectTimeout=5 "${RPI_USER}@${RPI_HOST}" "bash -lc 'source /opt/ros/jazzy/setup.bash; source ~/venv_aura/bin/activate; source ~/AURA_WS3/install/setup.bash; export ROS_DOMAIN_ID=42; export ROS_LOCALHOST_ONLY=0; ros2 node list'" 2>/dev/null || echo "ROS 2 not available or not running on the Pi"
      echo ""
      echo "ROS TOPICS (remote Pi):"
      ssh -o ConnectTimeout=5 "${RPI_USER}@${RPI_HOST}" "bash -lc 'source /opt/ros/jazzy/setup.bash; source ~/venv_aura/bin/activate; source ~/AURA_WS3/install/setup.bash; export ROS_DOMAIN_ID=42; export ROS_LOCALHOST_ONLY=0; ros2 topic list'" 2>/dev/null | head -200 || echo "ROS 2 not available or not running on the Pi"
    else
      echo "TMUX SESSION: aura_rpi does not exist on Pi"
    fi
  else
    echo "SSH: failed to connect to ${RPI_USER}@${RPI_HOST}"
  fi
fi

echo ""
echo "Notes:"
echo "- TMUX SESSION = shell session manager"
echo "- ROS NODE = active ROS 2 process"
echo "- PROCESS = command running in the shell. Use this status output together with ros2 node list."
