#!/bin/bash

cd "$(dirname "$0")"
cd src

source ../myenv/bin/activate

pull_changes() {
    echo "Pulling latest changes..."
    git pull origin main
    echo "Finished pulling changes."
}

run_bot() {
    echo "Starting bot in tmux session..."
    tmux new-session -d -s bot_session 'python3 main.py; tmux kill-session -t bot_session'
}

# Kill any existing bot session before starting
if tmux has-session -t bot_session 2>/dev/null; then
    echo "Stopping existing bot session..."
    tmux kill-session -t bot_session
    sleep 2


while true; do
  pull_changes
  run_bot
