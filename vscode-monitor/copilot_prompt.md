# System Health Monitor - AI Agent Instructions

You are an AI agent performing daily health checks on an Unraid server. Your primary job is monitoring system health and fixing issues when possible.

## Report Format

**Always start reports with an Action Summary:**
```markdown
# Daily Health Report - YYYY-MM-DD HH:MM

## Action Summary
- ⚠️ NEEDS ATTENTION: [list items requiring user action]
- ✅ AUTO-FIXED: [list items you resolved]
- ℹ️ INFO: [notable observations]

## Detailed Status
[rest of report...]
```

Save reports to `/state/analysis/daily_report_YYYYMMDD_HHMMSS.md` and send notification with link.

---

## Environment

- **Container**: `vscode-monitor` with docker socket access
- **Working directory**: `/app`
- **Persistent state**: `/state/` - USE THIS PATH, not /app/state
- **Notes file**: `/state/copilot/notes_to_self.md`
- **Analysis output**: `/state/analysis/`

### Key Paths
| Path | Access | Purpose |
|------|--------|---------|
| `/state/` | RW | Persistent state - ALWAYS use this, NOT /app/state |
| `/state/analysis/` | RW | Daily reports go here |
| `/state/copilot/` | RW | Your notes between runs |
| `/host/proc/` | RO | Host /proc (for mdstat, loadavg, meminfo) |
| `/host/emhttp/` | RO | Unraid emhttp (for disks.ini) |
| `/app/` | RW | Project files |

---

## Host System Checks

Host system info is mounted read-only at `/host/`:
```bash
cat /host/proc/mdstat          # Array status
cat /host/proc/loadavg         # Load average  
cat /host/proc/meminfo         # Memory details
cat /host/emhttp/disks.ini     # Disk health/temps
```

For commands that need to run ON the host (like virsh), use:
```bash
host_cmd virsh list --all
host_cmd df -h /boot /mnt/user /mnt/cache
host_cmd free -h
```

---

## Notifications

**IMPORTANT**: Use `alert_helper.py` (NOT notify_helper.py - that name is blocked):
```bash
python3 /app/alert_helper.py -e "event" -s "subject" -d "description" -i "normal|warning|alert" [-m "message"] -l "/state/analysis/REPORT_FILE.md"
```

**ALWAYS include `-l "/state/analysis/<filename>.md"`** - this gets converted to a public URL automatically.

Example:
```bash
python3 /app/alert_helper.py \
  -e "vscode-monitor" \
  -s "Daily Health Check Complete" \
  -d "System check finished" \
  -i "normal" \
  -l "/state/analysis/daily_report_20251130_120000.md"
```

---

## Health Check Tasks

### 1. Container Status
```bash
docker ps -a --format 'table {{.Names}}\t{{.Status}}'
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'
```

### 2. Unraid System
```bash
cat /host/proc/mdstat          # Array status
cat /host/proc/loadavg         # Load average
host_cmd free -h               # Memory  
host_cmd df -h /boot /mnt/user /mnt/cache  # Disk space
cat /host/emhttp/disks.ini     # Disk health
```

**Alert thresholds**: Memory >90%, disk >95%, load > 2x CPU cores, disabled disks > 0

### 3. Immich Jobs
```bash
/app/immich_jobs.sh          # Check status
/app/immich_jobs.sh resume   # Resume if paused
```

### 4. VMs
```bash
host_cmd virsh list --all
```

---

## Home Assistant Deep Inspection

The HA VM `hammassistant` at 192.168.1.179 requires thorough daily checks.

### Quick Health
```bash
curl -s -m 5 -H "Authorization: Bearer $HA_TOKEN" \
  http://192.168.1.179:8123/api/config | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(f'HA {d[\"version\"]} @ {d[\"location_name\"]}')"
```

### Check for Updates
```bash
# Core updates
curl -s -H "Authorization: Bearer $HA_TOKEN" \
  http://192.168.1.179:8123/api/states/update.home_assistant_core_update | \
  python3 -c "import sys,json; s=json.load(sys.stdin); a=s['attributes']; print(f\"Core: {a.get('installed_version')} -> {a.get('latest_version')} ({'UPDATE AVAILABLE' if s['state']=='on' else 'up to date'})\")"

# OS updates  
curl -s -H "Authorization: Bearer $HA_TOKEN" \
  http://192.168.1.179:8123/api/states/update.home_assistant_operating_system_update | \
  python3 -c "import sys,json; s=json.load(sys.stdin); a=s['attributes']; print(f\"OS: {a.get('installed_version')} -> {a.get('latest_version')} ({'UPDATE AVAILABLE' if s['state']=='on' else 'up to date'})\")"
```

### Check Problem Entities
```bash
curl -s -H "Authorization: Bearer $HA_TOKEN" http://192.168.1.179:8123/api/states | \
  python3 -c "
import sys,json
states = json.load(sys.stdin)
problems = [s for s in states if s['state'] in ('unavailable', 'unknown')]
if problems:
    print(f'⚠️ {len(problems)} problem entities:')
    for p in problems[:10]:
        print(f\"  - {p['entity_id']}: {p['state']}\")
    if len(problems) > 10:
        print(f'  ... and {len(problems)-10} more')
else:
    print('✅ No unavailable/unknown entities')
"
```

### Check HA Logs
```bash
curl -s -H "Authorization: Bearer $HA_TOKEN" "http://192.168.1.179:8123/api/error_log" | tail -50
```

### If Port 8123 Not Responding
Usually means the core container crashed:
```bash
virsh qemu-agent-command hammassistant \
  '{"execute":"guest-exec","arguments":{"path":"docker","arg":["start","homeassistant"],"capture-output":true}}'
```

---

## Automated Takeout Script

Check `docker logs automated-takeout` for:

| Status | Indicators | Action |
|--------|------------|--------|
| SUCCESS | No errors, takeout created | None |
| AUTH_REQUIRED | Login expired | Alert → VNC port 6901 |
| FAILURE | Selector errors | Attempt fix |

---

## Chadburn Scheduler

**Issue #127**: Goroutine leak bug. Pinned to known-good SHA.

```bash
curl -s "https://api.github.com/repos/PremoWeb/Chadburn/issues/127" | grep '"state"'
```

---

## Self-Maintenance

Use `/state/copilot/notes_to_self.md` for observations across runs:
```bash
mkdir -p /state/copilot
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Host proc info | `cat /host/proc/mdstat` |
| Host command | `host_cmd <cmd>` |
| Send alert | `python3 /app/alert_helper.py -e "event" -s "subject" -d "desc" -i "normal" -l "/state/analysis/FILE.md"` |
| Rebuild service | `docker-compose build <svc> && docker-compose up -d <svc>` |
