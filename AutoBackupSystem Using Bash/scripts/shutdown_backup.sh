#!/bin/bash

DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$DIR/../config.cfg"

source "$CONFIG"

TIME=$(date +"%Y-%m-%d_%H-%M-%S")
FILE="$BACKUP_DEST/shutdown_$TIME.tar.gz"

tar -czf "$FILE" "$BACKUP_SRC"

echo "[$(date)] Shutdown Backup Created" >> "$LOG_FILE"
