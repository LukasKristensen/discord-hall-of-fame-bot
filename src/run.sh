#!/bin/bash

cd /home/lukas/hall-of-fame-testing-branch/src
source /home/lukas/myenv/bin/activate

run_bot() {
    python3 main.py &
    BOT_PID=$!
}

kill_bot() {
    if [ -n "$BOT_PID" ] && kill -0 "$BOT_PID" 2>/dev/null; then
        kill "$BOT_PID"
        wait "$BOT_PID"
    fi
}

pull_changes() {
    echo "Pulling latest changes..."
    output=$(git pull origin main)
    echo "$output"
    if [[ "$output" == *"Already up to date."* ]]; then
        return 1
    else
        return 0
    fi
}

run_bot

while true; do
    sleep 60
    if pull_changes; then
        echo "Changes detected. Restarting bot..."
        kill_bot
        run_bot
    fi
    if ! kill -0 "$BOT_PID" 2>/dev/null; then
        echo "Bot stopped. Restarting..."
        run_bot
    fi
done
