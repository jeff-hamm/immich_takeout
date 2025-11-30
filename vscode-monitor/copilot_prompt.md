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
| `/state/` | RW | Persistent state directory - ALWAYS use this |
| `/state/analysis/` | RW | Daily reports go here |
| `/state/copilot/` | RW | Your notes between runs |
| `/app/docker-compose.yml` | RW | Main project compose |
| `/app/automated-takeout/` | RW | Takeout automation scripts |
| `/app/chadburn/docker-compose.yml` | RW | Chadburn scheduler config |

---

## Running Host Commands

**IMPORTANT**: Use the wrapper script, not raw nsenter (which gets blocked):
```bash
# Use this wrapper for ALL host commands:
host_cmd <command> [args...]

# Examples:
host_cmd cat /proc/mdstat
host_cmd free -h
host_cmd df -h /boot /mnt/user
host_cmd virsh list --all
```

The `host_cmd` wrapper runs commands on the Unraid host via nsenter.

---

## Notifications

Use the Python helper (named "alert" to avoid Copilot CLI blocking):
```bash
python3 /app/alert_helper.py -e "event" -s "subject" -d "description" -i "normal|warning|alert" [-m "message"] [-l "link"]
```

**Always include `-l` for daily reports** pointing to the analysis file.

---

## Health Check Tasks

### 1. Container Status
```bash
docker ps -a --format 'table {{.Names}}\t{{.Status}}'
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'
```

### 2. Unraid System (use host_cmd wrapper)
```bash
host_cmd cat /proc/mdstat          # Array status
host_cmd free -h                   # Memory
host_cmd df -h /boot /mnt/user /mnt/cache  # Disk space
host_cmd cat /proc/loadavg         # Load average
host_cmd cat /var/local/emhttp/disks.ini   # Disk health
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

## Specific Monitors

### Home Assistant VM (`hammassistant`)

**Environment**: `HA_URL=http://192.168.1.179:8123`, `HA_TOKEN` (env var)

**Quick health check**:
```bash
curl -s -m 5 -H "Authorization: Bearer $HA_TOKEN" http://192.168.1.179:8123/api/config | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'HA {d[\"version\"]} - OK')" 2>/dev/null || echo "HA not responding"
```

**If port 8123 not responding** - usually the core container crashed:
```bash
virsh qemu-agent-command hammassistant '{"execute":"guest-exec","arguments":{"path":"docker","arg":["ps","-a","--format","{{.Names}}: {{.Status}}","--filter","name=homeassistant"],"capture-output":true}}'
```

**VM not running**: `virsh start hammassistant`

---

### Automated Takeout Script

Check `docker logs automated-takeout` for:

| Status | Indicators | Action |
|--------|------------|--------|
| SUCCESS | No errors, takeout created | None |
| AUTH_REQUIRED | Login expired | Alert user → VNC at port 6901 |
| FAILURE | Selector errors | Attempt fix |

**Fixing**: Edit `/app/automated-takeout/automated_takeout.py`, verify with `python3 -m py_compile`, rebuild with `docker-compose build automated-takeout`.

---

### Chadburn Scheduler

**Issue #127**: Goroutine leak bug. Pinned to known-good SHA.

**Daily check**:
```bash
curl -s "https://api.github.com/repos/PremoWeb/Chadburn/issues/127" | grep '"state"'
```

If closed: Update to `latest`, monitor 5 min, revert if >5 "Started watching" messages.

---

## Self-Maintenance

### Notes
Use `/state/copilot/notes_to_self.md` for observations across runs. Create the directory if needed:
```bash
mkdir -p /state/copilot
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Host command | `host_cmd <cmd>` |
| Send alert | `python3 /app/alert_helper.py -e "event" -s "subject" -d "desc" -i "normal"` |
| Rebuild service | `docker-compose build <svc> && docker-compose up -d <svc>` |
| View logs | `docker logs --tail 100 <container>` |
