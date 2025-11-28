# Copilot Instructions for Takeout Script Project

## Environment Context

- **Host**: This environment is running directly on the Unraid server at 192.168.1.216
- **No SSH needed**: All commands run locally - do not use `ssh root@192.168.1.216`
- **Direct access**: All paths like `/mnt/user/appdata/takeout-script` are directly accessible

## Project Overview

Automated Google Photos backup system that:
1. **Automates Google Takeout creation** via browser automation (Playwright)
2. **Syncs Takeout exports** from Google Drive to local storage (rclone)
3. **Imports Google Photos** into Immich with full metadata (immich-go)
4. **Tracks import metadata** with a web viewer for auditing

All services are scheduled via **Chadburn** (Docker-native cron scheduler) labels.

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

### Utilities

| Service | Schedule | Purpose |
|---------|----------|---------|
| `metadata-viewer` | Always running | Web UI for viewing import metadata (port 5050) |
| `sd-import` | Manual trigger | Imports from SD cards/folders to Immich |

---

## Key Paths

### Host Paths
| Path | Purpose |
|------|---------|
| `/mnt/user/appdata/takeout-script/` | Project files |
| `/mnt/user/jumpdrive/gdrive/Takeout/` | Synced Takeout exports |
| `/mnt/user/jumpdrive/gdrive/` | Full Google Drive sync |
| `/mnt/user/jumpdrive/imports/metadata/` | Import metadata JSON files |
| `/mnt/user/jumpdrive/imports/extracted/` | Extracted non-photos content |
| `/mnt/user/appdata/rclone/` | rclone config |
| `/mnt/user/appdata/gphotos/chromeuser/` | Playwright browser profile |
| `/mnt/user/appdata/takeout-script/cache/.immich_api_key` | Immich API key |

### Environment Variables (.env file)
```bash
IMMICH_SERVER=http://192.168.1.216:2283
SERVER_IP=192.168.1.216
VNC_PASSWORD=<password>
kasmweb_version=1.18.0
```

---

## Shared Module: `shared/takeout_utils.py`

Central utility module used by multiple services:

### Key Classes
- **`ImmichGoRunner`**: Unified immich-go upload with retry logic (3 retries, 30s delay)
- **`ImportProcessor`**: Orchestrates import + extraction + metadata creation
- **`MetadataBuilder`**: Creates JSON metadata files for each import

### Key Functions
- `parse_immich_go_log()`: Parses immich-go JSON logs for per-file results
- `get_zip_contents()`: Lists files in zip with media detection
- `extract_non_imported_from_zip()`: Extracts files that weren't imported to Immich

### Configuration via Environment
```python
DEFAULT_IMMICH_SERVER = os.getenv("IMMICH_SERVER", "http://192.168.1.216:2283")
DEFAULT_METADATA_DIR = Path(os.getenv("METADATA_DIR", "/data/metadata"))
DEFAULT_EXTRACT_DIR = Path(os.getenv("EXTRACT_DIR", "/data/extracted"))
DEFAULT_MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
DEFAULT_RETRY_DELAY = int(os.getenv("RETRY_DELAY", "30"))
```

---

## Processing Logic

### takeout-backup (server_backup.py)
1. Runs `rclone move gdrive:Takeout` to local storage
2. Scans for .zip files
3. **Google Photos zips**: Left for immich-import to process
4. **Other zips**: Extracted locally, verified, originals deleted
5. Saves extraction metadata to `/data/metadata/`

### immich-import (immich_import.py)
1. Finds `takeout-*.zip` files in import directory
2. Groups multi-part archives by prefix (e.g., `takeout-20240427T195310Z-001.zip`)
3. Runs `immich-go upload from-google-photos` with flags:
   - `--sync-albums`, `--people-tag`, `--takeout-tag`, `--session-tag`
   - `--manage-raw-jpeg=StackCoverRaw`, `--manage-burst=Stack`
