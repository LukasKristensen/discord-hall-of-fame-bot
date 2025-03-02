#!/bin/bash

source myenv/bin/activate

# Kill any existing tmux session
tmux has-session -t mysession 2>/dev/null
if [ $? -eq 0 ]; then
    echo "Stopping existing tmux session..."
    tmux kill-session -t mysession
    sleep 2  # Give time for shutdown
fi

while true; do
    # Pull latest changes
    git pull origin main

    echo "Starting bot in tmux session..."
    tmux new-session -d -s mysession "python3 main.py"

    # Wait for the bot process inside tmux to stop
    while tmux has-session -t mysession 2>/dev/null; do
        sleep 5  # Check every 5 seconds
    done

    echo "Bot crashed or stopped! Restarting in 5 seconds..."
    sleep 5  # Prevent instant looping
done
