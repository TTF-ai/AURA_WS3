#!/usr/bin/env bash

set -u

TARGET="${1:-all}"
RPI_USER="${RPI_USER:-robo}"
RPI_HOST="${RPI_HOST:-${AURA_RPI_HOST:-CHANGE_ME}}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required for AURA session management on this machine. Please install tmux and try again."
  exit 1
fi

stop_laptop() {
  if tmux has-session -t aura_laptop 2>/dev/null; then
    tmux kill-session -t aura_laptop
    echo "Stopped aura_laptop"
  else
    echo "aura_laptop session not running"
  fi
}

stop_rpi() {
  if [[ "${RPI_HOST}" == "CHANGE_ME" ]]; then
    echo "RPI_HOST is not set; skipping remote Pi session stop."
    return 0
  fi

  if ssh -o BatchMode=yes -o ConnectTimeout=5 "${RPI_USER}@${RPI_HOST}" "echo SSH_OK" >/dev/null 2>&1; then
    if ssh -o ConnectTimeout=5 "${RPI_USER}@${RPI_HOST}" "tmux has-session -t aura_rpi 2>/dev/null" >/dev/null 2>&1; then
      ssh -o ConnectTimeout=5 "${RPI_USER}@${RPI_HOST}" "tmux kill-session -t aura_rpi"
      echo "Stopped aura_rpi on ${RPI_USER}@${RPI_HOST}"
    else
      echo "aura_rpi session not running on ${RPI_USER}@${RPI_HOST}"
    fi
  else
    echo "SSH to ${RPI_USER}@${RPI_HOST} failed; remote session not stopped."
  fi
}

case "${TARGET}" in
  laptop)
    stop_laptop
    ;;
  rpi)
    stop_rpi
    ;;
  all|"")
    stop_laptop
    stop_rpi
    ;;
  *)
    echo "Usage: ./scripts/stop_aura_all.sh [all|laptop|rpi]"
    exit 1
    ;;
esac

echo "AURA stop complete"
