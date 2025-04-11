#!/bin/bash

cd "$(dirname "$0")"  # Ensure script runs from its own directory
cd src  # Move into the correct folder where main.py is

source ../myenv/bin/activate  # Adjust path to activate virtual env

pull_changes() {
    echo "Pulling latest changes..."
    git pull origin main
    echo "Finished pulling changes."
}

run_bot() {
    echo "Starting bot in tmux session..."
    # When main.py exits, the tmux session is killed automatically
    tmux new-session -d -s bot_session 'python3 main.py; tmux kill-session -t bot_session'
}

# Kill any existing bot session before starting
if tmux has-session -t bot_session 2>/dev/null; then
    echo "Stopping existing bot session..."
    tmux kill-session -t bot_session
    sleep 2
fi

while true; do
    pull_changes
    run_bot

    # Track start time for 24-hour cycle
    start_time=$(date +%s)

    while tmux has-session -t bot_session 2>/dev/null; do
        current_time=$(date +%s)
        elapsed=$((current_time - start_time))

        if [ "$elapsed" -ge 60 ]; then
            echo "24 hours passed. Restarting bot..."
            tmux kill-session -t bot_session
            break
        fi

        sleep 5  # Check every 5 seconds
    done

    echo "Bot crashed or stopped! Restarting in 5 seconds..."
    sleep 5
done