4. Parses JSON log for per-file results
5. Extracts non-Google-Photos content to `/data/extracted/`
6. Saves metadata JSON with full file manifest
7. Deletes zips only if import succeeded with no errors

### automated-takeout (automated_takeout.py)
1. Loads album list from `album_state.yml`
2. Launches Playwright with persistent Chrome profile
3. Navigates to Google Takeout, selects Google Photos
4. Creates exports for albums needing backup:
   - Large albums (Photos from YYYY): Individual exports
   - Small albums: Batched together
5. Exports saved to Google Drive, synced by takeout-backup

---

## Common Operations

### Build and Deploy All Services
```bash
cd /mnt/user/appdata/takeout-script
docker compose build
docker compose up -d
```

### Deploy Individual Service
```bash
docker compose build immich-import
docker compose up -d --force-recreate immich-import
```

### Monitor Logs
```bash
docker logs -f takeout-backup
docker logs -f immich-import
docker logs -f automated-takeout
```

### Test Python Scripts
```bash
cd /mnt/user/appdata/takeout-script
python3 -m py_compile shared/takeout_utils.py
python3 -m py_compile immich-import/immich_import.py
```

### Access Metadata Viewer
```
http://192.168.1.216:5050
```

### Manual Login (when Google session expires)
1. Start login-helper with VNC:
   ```bash
   docker compose up -d login-helper
   ```
2. Open VNC: `http://192.168.1.216:6901`
3. Log in to Google in the browser
4. Stop container when done

---

## Troubleshooting

### Check Service Status
```bash
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

### Test Immich Connection
```bash
curl -s http://192.168.1.216:2283/api/server/ping
```

### Test rclone Connection
```bash
docker exec takeout-backup rclone lsd gdrive:Takeout
```

### Check immich-go Version
```bash
docker exec immich-import immich-go --version
```

### View Import Logs
```bash
ls -la /mnt/user/jumpdrive/imports/metadata/logs/
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Google login expired | Use login-helper VNC to re-authenticate |
| immich-go errors | Check logs in metadata/logs/, retry runs automatically |
| Zip not processing | Verify zip has "Google Photos" folder inside |
| API key missing | Check `/mnt/user/appdata/takeout-script/cache/.immich_api_key` |
| rclone auth failed | Re-run rclone config, update `/mnt/user/appdata/rclone/rclone.conf` |

---

## Metadata Files

Each import creates a `.metadata.json` file with:
- Source zip files (names, sizes)
- Complete file manifest with per-file status
- immich-go results (uploaded, duplicates, errors)
- Albums and tags discovered
- Import timing and command used

Example structure:
```json
{
  "import_type": "immich-go",
  "source_type": "google-photos",
  "source_name": "takeout-20240427T195310Z",
  "zip_files": [{"name": "...", "size": 1234567}],
  "files": [{"filename": "IMG_001.jpg", "immich_status": "uploaded", ...}],
  "summary": {"uploaded_success": 150, "server_duplicate": 20, "errors": 0},
  "immich_go_results": {...}
}
```

---

## Docker Image Details

| Image | Base | Key Tools |
|-------|------|-----------|
| `takeout-backup` | python:3.12-slim | rclone, unzip |
| `immich-import` | python:3.12-slim | immich-go (latest) |
| `gdrive-backup` | python:3.12-slim | rclone |
| `automated-takeout` | python:3.12-slim | playwright, chromium |
| `login-helper` | kasmweb/chrome | playwright, VNC |
| `metadata-viewer` | python:3.12-slim | flask |
| `sd-import` | python:3.12-slim | immich-go |
| `version-watcher` | python:3.12-slim | requests |

---

## Scheduling (Chadburn Labels)

Services use Docker labels for scheduling:
```yaml
labels:
  - "chadburn.enabled=true"
  - "chadburn.job-exec.SERVICE.schedule=CRON_EXPRESSION"
  - "chadburn.job-exec.SERVICE.command=python /app/script.py"
```

Requires Chadburn container running separately to execute scheduled jobs.
