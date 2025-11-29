# Unraid Customization Files

This directory contains customizations that need to be installed on Unraid's flash drive for persistence across reboots.

## Contents

### `go` - Boot Script
The Unraid boot script that runs after the array starts. Contains:
- SD card auto-import installation (udev rules, scripts)
- Failed drive hiding (udev rules)
- Persistent symlinks for VS Code Server
- Profile fixes (removes `cd $HOME` that breaks SSH)
- Custom bashrc installation with Docker aliases

### `bashrc` - Custom Shell Configuration
Docker convenience aliases and functions:
- `d` - shortcut for `docker`
- `dc` - shortcut for `docker-compose`
- `dcb` - docker-compose build
- `dcu` - docker-compose up -d
- `dcl` - docker-compose logs -f
- `dcr <service>` - full deploy workflow: build + up --force-recreate + logs -f

## Installation

These files are installed by `install.sh` in the parent directory. They can also be manually installed:

```bash
# Copy to Unraid flash drive
cp go /boot/config/go
mkdir -p /boot/config/custom-scripts
cp bashrc /boot/config/custom-scripts/bashrc

# Apply immediately (optional - happens automatically on reboot)
source /boot/config/go
```

## Important Notes

1. **Flash Drive Persistence**: Only files on `/boot/config/` survive reboots on Unraid
2. **The `go` file**: Runs once at boot after the array is started
3. **Custom scripts location**: `/boot/config/custom-scripts/` is copied to `/usr/local/bin/` at boot
4. **API Key Security**: The IMMICH_API_KEY in `go` is for SD card imports only

## Related Files on Flash Drive

The install script also creates/manages:
- `/boot/config/custom-scripts/sd-card-import.sh` - SD card import script
- `/boot/config/custom-scripts/immich-go.sh` - immich-go wrapper
- `/boot/config/custom-scripts/99-sd-card-import.rules` - udev rule for SD cards
