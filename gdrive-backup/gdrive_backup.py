#!/usr/bin/env python3
import os
import subprocess
import datetime
from pathlib import Path

# CONFIGURABLE PATHS
RCLONE_REMOTE = "gdrive:"  # Sync entire Google Drive
LOCAL_BACKUP_DIR = Path("/mnt/user/jumpdrive/gdrive")
STATE_FILE = Path("/mnt/user/jumpdrive/gdrive/.state/last_sync.txt")


def ensure_dirs():
    for p in [LOCAL_BACKUP_DIR, STATE_FILE.parent]:
        p.mkdir(parents=True, exist_ok=True)


def sync_from_drive():
    """Use rclone to sync entire Google Drive to LOCAL_BACKUP_DIR."""
    cmd = [
        "rclone",
        "sync",
        RCLONE_REMOTE,
        str(LOCAL_BACKUP_DIR),
        "--create-empty-src-dirs",
        "--exclude", "Takeout/**",  # Exclude Takeout folder (handled by other script)
        "--verbose",
        "--stats", "10s",
        "--transfers", "8",
        "--checkers", "16",
    ]
    print(f"[INFO] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print("[ERROR] rclone sync failed")
        raise RuntimeError("rclone sync failed")


def update_sync_timestamp():
    """Record the timestamp of this sync."""
    now = datetime.datetime.now().isoformat()
    STATE_FILE.write_text(now, encoding="utf-8")
    print(f"[INFO] Sync timestamp updated: {now}")


def main():
    ensure_dirs()
    sync_from_drive()
    update_sync_timestamp()
    print("[INFO] Google Drive backup complete.")


if __name__ == "__main__":
    main()
