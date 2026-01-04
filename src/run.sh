#!/usr/bin/env bash

set -e

WORKDIR="/home/lukas/hall-of-fame/src"
VENV="/home/lukas/myenv"
ENV_FILE="/home/lukas/hall-of-fame/.env"
TEMP_ENV="/home/lukas/.env_temp"
REPO_URL="https://github.com/LukasKristensen/discord-hall-of-fame-bot.git"
REPO_DIR="/home/lukas/hall-of-fame"

# Backup .env if it exists
if [[ -f "$ENV_FILE" ]]; then
    mv "$ENV_FILE" "$TEMP_ENV"
    echo "[INFO] Backed up .env temporarily"
fi

# Ensure repo exists and is up-to-date
if [[ ! -d "$REPO_DIR/.git" ]]; then
    echo "[INFO] Repo missing. Cloning fresh copy..."
    git clone "$REPO_URL" "$REPO_DIR"
else
    cd "$REPO_DIR"
    echo "[INFO] Checking for updates..."
    git fetch --all --prune
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [[ "$LOCAL" != "$REMOTE" ]]; then
        echo "[INFO] Update found. Resetting to origin/main..."
        git reset --hard origin/main
    fi
fi

# Restore .env if backup exists
if [[ -f "$TEMP_ENV" ]]; then
    mv "$TEMP_ENV" "$ENV_FILE"
    echo "[INFO] Restored .env after update"
fi

# Activate venv and load .env
cd "$WORKDIR"
source "$VENV/bin/activate"
export $(grep -v '^#' "../.env" | xargs)

# Start the bot in foreground (systemd manages it)
echo "[INFO] Starting bot with auto-retry..."
while true; do
    python main.py
    echo "[WARN] Bot exited. Restarting in 5 seconds..."
    sleep 5
done
