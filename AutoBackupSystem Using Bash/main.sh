#!/bin/bash
cd "$(dirname "$0")"
source config.cfg

# Zenity রেডিও লিস্ট দিয়ে অপশন দেখান
action=$(zenity --list --radiolist --title="Auto Backup System" \
    --column="Select" --column="Action" FALSE "Backup Now" FALSE "Restore Backup" FALSE "Exit")

case "$action" in
    "Backup Now")
        # ব্যাকআপ স্ক্রিপ্টটি চালান (প্রোগ্রেস বার দেখানোর জন্য)
        # pv কমান্ডের সাহায্যে প্রক্রিয়ার প্রগ্রেস Zenity-তে পাঠান【10†L151-L155】।
        (
            # ব্যাকআপ লজিক (টিআর-পাইপ-PV-জিপ)
            cd "$BACKUP_SRC" \
            && tar -cf - . \
            | pv -n -s $(du -sb "$BACKUP_SRC" | awk '{print $1}') \
            | gzip > "$BACKUP_DEST/desktop_backup_$(date +%Y-%m-%d_%H-%M-%S).tar.gz"
        ) 2>&1 | zenity --progress --auto-close --percentage=0 --title="ব্যাকআপ হচ্ছে..."
        ;;
    "Restore Backup")
        bash scripts/restore.sh
        ;;
    "Exit")
        exit 0
        ;;
esac

