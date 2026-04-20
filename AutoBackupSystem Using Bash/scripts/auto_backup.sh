#!/bin/bash

DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$DIR/../config.cfg"

source "$CONFIG"

mkdir -p "$BACKUP_DEST"

while true
do

TIME=$(date +"%Y-%m-%d_%H-%M-%S")
FILE="$BACKUP_DEST/backup_$TIME.tar.gz"

(
tar -czf "$FILE" "$BACKUP_SRC"
) | zenity --progress \
--title="Backing up Desktop..." \
--pulsate \
--auto-close \
--no-cancel

echo "[$(date)] Backup Created: $FILE" >> "$LOG_FILE"

sleep "$INTERVAL"

done
