#!/usr/bin/env bash

set -e

REPO_URL="https://github.com/LukasKristensen/discord-hall-of-fame-bot.git"
WORKDIR="/home/lukas/hall-of-fame"
VENV="/home/lukas/myenv"

terminate=false
child_pid=0

notify_ready() {
    systemd-notify --ready
}

notify_watchdog() {
    systemd-notify WATCHDOG=1
}

graceful_exit() {
    terminate=true
    if [[ $child_pid -ne 0 ]]; then
        kill -SIGTERM "$child_pid"
        wait "$child_pid"
    fi
    exit 0
}

trap graceful_exit SIGINT SIGTERM

ensure_repo() {
    ENV_FILE="$WORKDIR/.env"
    TEMP_ENV="/home/lukas/.env_temp"
    updated=1

    # Temporarily move .env if it exists
    if [[ -f "$ENV_FILE" ]]; then
        mv "$ENV_FILE" "$TEMP_ENV"
        echo "[INFO] Backed up .env temporarily"
    fi

    if [[ ! -d "$WORKDIR/.git" ]]; then
        echo "[INFO] Repo missing. Cloning fresh copy..."
        rm -rf "$WORKDIR"
        git clone "$REPO_URL" "$WORKDIR"
        updated=0
    else
        cd "$WORKDIR"
        echo "[INFO] Checking for updates..."
        git fetch --all --prune
        LOCAL=$(git rev-parse HEAD)
        REMOTE=$(git rev-parse origin/main)
        if [[ "$LOCAL" != "$REMOTE" ]]; then
            echo "[INFO] Update found. Resetting to origin/main..."
            git reset --hard origin/main
            updated=0
        fi
    fi

    # Restore .env if backup exists
    if [[ -f "$TEMP_ENV" ]]; then
        mv "$TEMP_ENV" "$WORKDIR/.env"
        echo "[INFO] Restored .env after update"
    fi

    return $updated
}

load_env() {
    ENV_FILE="$WORKDIR/.env"
    if [[ -f "$ENV_FILE" ]]; then
        export $(grep -v '^#' "$ENV_FILE" | xargs)
        echo "[INFO] Loaded environment variables from .env"
    else
        echo "[WARN] .env file not found!"
    fi
}

run_bot() {
    echo "[INFO] Starting bot..."
    source "$VENV/bin/activate"
    cd "$WORKDIR"
    load_env
    python main.py &
    child_pid=$!
    notify_ready
    while kill -0 "$child_pid" 2>/dev/null; do
        notify_watchdog
        sleep 10
    done
    wait "$child_pid"
}

while true; do
    if $terminate; then
        break
    fi
    ensure_repo
    repo_updated=$?
    if [[ $repo_updated -eq 0 ]]; then
        echo "[INFO] Repo updated, restarting bot."
        if [[ $child_pid -ne 0 ]]; then
            kill -SIGTERM "$child_pid"
            wait "$child_pid"
        fi
    fi
    run_bot
    if $terminate; then
        break
    fi
    sleep 60
done
