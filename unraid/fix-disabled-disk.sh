#!/bin/bash
#
# fix-disabled-disk.sh - Fix a disabled disk in Unraid array
#
# This script fixes the "DISK_DSBL" status that occurs when a disk is
# accidentally unplugged while the array is running. It patches the
# superblock to change the disk state from DSBL (4) to OK (7).
#
# Usage: fix-disabled-disk.sh <disk_name>
#   disk_name: The disk name (e.g., disk1, disk2, parity, parity2)
#              Or slot number (0=parity, 1-28=data disks, 29=parity2)
#
# Examples:
#   fix-disabled-disk disk1
#   fix-disabled-disk parity2
#   fix-disabled-disk 1
#
# WARNING: This script modifies the Unraid superblock. Use with caution!
#          Always ensure you have backups before running.
#

# Wrap with Copilot CLI for monitoring
/usr/local/bin/copilot-monitor.sh "$0" "$@"

set -e
DISK_INPUT="$1"

# Disk state values
STATE_EMPTY=0
STATE_DSBL=4
STATE_OK=7

# Convert disk name to slot number
parse_disk_name() {
    local input="$1"
    
    # If empty, show usage
    if [[ -z "$input" ]]; then
        echo ""
        return 1
    fi
    
    # If already a number, return it
    if [[ "$input" =~ ^[0-9]+$ ]]; then
        echo "$input"
        return 0
    fi
    
    # Parse disk names
    case "$input" in
        parity|parity1)
            echo 0
            ;;
        parity2)
            echo 29
            ;;
        disk[0-9]|disk[0-9][0-9])
            # Extract number from disk1, disk2, etc.
            echo "${input#disk}"
            ;;
        cache|pool)
            echo "ERROR: Cache/pool disks are not part of the array"
            return 1
            ;;
        *)
            echo "ERROR: Unknown disk name: $input"
            return 1
            ;;
    esac
}

# Show usage
usage() {
    echo "Usage: $0 <disk_name>"
    echo ""
    echo "  disk_name: The disk to fix (e.g., disk1, disk2, parity, parity2)"
    echo "             Or slot number (0=parity, 1-28=data disks, 29=parity2)"
    echo ""
    echo "Examples:"
    echo "  $0 disk1      # Fix data disk 1"
    echo "  $0 parity2    # Fix parity 2"
    echo "  $0 1          # Fix slot 1 (same as disk1)"
    exit 1
}

# Calculate offset for disk state in super.dat
# Structure: Each disk entry is 128 bytes (0x80)
# Header is 128 bytes (0x80)
# Disk state is at offset 12 (0x0C) within each disk entry
# So: offset = 0x80 + (slot * 0x80) + 0x0C = 128 + (slot * 128) + 12
calculate_offset() {
    local slot=$1
    echo $((128 + (slot * 128) + 12))
}

# Read current disk state at offset
read_state() {
    local offset=$1
    hexdump -s "$offset" -n 1 -e '1/1 "%u"' "$SUPER_DAT"
}

# Get disk ID from super.dat
get_disk_id() {
    local slot=$1
    local id_offset=$((128 + (slot * 128) + 24))  # ID string starts at offset 24 within entry
    dd if="$SUPER_DAT" bs=1 skip="$id_offset" count=40 2>/dev/null | tr -d '\0'
}

echo "=== Unraid Disabled Disk Fixer ==="
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

# Parse disk name argument
if [[ -z "$DISK_INPUT" ]]; then
    usage
fi

DISK_SLOT=$(parse_disk_name "$DISK_INPUT")
if [[ $? -ne 0 ]] || [[ -z "$DISK_SLOT" ]] || [[ "$DISK_SLOT" == ERROR* ]]; then
    echo "$DISK_SLOT"
    usage
fi

# Determine friendly name for display
if [[ "$DISK_SLOT" -eq 0 ]]; then
    DISK_NAME="parity"
elif [[ "$DISK_SLOT" -eq 29 ]]; then
    DISK_NAME="parity2"
else
    DISK_NAME="disk${DISK_SLOT}"
fi

# Check if super.dat exists
if [[ ! -f "$SUPER_DAT" ]]; then
    echo "ERROR: $SUPER_DAT not found"
    exit 1
fi

# Calculate offset for the disk slot
OFFSET=$(calculate_offset "$DISK_SLOT")
echo "Disk: $DISK_NAME (slot $DISK_SLOT)"
echo "Superblock offset: $OFFSET (0x$(printf '%x' $OFFSET))"

# Get disk ID
DISK_ID=$(get_disk_id "$DISK_SLOT")
if [[ -z "$DISK_ID" ]]; then
    echo "WARNING: No disk ID found for slot $DISK_SLOT"
