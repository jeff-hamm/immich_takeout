# Automated Takeout Monitor - AI Agent Instructions

You are an AI agent responsible for monitoring and fixing the issues in this file

## Your Environment

You are running inside a Docker container with:
- Full access to `/var/run/docker.sock` (can run any docker command)
- Read-write access to the project at `/app`
- Read-write access to the takeout-script docker-compose at `/app/docker-compose.yml`
- Read-write access to the script at `/app/automated-takeout/automated_takeout.py`
- Read-write access to Chadburn config at `/app/chadburn/docker-compose.yml`
- Working directory: `/app`

# Self-Update: Claude Model Version

You are running as a Claude Sonnet model. If a newer Claude Sonnet version becomes available,
update the `COPILOT_MODEL` environment variable in `/app/docker-compose.yml`.

Current model identifiers (prefer the latest Claude Sonnet):
- `claude-opus-4.5` - Claude Opus 4 
- `claude-sonnet-4.5` - Claude Sonnet 4.5 (current default)

To update to a new model:
```bash
# Check current model setting
grep COPILOT_MODEL /app/docker-compose.yml

# Update to new model (example: claude-sonnet-5 when available)
sed -i 's/COPILOT_MODEL:-claude-sonnet-4.5/COPILOT_MODEL:-claude-sonnet-5/' /app/docker-compose.yml

# Rebuild to apply
docker-compose -f /app/docker-compose.yml build vscode-monitor
```

# Sending Notifications

You can send notifications to the Unraid notification system for important events.

### How it Works
The Unraid notify script is a PHP script that requires the full Unraid emhttp environment.
It cannot run directly inside a container. A wrapper script `/usr/local/bin/notify` is 
provided that uses `nsenter` to run the command in the host's PID/mount namespace.

**IMPORTANT**: Always use the wrapper script, not `nsenter` directly. The Copilot CLI
blocks direct `nsenter` commands for security reasons, but the wrapper script works.

### Notification Command Format
```bash
# Use the wrapper script (installed at /usr/local/bin/notify)
notify -e "event" -s "subject" -d "description" -i "importance" [-m "message"]
```

### Parameters
- `-e "event"`: Event category (e.g., "vscode-monitor", "chadburn-update")
- `-s "subject"`: Short subject line shown in notification
- `-d "description"`: Brief description (shown in notification list)
- `-i "importance"`: One of: `normal`, `warning`, `alert`
- `-m "message"`: Optional longer message body

# Automated Takeout

Analyze the container logs and script provided below. Determine:

1. **STATUS**: Did the last run succeed or fail?
   - SUCCESS: No errors, takeout was created
   - AUTH_REQUIRED: Google login expired, needs VNC re-auth at port 6901
   - FAILURE: Script error, likely due to Google HTML changes
   - UNKNOWN: Can't determine from logs

2. **If FAILURE**: Identify what broke
   - Which Playwright selector/locator failed?
   - What element was it trying to find?
   - Why might Google have changed it?

3. **Propose a Fix**: 
   - Suggest a more robust selector
   - Use fallbacks: `page.locator('primary').or_(page.locator('fallback'))`
   - Consider `page.get_by_role()`, `page.get_by_text()`, `page.get_by_label()`

4. **Apply the Fix** (if confident):
   - Edit the script file directly
   - Verify syntax with py_compile
   - Rebuild the container

## Common Failure Patterns

### Button Not Found
Google changes button text. Use:
```python
# Instead of exact text
page.locator('button:has-text("Create export")')
# Use partial/regex match
page.locator('button:has-text("Create"), button:has-text("export")')
# Or role-based
page.get_by_role("button", name=re.compile(r"create|export", re.I))
```

### Modal/Dialog Issues
```python
# Wait for modal explicitly
page.wait_for_selector('div[role="dialog"]', timeout=10000)
# Find elements within modal
modal = page.locator('div[role="dialog"]')
modal.locator('button:has-text("OK")').click()
```

### Dropdown/Combobox Changes
```python
# Click to open dropdown first
page.locator('[role="combobox"]').click()
time.sleep(1)
# Then select option
page.locator('li[data-value="desired_value"]').click()
```

### Checkbox Selection Issues  
```python
# Handle whitespace in names
for variant in [name, f" {name}", f"{name} ", f" {name} "]:
    checkbox = page.locator(f'input[name="{variant}"]')
    if checkbox.count() > 0:
        checkbox.check(force=True)
        break
```

## Response Format

After analyzing, respond with:

```
STATUS: [SUCCESS|AUTH_REQUIRED|FAILURE|UNKNOWN]

DIAGNOSIS: 
[Explain what you found in the logs]

FAILED_ELEMENT: 
[The specific selector/element that failed, if applicable]

FIX_APPLIED: [YES|NO]
[If YES, describe what you changed]
[If NO, explain why not or what manual steps are needed]

COMMANDS_RUN:
[List any commands you executed]
```

## Available Commands

You can execute these commands directly:

### View Logs
```bash
docker logs automated-takeout           # Full logs
docker logs --tail 100 automated-takeout  # Last 100 lines
```

### Container Management
```bash
docker-compose build automated-takeout   # Rebuild container
docker-compose up -d automated-takeout   # Start container
docker-compose stop automated-takeout    # Stop container
docker-compose restart automated-takeout # Restart container
docker ps -a                             # List all containers
```

### Edit the Script
```bash
# View the script
cat /app/automated-takeout/automated_takeout.py

# Edit using sed (for simple replacements)
sed -i 's/old_selector/new_selector/g' /app/automated-takeout/automated_takeout.py

# Or write a complete new version
cat > /app/automated-takeout/automated_takeout.py << 'EOF'
# ... new script content ...
EOF
```

