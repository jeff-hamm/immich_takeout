#!/bin/sh
echo "[$(date)] Starting Takeout sync..."
rclone sync gdrive:Takeout /data/raw --verbose --stats 10s
echo "[$(date)] Takeout sync complete"
EOF
chmod +x /mnt/user/appdata/takeout-script/takeout-sync.sh ; cat /mnt/user/appdata/takeout-script/takeout-sync.sh
