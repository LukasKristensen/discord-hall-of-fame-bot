#!/bin/bash

cd "$(dirname "$0")"
# cd src

source ../../myenv/bin/activate

pull_changes() {
    echo "Pulling latest changes..."
    output=$(git pull origin main)
    echo "$output"

    if [[ "$output" == *"Already up to date."* ]]; then
        return 1  # No updates
    else
        return 0  # New updates
    fi
}

run_bot() {
  if tmux has-session -t bot 2>/dev/null; then
      echo "Stopping existing bot session..."
      tmux kill-session -t bot
      sleep 2
  fi

  echo "Starting bot in tmux session..."
  tmux new-session -d -s bot 'python3 main.py; tmux kill-session -t bot'
}

# Start the bot for the first time
run_bot

while true; do
  if pull_changes; then
    echo "Changes detected. Restarting bot..."
    run_bot
  else
    echo "No changes. Bot not restarted."
  fi

  sleep 60
done
