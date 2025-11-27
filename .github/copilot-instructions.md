# Copilot Instructions for Takeout Script Project

## Environment Context

- **Host**: This environment is running directly on the Unraid server at 192.168.1.216
- **No SSH needed**: All commands run locally - do not use `ssh root@192.168.1.216`
- **Direct access**: All paths like `/mnt/user/appdata/takeout-script` are directly accessible

## Project Structure

- Docker containers for backup automation
- Python scripts for Google Takeout sync and Immich import
- PowerShell deployment scripts (for remote deployment from Windows)

## Common Operations

### Building and Deploying Containers

```bash
cd /mnt/user/appdata/takeout-script
docker-compose build
docker-compose up -d
```

### Checking Container Status

```bash
docker ps -a | grep takeout
docker logs -f takeout-backup
docker logs -f immich-import
```

### Testing Scripts

```bash
# Test server_backup.py
docker run --rm \
  -v /mnt/user/jumpdrive/gdrive/Takeout:/data/gdrive/Takeout \
  -v /mnt/user/backups/google-takeout/raw:/data/photos/import/Takeout \
  -v /mnt/user/appdata/rclone:/config/rclone \
  takeout-backup:latest

# Test immich_import.py
docker run --rm \
  -e IMMICH_API_URL='http://192.168.1.216:2283/api' \
  -v /mnt/user/backups/google-takeout/raw:/data/photos/import \
  -v /mnt/user/appdata/takeout-script/cache/.immich_api_key:/run/secrets/immich_api_key:ro \
  immich-import:latest
```

## Key Paths

- `/mnt/user/appdata/takeout-script/` - Application files
- `/mnt/user/jumpdrive/gdrive/Takeout/` - Synced from Google Drive
- `/mnt/user/backups/google-takeout/raw/` - Import staging area
- `/mnt/user/appdata/rclone/` - rclone config

## Deployment Notes

- When updating Python scripts, rebuild the affected Docker image
- Check logs after deployment to verify operation
- The PowerShell scripts are for remote deployment from Windows, not for use on this host


# Google Takeout to Immich Backup System

## Project Overview
Automated backup system that syncs Google Takeout exports to an Unraid server and imports Google Photos content into Immich using Docker containers.

## Server Configuration
- **Platform**: Unraid
- **Docker**: Running on host network
- **Immich**: http://192.168.1.216:2283
- **Immich API**: http://192.168.1.216:2283/api
- **Immich API Key**: (stored in /mnt/user/appdata/takeout-script/cache/.immich_api_key)
- **API Key Location**: /mnt/user/appdata/takeout-script/cache/.immich_api_key
- **User Email**: (configured via Google account)

## Storage Architecture

### Host Paths
- **Takeout Sync**: /mnt/user/jumpdrive/gdrive/Takeout (all files from Google Drive Takeout folder)
- **Photos Import**: /mnt/user/backups/google-takeout/raw (Google Photos zips + media files)
- **Full Google Drive**: /mnt/user/jumpdrive/gdrive (entire Google Drive excluding Takeout)
- **rclone Config**: /mnt/user/appdata/rclone/rclone.conf
- **Project Files**: /mnt/user/appdata/takeout-script/

### Container Paths
- **takeout-backup**: 
  - /data/gdrive/Takeout → /mnt/user/jumpdrive/gdrive/Takeout
  - /data/photos/import/Takeout → /mnt/user/backups/google-takeout/raw
  - /config/rclone → /mnt/user/appdata/rclone
  
- **gdrive-backup**:
  - /mnt/user/jumpdrive/gdrive → /mnt/user/jumpdrive/gdrive
  - /config/rclone → /mnt/user/appdata/rclone
  
- **immich-import**:
  - /data/photos/import/Takeout → /mnt/user/backups/google-takeout/raw (read-write for deletion)
  - /run/secrets/immich_api_key → /mnt/user/appdata/takeout-script/cache/.immich_api_key (read-only)

## Docker Services

### takeout-backup
- **Image**: takeout-backup:latest (Python 3.12-slim + rclone)
- **Purpose**: Syncs Google Takeout folder, inspects zips for Google Photos content, copies media files
- **Script**: server_backup.py
- **Restart**: unless-stopped (continuous monitoring)
- **Check Interval**: 3600 seconds (1 hour)
- **rclone Remote**: gdrive:Takeout

### gdrive-backup
- **Image**: gdrive-backup:latest (inherits from takeout-backup)
- **Purpose**: Syncs entire Google Drive excluding Takeout folder
- **Script**: gdrive_backup.py
- **Restart**: "no" (cron job only)
- **Cron Schedule**: Daily at 4:00 AM (`0 4 * * *`)
- **Log**: /var/log/gdrive-backup.log

### immich-import
- **Image**: immich-import:latest (Python 3.12-slim + immich-go v0.31.0)
- **Purpose**: Monitors for Google Photos zips, imports to Immich, deletes after successful import
- **Script**: immich_import.py
- **Restart**: unless-stopped (continuous monitoring)
- **Check Interval**: 300 seconds (5 minutes)
- **Tool**: immich-go CLI for Google Photos import

## File Processing Logic

