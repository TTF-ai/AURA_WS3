#!/usr/bin/env bash

set -u

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required for AURA session management on this machine. Please install tmux and try again."
  exit 1
fi

if tmux has-session -t aura_laptop 2>/dev/null; then
  tmux kill-session -t aura_laptop
  echo "Stopped aura_laptop"
else
  echo "aura_laptop session not running"
fi
