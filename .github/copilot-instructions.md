# Copilot Instructions for Takeout Script Project

## ⚠️ IMPORTANT RULES

### Command Restrictions
- **NEVER use `/dev/null`, `\dev\null` or `/tmp`** in any commands - the user cannot auto-approve commands containing these paths
- Use alternatives like `> .tmp/output.txt` or simply omit output redirection when possible

### Environment Context
- **Host**: Running directly on Unraid server at 192.168.1.216
- **No SSH needed**: All commands run locally - do NOT use `ssh root@192.168.1.216`
- **Direct access**: All paths like `$APP_PATH` are directly accessible

### Shell Aliases Available
```bash
d='docker'
dc='docker-compose'
dcb='docker-compose build'
dcu='docker-compose up -d'
dcl='docker-compose logs -f'
dcr <service>  # Build + up --force-recreate + logs -f (full deploy workflow)
```

---

## Project Overview

Automated Google Photos backup system with these core functions:
1. **Automates Google Takeout creation** via Playwright browser automation
2. **Syncs Takeout exports** from Google Drive to local storage via rclone
3. **Imports Google Photos** into Immich with full metadata via immich-go
4. **Tracks import metadata** with a Flask web viewer for auditing
5. **SD Card auto-import** via udev rules triggering immich-go uploads

---

## Docker Services (8 total)

### Core Import Pipeline

| Service | Schedule | Purpose |
|---------|----------|---------|
| `takeout-backup` | Daily 4:00 AM | Syncs Takeout folder from Google Drive, extracts non-photos zips |
| `immich-import` | Every 15 min | Imports Google Photos zips to Immich using immich-go |
| `gdrive-backup` | Daily 5:00 AM | Syncs entire Google Drive (excluding Takeout folder) |

### Automation & Login

| Service | Schedule | Purpose |
|---------|----------|---------|
| `automated-takeout` | Daily 1:10 AM | Creates new Google Takeout exports via Playwright |
| `login-helper` | Daily 1:05 AM | Checks Google login status, provides VNC for re-auth |
| `version-watcher` | Daily 1:00 AM | Updates kasmweb/chrome base image version |
| `vscode-monitor` | Daily 1:40 AM | Monitors automated-takeout for failures, auto-fixes Playwright scripts |

### Utilities

| Service | Schedule | Purpose |
|---------|----------|---------|
| `metadata-viewer` | Always running | Web UI for viewing import metadata (port 5050) |

### Host-Level (Non-Docker)

| Component | Trigger | Purpose |
|-----------|---------|---------|
| SD Card Import | udev on insert | Auto-imports SD cards to Immich via immich-go wrapper |

---

## Directory Structure

```
$APP_PATH/
├── .github/                    # GitHub config, copilot instructions
├── shared/                     # Shared Python modules (mounted into containers)
│   ├── takeout_utils.py        # Core utilities, constants, zip handling
│   ├── immich_go_runner.py     # ImmichGoRunner class with retry logic
│   ├── import_metadata.py      # ImportMetadata class for tracking
│   └── import_processor.py     # ImportProcessor orchestration
├── immich-import/              # Google Photos zip importer
├── takeout-backup/             # rclone sync from Google Drive
├── gdrive-backup/              # Full Google Drive sync
├── automated-takeout/          # Playwright automation for Takeout creation
├── login-helper/               # VNC-enabled browser for Google auth
├── metadata-viewer/            # Flask web UI for import history
├── version-watcher/            # Docker image version checker
├── vscode-monitor/             # AI-powered Playwright script fixer
├── sd-import/                  # SD card udev rules and scripts
├── unraid/                     # Unraid customization files (go, bashrc)
├── scripts/                    # Utility scripts (resume_immich_jobs.py)
├── state/                      # Persistent state files (.immich_api_key)
└── docker-compose.yml
```

---

## Key Paths

### Host Paths
| Path | Purpose |
|------|---------|
| `$APP_PATH/` | Project source files |
| `/mnt/user/jumpdrive/imports/` | Import working directory |
| `/mnt/user/jumpdrive/imports/Takeout/` | Synced Google Takeout zips |
| `/mnt/user/jumpdrive/imports/metadata/` | Import metadata JSON files |
| `/mnt/user/jumpdrive/imports/metadata/logs/` | immich-go JSON log files |
| `/mnt/user/jumpdrive/imports/extracted/` | Extracted non-photos content |
| `/mnt/user/jumpdrive/gdrive/` | Full Google Drive sync |
| `${APP_ROOT}/rclone/` | rclone config |
| `${APP_ROOT}/gphotos/chromeuser/` | Playwright browser profile |

### Container Mount Points
| Container Path | Host Path |
|----------------|-----------|
| `/data/import/` | `/mnt/user/jumpdrive/imports/` |
| `/data/metadata/` | `/mnt/user/jumpdrive/imports/metadata/` |
| `/data/extracted/` | `/mnt/user/jumpdrive/imports/extracted/` |
| `/app/shared/` | `./shared/` (bind mount) |

---

## Shared Python Modules

### `shared/takeout_utils.py`
Core utilities and constants:
- `get_zip_contents()`: Lists files in zip with media detection
- `get_folder_contents()`: Lists files in folder with media detection  
- `parse_log_entry()`: Parses single immich-go JSON log entry
- `parse_immich_go_log()`: Parses complete log file
- `file_result_to_manifest_entry()`: Converts log entry to manifest format
- `get_immich_api_key()`: Reads API key from file
- Default constants: `DEFAULT_IMMICH_SERVER`, `DEFAULT_METADATA_DIR`, etc.

