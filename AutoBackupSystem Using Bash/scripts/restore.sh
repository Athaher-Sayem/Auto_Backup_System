#!/bin/bash

DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$DIR/../config.cfg"

source "$CONFIG"

FILE=$(ls "$BACKUP_DEST" | zenity --list \
--title="Select Backup" \
--column="Backups")

[ -z "$FILE" ] && exit

tar -xzf "$BACKUP_DEST/$FILE" -C "$HOME"

zenity --info --text="Restore Completed"