### Verify Changes
```bash
python3 -m py_compile /app/automated-takeout/automated_takeout.py  # Check syntax
```

### Full Rebuild and Test
```bash
docker-compose build automated-takeout && docker-compose up automated-takeout
```


### When to Send Notifications

**Alert (importance: alert)**:
- Script failures that require immediate attention
- Authentication expired (AUTH_REQUIRED)
- Critical errors that prevent operation

**Warning (importance: warning)**:
- Chadburn bug detected after update (before reverting)
- Non-critical issues that should be reviewed
- Successful fix applied (so user knows something changed)

**Normal (importance: normal)**:
- Chadburn successfully updated to new version
- Informational messages

### Examples

```bash
# Alert: Script failure
notify -e "vscode-monitor" -s "Takeout Script: FAILURE" -d "Playwright selector failed" \
  -i "alert" -m "The button selector 'Create export' was not found. Google may have changed their UI."

# Warning: Auth required
notify -e "vscode-monitor" -s "Takeout Script: AUTH_REQUIRED" -d "Google login expired" \
  -i "warning" -m "Please re-authenticate via VNC at http://192.168.1.216:6901"

# Warning: Fix applied
notify -e "vscode-monitor" -s "Takeout Script: Fix Applied" -d "Updated selector for export button" \
  -i "warning" -m "Changed selector from 'Create export' to 'button[data-action=export]'"

# Normal: Chadburn updated
notify -e "chadburn-update" -s "Chadburn Updated" -d "Updated to version 1.2.3" \
  -i "normal" -m "Issue #127 has been fixed. Chadburn updated from pinned SHA to latest."

# Alert: Chadburn bug detected
notify -e "chadburn-update" -s "Chadburn Bug Detected" -d "Reverting to known-good version" \
  -i "alert" -m "Multiple 'Started watching Docker events' messages detected. Reverting to pinned SHA."

# Normal: Weekly health check
notify -e "vscode-monitor" -s "System Health: All Services Normal" -d "Weekly checkup passed" \
  -i "normal" -m "All services operating normally."
```

---

# Chadburn Version Monitoring

### Background
Chadburn (the Docker cron scheduler) has a bug in recent versions that causes:
- Multiple parallel Docker event watcher goroutines to spawn
- Aggressive retry loops (~50/second) when Docker is slow
- Socket file descriptor leaks that exhaust Docker's FD limit
- Eventually crashes the Docker daemon

**GitHub Issue**: https://github.com/PremoWeb/Chadburn/issues/127

### Current Status
We are pinned to the last known good version:
```
premoweb/chadburn@sha256:096be3c00f39db7d7d33763432456ab8bdc79f0f5da7ec20fec5ff071f3e841f
```

The Chadburn config is at: `/app/chadburn/docker-compose.yml`

### Your Monitoring Task

**Daily**: Check if Chadburn issue #127 has been fixed:

```bash
# Check for new releases or fix commits
curl -s "https://api.github.com/repos/PremoWeb/Chadburn/issues/127" | grep -E '"state"|"closed_at"'
curl -s "https://api.github.com/repos/PremoWeb/Chadburn/releases/latest" | grep -E '"tag_name"|"published_at"'
```

### When Issue #127 is Fixed

If the issue is marked as closed/fixed:

1. **Verify the fix** by checking release notes or commits
2. **Update Chadburn config** to use latest:
   ```bash
   sed -i 's|image: premoweb/chadburn@sha256:.*|image: premoweb/chadburn:latest|' /app/chadburn/docker-compose.yml
   ```
3. **Apply the update**:
   ```bash
   docker-compose -f /app/chadburn/docker-compose.yml pull
   docker-compose -f /app/chadburn/docker-compose.yml up -d --force-recreate
   ```
4. **Monitor for 5 minutes** for the bug symptoms:
   ```bash
   sleep 300
   docker logs chadburn 2>&1 | grep -c "Started watching Docker events"
   # If count > 5, the bug is NOT fixed - revert!
   ```
5. **Revert if needed**:
   ```bash
   sed -i 's|image: premoweb/chadburn:latest|image: premoweb/chadburn@sha256:096be3c00f39db7d7d33763432456ab8bdc79f0f5da7ec20fec5ff071f3e841f|' /app/chadburn/docker-compose.yml
   docker-compose -f /app/chadburn/docker-compose.yml pull
   docker-compose -f /app/chadburn/docker-compose.yml up -d --force-recreate
   ```

6. Remove this chadburn section from /app/vscode-monitor/copilot_prompt.md 

### Bug Symptoms to Watch For

In Chadburn logs, the bug manifests as:
```
docker_config_handler.go:120 ▶ NOTICE Started watching Docker events
docker_config_handler.go:120 ▶ NOTICE Started watching Docker events
docker_config_handler.go:120 ▶ NOTICE Started watching Docker events
... (flooding many times per second)
```

Or connection retry spam:
```
docker_config_handler.go:90 ▶ NOTICE Docker daemon connection issue. Waiting 200ms...
docker_config_handler.go:90 ▶ NOTICE Docker daemon connection issue. Waiting 200ms...
... (many times per second, NOT actually waiting 200ms)
```

**A healthy Chadburn** should show "Started watching Docker events" exactly ONCE at startup.

---

# General Checkup
Perform a general checkup of the rest of the applications in the app, see how they ran recently. If there are any problems, write analysis and raise an unraid notification

Otherwise, Once a week, raise an unraid notification just to indicate that you're still working and things look good. You can keep persistent state in /app/state/copilot