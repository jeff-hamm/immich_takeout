# SD Card Auto-Import for Unraid

Automatically detects, copies, and imports photos from SD cards to Immich when inserted into your Unraid server.

## Features

- **Auto-detection**: Triggers automatically when SD card is inserted
- **Smart copying**: Copies all files from all mountable partitions
- **Duplicate prevention**: Tracks imported files on the SD card to avoid re-importing
- **Immich integration**: Automatically uploads to Immich after copying
- **Persistent**: Survives Unraid reboots via `/boot/config` storage

## Installation

1. Copy this directory to your Unraid server (e.g., `/mnt/user/appdata/takeout-script/sd-import/`)

2. Run the installer as root:
   ```bash
   cd /mnt/user/appdata/takeout-script/sd-import/
   ./install.sh
   ```

3. The installer will:
   - Copy scripts to `/boot/config/custom-scripts/` (persistent storage)
   - Install the udev rule to detect SD card insertion
   - Update the `/boot/config/go` script to reinstall on each boot
   - Create the import directory at `/mnt/user/jumpdrive/imports/`

## Configuration

### Immich Configuration

The system uses Docker to run immich-go, so no additional installation is needed.

To enable automatic upload to Immich, set the `IMMICH_API_KEY` and optionally `IMMICH_SERVER` environment variables:

```bash
# Add to /boot/config/go after the sd-card-import installation lines
export IMMICH_API_KEY="your-api-key-here"
export IMMICH_SERVER="http://192.168.1.128:2283"  # Optional, defaults to this
```

The wrapper script (`immich-go.sh`) will automatically pull and run the immich-go Docker container when needed.

### SD Card Detection

The default configuration detects SD cards with serial: `Generic-_SD_MMC_MS_PRO_20120926571200000-0:0`

To change this, edit `99-sd-card-import.rules` and update the `ATTRS{serial}` value.

## How It Works

1. When an SD card is inserted, udev triggers the import script
2. Script mounts all readable partitions
3. Files are copied to `/mnt/user/jumpdrive/imports/YYYY-MM-DD_HHMMSS/partition_name/`
4. Successfully copied files are tracked in `.immich_imported.txt` on the SD card
5. If `IMMICH_API_KEY` is set, immich-go uploads the files to Immich
6. All activity is logged to `/var/log/sd-card-import.log`

## Files

- `install.sh` - Installation script
- `sd-card-import.sh` - Main import script
- `immich-go.sh` - Docker wrapper for immich-go
- `99-sd-card-import.rules` - Udev rule for auto-detection

## Monitoring

View real-time import activity:
```bash
tail -f /var/log/sd-card-import.log
```

## Troubleshooting

- Check logs: `/var/log/sd-card-import.log`
- Verify udev rule is loaded: `udevadm control --reload-rules`
- Test manually: `/usr/local/bin/sd-card-import.sh sdd` (replace sdd with your device)
- Check if device is detected: `lsblk` and `udevadm info --query=all --name=/dev/sdd`

## Uninstallation

1. Remove from go script: Edit `/boot/config/go` and remove the sd-card-import lines
2. Remove files:
   ```bash
   rm /boot/config/custom-scripts/sd-card-import.sh
   rm /boot/config/custom-scripts/99-sd-card-import.rules
   rm /usr/local/bin/sd-card-import.sh
   rm /etc/udev/rules.d/99-sd-card-import.rules
   udevadm control --reload-rules
   ```
