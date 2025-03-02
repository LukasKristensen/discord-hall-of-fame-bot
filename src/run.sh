#!/bin/bash

source myenv/bin/activate

pull_changes() {
    echo "Pulling changes from remote current version..."
    git pull origin main
    echo "Pulled changes from remote current version"
}

run_bot() {
    echo "Starting bot in tmux session..."
    tmux new-session -d -s bot_session 'python3 ../src/main.py'
}

while true; do
    pull_changes
    run_bot
    echo "Bot crashed, restarting in 5 seconds..."
    sleep 5
done