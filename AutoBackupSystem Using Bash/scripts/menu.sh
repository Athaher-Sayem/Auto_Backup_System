#!/bin/bash

DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$DIR/../config.cfg"

source "$CONFIG"

while true
do

CHOICE=$(zenity --list \
--title="Auto Backup System" \
--width=400 \
--height=300 \
--column="Menu" \
"Start Auto Backup" \
"Stop Auto Backup" \
"Restore Backup" \
"Open Backup Folder" \
"View Logs" \
"Exit")

case $CHOICE in

"Start Auto Backup")
bash "$DIR/auto_backup.sh" &
;;

"Stop Auto Backup")
pkill -f auto_backup.sh
zenity --info --text="Backup Stopped"
;;

"Restore Backup")
bash "$DIR/restore.sh"
;;

"Open Backup Folder")
xdg-open "$BACKUP_DEST"
;;

"View Logs")
zenity --text-info --filename="$LOG_FILE"
;;

"Exit")
exit
;;

esac

done
