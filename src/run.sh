#!/bin/bash

cd "$(dirname "$0")"
cd src

source ../myenv/bin/activate

# Handle Ctrl+C to detach tmux session (not kill it)
cleanup() {
    echo "Caught Ctrl+C. Detaching tmux session..."
    tmux detach -s bot_session  # Detach, don't kill the session
}

trap cleanup SIGINT  # Trap Ctrl+C

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
fi

while true; do
    pull_changes
    run_bot

    start_time=$(date +%s)
    restart_after=86400  # 60 seconds for testing; set to 86400 for 24h

    while true; do
        current_time=$(date +%s)
        elapsed=$((current_time - start_time))

        if ! tmux has-session -t bot_session 2>/dev/null; then
            echo "Bot crashed or stopped!"
            break
        fi

        if [ "$elapsed" -ge "$restart_after" ]; then
            echo "$restart_after seconds passed. Restarting bot..."
            tmux kill-session -t bot_session
            break
        fi

        sleep 5
    done

    echo "Restarting in 5 seconds..."
    sleep 5
done
