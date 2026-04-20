#!/bin/bash

WATCH="$HOME/Desktop"

while true
do
inotifywait -r -e modify,create,move "$WATCH" >/dev/null 2>&1

# force write buffers to disk
sync

# copy temp editor files if exist
find "$WATCH" -type f \( -name "*.swp" -o -name "*~" -o -name ".#*" \) 2>/dev/null | while read f
do
base=$(echo "$f" | sed 's/\.\w*$//')
cp "$f" "$base.autosave" 2>/dev/null
done

sleep 2
done