else
    echo "Disk ID: $DISK_ID"
fi

# Read current state
CURRENT_STATE=$(read_state "$OFFSET")
echo "Current state: $CURRENT_STATE"

case $CURRENT_STATE in
    $STATE_EMPTY)
        echo "Status: EMPTY (no disk assigned)"
        echo "Nothing to fix - slot is empty"
        exit 0
        ;;
    $STATE_DSBL)
        echo "Status: DISK_DSBL (disabled)"
        ;;
    $STATE_OK)
        echo "Status: DISK_OK (valid)"
        echo "Disk is already OK - nothing to fix"
        exit 0
        ;;
    *)
        echo "Status: UNKNOWN ($CURRENT_STATE)"
        echo "ERROR: Unknown disk state - aborting for safety"
        exit 1
        ;;
esac

# Check array state
ARRAY_STATE=$(grep "mdState=" /proc/mdstat 2>/dev/null | cut -d= -f2 || echo "UNKNOWN")
echo ""
echo "Array state: $ARRAY_STATE"

if [[ "$ARRAY_STATE" == "STARTED" ]]; then
    echo ""
    echo "Array is running - stopping it first..."
    
    # Stop docker containers to release mounts
    echo "Stopping docker containers..."
    docker stop $(docker ps -q) 2>/dev/null || true
    sleep 2
    
    # Lazy unmount user shares
    echo "Unmounting user shares..."
    umount -l /mnt/user 2>/dev/null || true
    
    # Stop the array
    echo "Stopping array..."
    /usr/local/sbin/emcmd cmdStop=Stop
    
    # Wait for array to stop
    echo -n "Waiting for array to stop"
    for i in {1..60}; do
        sleep 2
        ARRAY_STATE=$(grep "mdState=" /proc/mdstat 2>/dev/null | cut -d= -f2 || echo "UNKNOWN")
        if [[ "$ARRAY_STATE" == "STOPPED" ]]; then
            echo ""
            echo "Array stopped."
            break
        fi
        echo -n "."
    done
    
    if [[ "$ARRAY_STATE" != "STOPPED" ]]; then
        echo ""
        echo "ERROR: Array did not stop (state: $ARRAY_STATE)"
        echo "Check for processes blocking unmount with: fuser -vm /mnt/user"
        exit 1
    fi
fi

# Create backup
BACKUP="$SUPER_DAT.backup.$(date +%Y%m%d_%H%M%S)"
echo ""
echo "Creating backup: $BACKUP"
cp "$SUPER_DAT" "$BACKUP"

# Patch the superblock
echo "Patching superblock: changing state from $CURRENT_STATE to $STATE_OK"
printf "\\x$(printf '%02x' $STATE_OK)" | dd of="$SUPER_DAT" bs=1 seek="$OFFSET" count=1 conv=notrunc 2>/dev/null

# Verify the change
NEW_STATE=$(read_state "$OFFSET")
if [[ "$NEW_STATE" -eq "$STATE_OK" ]]; then
    echo "SUCCESS: Disk state changed to OK ($NEW_STATE)"
else
    echo "ERROR: Failed to change state (got $NEW_STATE, expected $STATE_OK)"
    echo "Restoring backup..."
    cp "$BACKUP" "$SUPER_DAT"
    exit 1
fi

echo ""
echo "=== Starting Array ==="
echo "Starting array with 'Parity is already valid'..."

# Start the array - use curl to hit the WebUI endpoint with parity valid flag
curl -s "http://localhost/update.htm" -X POST -d "cmdStart=Start&md_invalidslot=99" > /dev/null 2>&1

# Wait for array to start
echo -n "Waiting for array to start"
for i in {1..60}; do
    sleep 2
    ARRAY_STATE=$(grep "mdState=" /proc/mdstat 2>/dev/null | cut -d= -f2 || echo "UNKNOWN")
    if [[ "$ARRAY_STATE" == "STARTED" ]]; then
        echo ""
        echo "Array started!"
        break
    fi
    echo -n "."
done

if [[ "$ARRAY_STATE" != "STARTED" ]]; then
    echo ""
    echo "WARNING: Array may not have started automatically."
    echo "Please start it manually from WebUI: http://$(hostname -I | awk '{print $1}')"
    echo "Check 'Parity is already valid' before starting."
fi

# Verify disk is accessible
MOUNT_PATH="/mnt/${DISK_NAME}"
if [[ -d "$MOUNT_PATH" ]]; then
    echo ""
    echo "=== Verification ==="
    echo "Disk mount: $MOUNT_PATH"
    ls "$MOUNT_PATH/" 2>/dev/null | head -5
    echo ""
    df -h "$MOUNT_PATH" 2>/dev/null
fi

echo ""
echo "Done!"
