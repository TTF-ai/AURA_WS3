#!/usr/bin/env bash

set -u

WORKSPACE="${HOME}/AURA_WS3"
ROS_SETUP="/opt/ros/jazzy/setup.bash"
VENV_ACTIVATE="${HOME}/venv_aura/bin/activate"
INSTALL_SETUP="${WORKSPACE}/install/setup.bash"

RPI_USER="${RPI_USER:-robo}"
RPI_HOST="${RPI_HOST:-CHANGE_ME}"

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
  echo "Attach with: tmux attach -t aura_laptop"
  exit 0
fi

if [[ "${RPI_HOST}" == "CHANGE_ME" ]]; then
  echo "ERROR: Set RPI_HOST before starting the full AURA system. Example:"
  echo "  RPI_HOST=10.x.x.x ./scripts/start_aura_all.sh"
  echo "  or edit the variable at the top of this script."
  exit 1
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "${RPI_USER}@${RPI_HOST}" "echo SSH_OK" >/dev/null 2>&1; then
  echo "ERROR: SSH failed to ${RPI_USER}@${RPI_HOST}"
  echo "Check the host, SSH keys, and network connectivity before starting AURA."
  exit 1
fi

echo "Starting Pi-side AURA stack on ${RPI_USER}@${RPI_HOST}..."
ssh -o ConnectTimeout=10 "${RPI_USER}@${RPI_HOST}" "bash -lc 'export ROS_DOMAIN_ID=42; export ROS_LOCALHOST_ONLY=0; source /opt/ros/jazzy/setup.bash; source ~/venv_aura/bin/activate; source ~/AURA_WS3/install/setup.bash; ~/AURA_WS3/scripts/start_rpi.sh'"

if [[ $? -ne 0 ]]; then
  echo "ERROR: Pi startup command failed."
  exit 1
fi

echo "Starting laptop-side AURA stack locally..."
"${WORKSPACE}/scripts/start_laptop.sh"

echo ""
echo "AURA full startup complete"
echo "Pi session: aura_rpi"
echo "Laptop session: aura_laptop"
echo "Attach Pi: tmux attach -t aura_rpi"
echo "Attach Laptop: tmux attach -t aura_laptop"
