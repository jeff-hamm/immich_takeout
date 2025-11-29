# Immich Takeout - Automated Google Takeout to Immich Backup System

A comprehensive automation system for backing up Google Photos to [Immich](https://immich.app) via Google Takeout exports. Designed for Unraid but adaptable to any Docker host.

## Features

- **Automated Google Takeout Creation**: Browser automation to create and manage Google Takeout exports for specific photo albums
- **Google Drive Sync**: Automatic syncing of Takeout exports from Google Drive using rclone
- **Immich Import**: Automatic import of Google Photos ZIP files into Immich using immich-go
- **SD Card Auto-Import**: Automatic detection and import of photos from SD cards when inserted
- **Login Management**: Automated Google login verification and VNC-based manual login helper
- **Smart Scheduling**: Cron-based scheduling for all automation tasks

## Quick Start

1. Copy `.env.example` to `.env` and configure your settings
2. Run `./configure-rclone.ps1` to set up Google Drive access
3. Run `./create-immich-api-key.ps1` to generate your Immich API key
4. Start login-helper: `docker-compose up -d login-helper` and log into Google via VNC
5. Create `cache/album_state.yml` with your albums to export
6. Start all services: `docker-compose up -d`

See full installation guide below for details.

## Documentation

- [Installation Guide](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [SD Card Import](sd-import/README.md)
- [Troubleshooting](#troubleshooting)

## Architecture

### Docker Services

1. **automated-takeout**: Playwright-based browser automation to create Google Takeout exports
2. **takeout-backup**: Syncs Google Drive Takeout folder using rclone
3. **gdrive-backup**: Full Google Drive backup (excluding Takeout folder)
4. **immich-import**: Monitors for and imports Google Photos ZIPs using immich-go
5. **login-helper**: VNC-enabled Chrome for manual Google login when needed
6. **version-watcher**: Monitors for updates to KasmWeb Chrome image

### Default Storage Paths (Unraid)

- `/mnt/user/jumpdrive/gdrive/Takeout` - Synced Google Takeout folder
- `/mnt/user/jumpdrive/gdrive` - Full Google Drive backup
- `/mnt/user/backups/google-takeout/raw` - Import staging for Google Photos
- `${APP_ROOT}/rclone` - rclone configuration
- `${APP_ROOT}/state/chromeuser` - Browser profile
- `$APP_PATH/state` - API keys and state files

## Installation

### Prerequisites

- Docker and Docker Compose
- [Immich](https://immich.app) server running
- Google account with photos to backup
- rclone configured with Google Drive access

### Setup Steps

1. **Clone repository**
   \`\`\`bash
   git clone https://github.com/jeff-hamm/immich_takeout.git
   cd immich_takeout
   \`\`\`

2. **Configure environment**
   \`\`\`bash
   cp .env.example .env
   nano .env
   \`\`\`

3. **Configure rclone** (PowerShell)
   \`\`\`powershell
   .\configure-rclone.ps1 -Server YOUR_SERVER_IP
   \`\`\`

4. **Create Immich API key**
   \`\`\`powershell
   .\create-immich-api-key.ps1 -Server YOUR_SERVER_IP
   \`\`\`

5. **Set up Google login**
   \`\`\`bash
   docker-compose up -d login-helper
   # Access VNC at http://YOUR_SERVER_IP:6901
   \`\`\`

6. **Create album state file**
   \`\`\`bash
   nano $APP_PATH/state/album_state.yml
   \`\`\`

7. **Start services**
   \`\`\`bash
   docker-compose up -d
   \`\`\`

## Configuration

### Environment Variables

\`\`\`env
# KasmWeb Chrome version
kasmweb_version=1.18.0

# Immich server URL
IMMICH_SERVER=http://192.168.1.216:2283

# Server IP for VNC
SERVER_IP=192.168.1.216

# VNC password
VNC_PASSWORD=password
\`\`\`

### Album State File

\`\`\`yaml
albums:
- name: "Photos from 2024"
  last_export_date: null
  is_large: true
\`\`\`

## Usage

### Automated Schedules

- **1:00 AM**: Version check
- **1:05 AM**: Login verification
- **1:10 AM**: Create Takeout exports
- **4:00 AM**: Sync from Google Drive
- **5:00 AM**: Full Drive backup
- **Every 15 min**: Import to Immich

### Manual Operations

\`\`\`bash
# Test takeout creation
docker-compose run --rm automated-takeout

# Sync from Drive
docker-compose run --rm takeout-backup

# Import photos
docker-compose run --rm immich-import

# View logs
docker-compose logs -f automated-takeout
\`\`\`

## Troubleshooting

### Check Logs

\`\`\`bash
docker-compose logs -f SERVICE_NAME
\`\`\`

### Common Issues

1. **Browser session expired**: Run login-helper
2. **rclone auth failed**: Re-run configure-rclone.ps1
3. **Import fails**: Verify API key in cache/.immich_api_key

## License

MIT License

## Credits

- [Immich](https://immich.app)
- [immich-go](https://github.com/simulot/immich-go)
- [Playwright](https://playwright.dev)
- [rclone](https://rclone.org)
- [KasmWeb](https://www.kasmweb.com)
