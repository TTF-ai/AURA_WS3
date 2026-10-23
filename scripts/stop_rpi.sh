#!/usr/bin/env bash

set -u

RPI_USER="${RPI_USER:-robo}"
RPI_HOST="${RPI_HOST:-${AURA_RPI_HOST:-CHANGE_ME}}"

if [[ "${RPI_HOST}" == "CHANGE_ME" ]]; then
  echo "RPI_HOST is not set."
  echo "Example: RPI_HOST=10.123.81.187 ./scripts/stop_rpi.sh"
  exit 1
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
  exit 1
fi
