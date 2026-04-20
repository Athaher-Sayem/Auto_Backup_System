#!/bin/bash
# লক্ষ্য: Desktop এর অটো ব্যাকআপ নেয়া

# প্রোজেক্ট রুটে চলে আসুন (নিশ্চিত করুন যে সঠিক কনফিগ লোড হবে)
cd "$(dirname "$0")/.."
# কনফিগ ফাইল লোড
source config.cfg

# লগ ফোল্ডার তৈরি (যদি না থাকে)
mkdir -p logs

# বর্তমান সময় স্ট্যাম্প
timestamp=$(date +%Y-%m-%d_%H-%M-%S)
# ব্যাকআপ ফাইলের নাম (DesktopBakkup_<timestamp>.tar.gz)
backup_file="$BACKUP_DEST/desktop_backup_$timestamp.tar.gz"

# ব্যাকআপ ফোল্ডার তৈরি (যদি না থাকে)
mkdir -p "$BACKUP_DEST"

# ফাইল গুলো কমপ্রেস করে টার ফাইল তৈরি করুন
# (pf প্রাক-প্রসেসিং কমান্ড হিসেবে ব্যবহার করতে পারেন; এখানে সরলভাবে tar ব্যবহার)
tar -czf "$backup_file" -C "$BACKUP_SRC" .
echo "$timestamp: Backed up Desktop to $backup_file" >> logs/backup.log