### server_backup.py
1. Syncs all files from gdrive:Takeout to /data/gdrive/Takeout
2. Inspects each .zip file using Python zipfile module
3. Checks for "Google Photos" or "Google Foto's" directories in zip
4. Copies Google Photos zips to /data/photos/import/Takeout
5. Copies all media files (photos/videos) to /data/photos/import/Takeout
6. Preserves directory structure using relative paths
7. Only copies if destination doesn't exist or sizes differ

### immich_import.py
1. Recursively scans /data/photos/import/Takeout for .zip files
2. For each zip file:
   - Runs `immich-go upload from-google-photos -s SERVER -k API_KEY zipfile.zip`
   - If import succeeds (returncode 0), deletes the zip file
   - If import fails, leaves zip file for retry on next cycle
3. No state tracking - processes all zips found on each cycle
4. Uses Path.rglob("*") to find zips recursively

### gdrive_backup.py
1. Syncs entire Google Drive to /mnt/user/jumpdrive/gdrive
2. Excludes Takeout folder using rclone filter: --exclude "Takeout/**"
3. Runs only when triggered by cron (not continuous)

## Supported Media Formats
- **Images**: .jpg, .jpeg, .png, .gif, .bmp, .tiff, .tif, .webp, .heic, .heif, .raw, .cr2, .nef, .arw, .dng
- **Videos**: .mp4, .mov, .avi, .mkv, .wmv, .flv, .webm, .m4v, .3gp, .3g2, .mpeg, .mpg, .mts, .m2ts

## Deployment

### Build and Deploy All Services
```bash
cd /mnt/user/appdata/takeout-script
docker-compose down
docker-compose build
docker-compose up -d
```

### Deploy Individual Service
```bash
docker-compose build immich-import
docker-compose up -d --force-recreate immich-import
```

### Monitor Logs
```bash
docker logs -f takeout-backup
docker logs -f immich-import
docker logs --tail 50 gdrive-backup
```

### Cron Configuration
```bash
crontab -l  # View current cron jobs
crontab -e  # Edit cron jobs
```

## PowerShell Scripts

### create-immich-api-key.ps1
Automates Immich API key generation via REST API:
1. Login to Immich with credentials
2. Create API key with "all" permissions
3. Save to /mnt/user/appdata/takeout-script/cache/.immich_api_key

### deploy-*.ps1
Legacy deployment scripts (consider consolidating into one script)

### configure-rclone.ps1
Sets up rclone with Google Drive OAuth

### test-and-schedule.ps1
Testing and scheduling utilities

## Docker Images

### Dockerfile (takeout-backup)
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y rclone
WORKDIR /app
COPY server_backup.py /app/
RUN mkdir -p /config/rclone
CMD ["python", "/app/server_backup.py"]
```

### Dockerfile.gdrive (gdrive-backup)
```dockerfile
FROM takeout-backup:latest
WORKDIR /app
COPY gdrive_backup.py /app/
CMD ["python", "/app/gdrive_backup.py"]
```

### Dockerfile.immich (immich-import)
```dockerfile
FROM python:3.12-slim
WORKDIR /tmp
RUN wget https://github.com/simulot/immich-go/releases/latest/download/immich-go_Linux_x86_64.tar.gz
RUN tar -xzf immich-go.tar.gz && mv immich-go /usr/local/bin/
WORKDIR /app
COPY immich_import.py /app/
CMD ["python", "/app/immich_import.py"]
```

## Troubleshooting

### Check Container Status
```bash
docker ps | grep -E 'takeout-backup|gdrive-backup|immich-import'
docker inspect <container_id>
```

### Verify Volume Mounts
```bash
docker exec takeout-backup ls -la /data/gdrive/Takeout
docker exec immich-import ls -la /data/photos/import/Takeout
```

### Test rclone Connection
```bash
docker exec takeout-backup rclone lsd gdrive:Takeout
```

### Test Immich API
```bash
curl -s http://192.168.1.216:2283/api/server/ping
```

### Check immich-go Version
```bash
docker exec immich-import immich-go --version
```

### Common Issues
1. **Read-only filesystem errors**: Ensure volume is not mounted with `:ro` flag
2. **Missing API key**: Verify /mnt/user/appdata/takeout-script/cache/.immich_api_key exists
3. **rclone authentication**: Check /mnt/user/appdata/rclone/rclone.conf
4. **Broken pipe errors**: Network timeout, immich-go will retry on next cycle
5. **Pending assets warning**: Normal for large uploads, assets will complete in background

## Environment Variables
- **RCLONE_CONFIG**: Path to rclone.conf (default: /config/rclone/rclone.conf)
- **CHECK_INTERVAL**: Seconds between sync checks (takeout-backup: 3600, immich-import: 300)
- **IMMICH_API_URL**: Immich API endpoint (default: http://192.168.1.216:2283/api)
- **IMMICH_API_KEY_FILE**: Path to API key file (default: /run/secrets/immich_api_key)

## Current Status
- All services deployed and running
- takeout-backup: Actively syncing 929 GB from Google Drive (1% complete, ETA ~4 days)
- immich-import: Successfully processed 6 zip files, importing photos continuously
- gdrive-backup: Scheduled for daily execution at 4:00 AM
- No state tracking - processes all files found on each cycle
- Files deleted after successful import (requires read-write volume mount)
