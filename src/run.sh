#!/bin/bash

cd "$(dirname "$0")"
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
    echo "Starting bot..."
    python3 main.py
}

while true; do
    run_bot
    echo "Bot stopped. Checking for updates..."
    if pull_changes; then
        echo "Changes detected. Restarting bot..."
    else
        echo "No changes."
    fi
    sleep 60
done
