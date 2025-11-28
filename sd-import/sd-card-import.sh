#!/bin/bash
# SD Card Auto-Import Script for Immich
# Triggered by udev when SD card is inserted

DEVICE="$1"
MOUNT_BASE="/mnt/sd-import"
IMPORT_BASE="${IMPORTS_PATH:-/mnt/user/jumpdrive/imports}"
LOG_FILE="/var/log/sd-card-import.log"
IMMICH_SERVER="${IMMICH_SERVER:-http://192.168.1.216:2283}"
LOCK_FILE="/tmp/sd-card-import.lock"
LOCK_TIMEOUT=300  # 5 minutes max - if lock older than this, ignore it

# Function to log messages
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Soft lock - prefer skipping duplicate runs but never block forever
acquire_lock() {
    if [ -f "$LOCK_FILE" ]; then
        LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
        if [ $LOCK_AGE -lt $LOCK_TIMEOUT ]; then
            log "Another import is running (lock age: ${LOCK_AGE}s), exiting"
            exit 0
        else
            log "Stale lock found (age: ${LOCK_AGE}s), removing and continuing"
            rm -f "$LOCK_FILE"
        fi
    fi
    echo $$ > "$LOCK_FILE"
}

release_lock() {
    rm -f "$LOCK_FILE"
}

# Clean up lock on exit (but don't trap errors - let script continue if lock fails)
trap release_lock EXIT

acquire_lock

log "=========================================="
log "SD card device detected: /dev/$DEVICE"

# Create timestamped import directory
TIMESTAMP=$(date '+%Y-%m-%d_%H%M%S')
IMPORT_DIR="$IMPORT_BASE/$TIMESTAMP"
mkdir -p "$IMPORT_DIR"

log "Import directory: $IMPORT_DIR"

# Find all partitions on the device
PARTITIONS=$(lsblk -ln -o NAME /dev/$DEVICE | grep -v "^${DEVICE}$" | sed "s|^|/dev/|")

if [ -z "$PARTITIONS" ]; then
    log "No partitions found, trying whole device"
    PARTITIONS="/dev/$DEVICE"
fi

TOTAL_COPIED=0

# Process each partition
for PARTITION in $PARTITIONS; do
    PART_NAME=$(basename "$PARTITION")
    log "Processing partition: $PARTITION"
    
    # Get filesystem type
    FS_TYPE=$(blkid -o value -s TYPE "$PARTITION" 2>/dev/null)
    log "Filesystem type: ${FS_TYPE:-unknown}"
    
    # Skip non-mountable filesystems
    if [ "$FS_TYPE" = "squashfs" ] || [ "$FS_TYPE" = "erofs" ] || [ -z "$FS_TYPE" ]; then
        log "Skipping non-mountable partition $PARTITION (type: ${FS_TYPE:-none})"
        continue
    fi
    
    # Create mount point
    MOUNT_POINT="$MOUNT_BASE/$PART_NAME"
    mkdir -p "$MOUNT_POINT"
    
    # Try to mount (try read-write first, fall back to read-only)
    WRITABLE=0
    if mount "$PARTITION" "$MOUNT_POINT" 2>> "$LOG_FILE"; then
        WRITABLE=1
        log "Mounted $PARTITION read-write to $MOUNT_POINT"
    elif mount -o ro "$PARTITION" "$MOUNT_POINT" 2>> "$LOG_FILE"; then
        WRITABLE=0
        log "Mounted $PARTITION read-only to $MOUNT_POINT"
    else
        log "Failed to mount $PARTITION, skipping"
        rmdir "$MOUNT_POINT" 2>/dev/null
        continue
    fi
    
    # Get partition label for better naming
    LABEL=$(blkid -o value -s LABEL "$PARTITION" 2>/dev/null)
    if [ -n "$LABEL" ]; then
        DEST_DIR="$IMPORT_DIR/${LABEL}_${PART_NAME}"
    else
        DEST_DIR="$IMPORT_DIR/$PART_NAME"
    fi
    
    mkdir -p "$DEST_DIR"
    log "Copying to: $DEST_DIR"
    
    # Build rsync command with exclude list if it exists
    EXCLUDE_FILE="$MOUNT_POINT/.immich_imported.txt"
    RSYNC_ITEMIZE_FILE=$(mktemp)
    RSYNC_CMD="rsync -av --progress --stats --itemize-changes --out-format='%n'"
    
    if [ -f "$EXCLUDE_FILE" ]; then
        EXISTING_COUNT=$(wc -l < "$EXCLUDE_FILE")
        log "Found existing import list with $EXISTING_COUNT files, will skip already imported files"
        RSYNC_CMD="$RSYNC_CMD --exclude-from=$EXCLUDE_FILE"
    fi
    
    # Perform the copy and capture what was actually transferred
    $RSYNC_CMD "$MOUNT_POINT/" "$DEST_DIR/" > "$RSYNC_ITEMIZE_FILE" 2>> "$LOG_FILE"
    COPY_EXIT=$?
    
    if [ $COPY_EXIT -eq 0 ] || [ $COPY_EXIT -eq 23 ] || [ $COPY_EXIT -eq 24 ]; then
        # Exit codes 23/24 are partial transfer (some files couldn't be copied but others succeeded)
        FILE_COUNT=$(grep -v '/$' "$RSYNC_ITEMIZE_FILE" | wc -l)
        log "Copy completed: $FILE_COUNT files copied to $DEST_DIR"
        TOTAL_COPIED=$((TOTAL_COPIED + FILE_COUNT))
        
        # If partition is writable, append successfully copied files to the imported list
        if [ $WRITABLE -eq 1 ]; then
            log "Appending successfully copied files to import tracking file"
            # Extract only actual files (not directories) that were transferred
            grep -v '/$' "$RSYNC_ITEMIZE_FILE" >> "$EXCLUDE_FILE" 2>/dev/null
            if [ $? -eq 0 ]; then
                TOTAL_TRACKED=$(wc -l < "$EXCLUDE_FILE")
                log "Tracking file now contains $TOTAL_TRACKED total entries"
            else
                log "Warning: Could not update tracking file (filesystem may not support it)"
            fi
        else
            log "Partition is read-only, cannot create tracking file"
        fi
    else
        log "ERROR: Copy failed with exit code $COPY_EXIT"
    fi
    
    # Clean up temp file
    rm -f "$RSYNC_ITEMIZE_FILE"
    
    # Unmount
    umount "$MOUNT_POINT"
    rmdir "$MOUNT_POINT" 2>/dev/null
    log "Unmounted $PARTITION"
done

log "Import complete: $TOTAL_COPIED total files copied to $IMPORT_DIR"

# Run immich-go if files were copied
if [ $TOTAL_COPIED -gt 0 ]; then
    log "Starting immich-go upload from $IMPORT_DIR"
    
    if command -v immich-go-upload &> /dev/null; then
        immich-go-upload "$IMPORT_DIR" >> "$LOG_FILE" 2>&1
        UPLOAD_EXIT=$?
        
        if [ $UPLOAD_EXIT -eq 0 ]; then
            log "immich-go upload completed successfully"
        else
            log "ERROR: immich-go upload failed with exit code $UPLOAD_EXIT"
        fi
    else
        log "WARNING: immich-go-upload not found in PATH"
    fi
else
    log "No files copied, skipping immich-go upload"
fi

log "Import process completed"
log "=========================================="
exit 0
