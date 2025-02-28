#!/bin/bash

source myenv/bin/activate

# Kill existing session if running
tmux kill-session -t mysession 2>/dev/null

while true; do
    # Pull latest changes
    git pull origin main

    # Start bot in tmux
    tmux new -d -s mysession "python3 main.py"

    echo "Bot started! Monitoring for crashes..."

    # Wait for the bot process to exit before restarting
    sleep 5  # Small delay before checking again
    tmux wait -s mysession  # This will wait until tmux session ends

    echo "Bot crashed or stopped! Restarting..."
done