### `shared/immich_go_runner.py`
`ImmichGoRunner` class:
- Unified immich-go upload with retry logic (3 retries, 30s delay)
- Real-time log file tailing with callbacks
- Heartbeat mechanism for long-running imports (updates metadata every 30s)
- Discovery progress logging with percentage
- Methods: `upload_google_photos()`, `upload_folder()`

### `shared/import_metadata.py`
`ImportMetadata` class (extends dict):
- Self-saving metadata with atomic writes (temp file + fsync + rename)
- Tracks import status, file manifest, results
- Constructor handles zip files, folders, or extraction-only
- Methods: `save()`, `update_status()`, `load()`

### `shared/import_processor.py`
`ImportProcessor` class:
- Orchestrates complete import workflow
- Handles zip or folder imports
- Extracts non-imported content
- Updates metadata on completion

---

## Processing Logic

### immich-import Workflow
1. Scans `/data/import/Takeout/` for `takeout-*.zip` files
2. Groups multi-part archives by prefix (e.g., `takeout-20240427T195310Z-*.zip`)
3. Creates `ImportMetadata` with file manifest from zip contents
4. Runs `ImmichGoRunner.upload_google_photos()` with real-time callbacks
5. Callbacks update metadata with per-file results as they arrive
6. Heartbeat saves metadata every 30s even during quiet periods
7. On completion, updates final status and summary
8. Deletes zips only if import succeeded with no errors

### SD Card Import Workflow
1. udev rule triggers on SD card insert (`ACTION=="add|change"`)
2. Lock file prevents concurrent runs
3. `sd-card-import.sh` mounts card and runs immich-go wrapper
4. `immich-go-upload.sh` calls immich-go with appropriate flags
5. Unmounts card when done

---

## Common Operations

### Build and Deploy
```bash
# Single service (recommended)
dcr immich-import   # Build + restart + tail logs

# Or manually:
dc build immich-import
dc up -d --force-recreate immich-import
dcl immich-import

# All services
dc build && dc up -d
```

### Monitor Logs
```bash
dcl immich-import          # Follow logs
dc logs --tail 50 immich-import  # Last 50 lines
```

### Test Python Syntax
```bash
python3 -m py_compile shared/immich_go_runner.py
python3 -m py_compile immich-import/immich_import.py
```

### Immich Job Control
```bash
# Check job status
curl -s -H "x-api-key: $(cat state/.immich_api_key)" \
  http://192.168.1.216:2283/api/jobs | python3 -m json.tool

# Resume paused jobs
python3 scripts/resume_immich_jobs.py resume
```

### Access Web UIs
- **Metadata Viewer**: http://192.168.1.216:5050
- **Immich**: http://192.168.1.216:2283
- **Login Helper VNC**: http://192.168.1.216:6901

---

## Metadata Viewer Features

Flask web UI at port 5050:
- **Dashboard**: Aggregated stats, import list sorted by last modified
- **Detail View**: Full file manifest, per-file status, albums, tags
- **Logs Tab**: View immich-go JSON logs
- **Timeout Detection**: Shows "timeout" if status is running but no updates for 2 minutes

---

## SD Card Auto-Import

### Files in `sd-import/`
- `99-sd-card-import.rules`: udev rule for card detection
- `sd-card-import.sh`: Main script triggered by udev (with lock file)
- `immich-go-upload.sh`: immich-go wrapper called from import script
- `install.sh`: Installs scripts to Unraid

### Persistence on Unraid
Scripts are copied to `/boot/config/custom-scripts/` and installed via `/boot/config/go`:
```bash
# In /boot/config/go
cp /boot/config/custom-scripts/sd-card-import.sh /usr/local/bin/
cp /boot/config/custom-scripts/99-sd-card-import.rules /etc/udev/rules.d/
```

---

## Troubleshooting

### Check Container Status
```bash
d ps -a --format "table {{.Names}}\t{{.Status}}"
```

### Validate Metadata JSON
```bash
python3 -c "import json; json.load(open('file.metadata.json'))"
```

### Test Immich Connection
```bash
curl -s http://192.168.1.216:2283/api/server/ping
```

### Check immich-go Version
```bash
docker exec immich-import immich-go --version
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Import stuck/timeout | Check if immich-go process running, look at JSON log |
| Metadata shows "timeout" | Heartbeat not updating - may need container restart |
| Corrupted metadata JSON | Usually concurrent write issue - check for `.tmp` files |
| SD card not triggering | Check udev rule, `udevadm monitor`, log at `/var/log/sd-card-import.log` |
| Google login expired | Use login-helper VNC at port 6901 to re-auth |
| Immich jobs paused | Run `python3 scripts/resume_immich_jobs.py resume` |

---

## Environment Variables

### .env File
```bash
IMMICH_SERVER=http://192.168.1.216:2283
SERVER_IP=192.168.1.216
VNC_PASSWORD=<password>
kasmweb_version=1.18.0
```

### Container Environment
```bash
METADATA_DIR=/data/metadata
EXTRACT_DIR=/data/extracted
MAX_RETRIES=3
RETRY_DELAY=30
PAUSE_IMMICH_JOBS=true
```

---

## Scheduling (Chadburn)

Services use Docker labels for cron scheduling:
```yaml
labels:
  - "chadburn.enabled=true"
  - "chadburn.job-exec.immich-import.schedule=0 */15 * * * *"
  - "chadburn.job-exec.immich-import.command=python /app/immich_import.py"
```

Requires Chadburn container running to execute scheduled jobs.
