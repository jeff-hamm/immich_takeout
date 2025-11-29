#!/usr/bin/env python3
"""
Minimal orchestrator for AI-powered automated-takeout monitoring.
Collects context and delegates all analysis/fixing to GitHub Copilot CLI.
The AI agent has full control to edit files, run docker commands, etc.

Uses the NEW GitHub Copilot CLI (@github/copilot) which is a full agentic CLI:
- Programmatic mode: copilot -p "prompt" --allow-all-tools
- Can edit files, run shell commands, interact with GitHub
- Uses Claude Sonnet 4.5 by default
"""
import os
import sys
import subprocess
import json
from datetime import datetime
from pathlib import Path

# Paths
PROJECT_DIR = os.getenv("PROJECT_DIR", "/app")
PROMPT_FILE = os.getenv("PROMPT_FILE", "/app/copilot_prompt.md")
LOG_DIR = os.getenv("LOG_DIR", "/app/logs")
ANALYSIS_DIR = os.getenv("ANALYSIS_DIR", "/state/analysis")
CONTAINER = "automated-takeout"

# GitHub token file (mounted from host state directory)
COPILOT_TOKEN_FILE = os.getenv("COPILOT_TOKEN_FILE", "/root/.copilot-token")

# Unraid notify script (mounted from host)
UNRAID_NOTIFY = os.getenv("UNRAID_NOTIFY", "/usr/local/emhttp/plugins/dynamix/scripts/notify")

# Copilot model - Claude Sonnet 4.5 by default
COPILOT_MODEL = os.getenv("COPILOT_MODEL", "claude-sonnet-4.5")

# Copilot version - if set, ensure we're running at least this version
COPILOT_VERSION = os.getenv("COPILOT_VERSION", "")


def load_github_token() -> bool:
    """Load GitHub token from file and set environment variable."""
    # Check if already set via environment
    if os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or os.getenv("COPILOT_GITHUB_TOKEN"):
        print("[AUTH] Using token from environment variable")
        return True
    
    # Try to load from file
    if os.path.exists(COPILOT_TOKEN_FILE):
        try:
            with open(COPILOT_TOKEN_FILE) as f:
                token = f.read().strip()
            if token:
                os.environ["GH_TOKEN"] = token
                print(f"[AUTH] Loaded token from {COPILOT_TOKEN_FILE}")
                return True
        except Exception as e:
            print(f"[ERROR] Failed to read token file: {e}")
    
    print(f"[ERROR] No GitHub token found. Set GH_TOKEN env var or create {COPILOT_TOKEN_FILE}")
    return False


def parse_version(version_str: str) -> tuple:
    """Parse version string like '0.0.365' into tuple (0, 0, 365) for comparison."""
    try:
        # Extract version number from string (handles "0.0.365" or "v0.0.365" or output like "copilot version 0.0.365")
        import re
        match = re.search(r'(\d+)\.(\d+)\.(\d+)', version_str)
        if match:
            return tuple(int(x) for x in match.groups())
    except Exception:
        pass
    return (0, 0, 0)


def ensure_copilot_version() -> bool:
    """Check and upgrade Copilot CLI if COPILOT_VERSION is set and current version is lower."""
    if not COPILOT_VERSION:
        return True  # No version requirement
    
    required_version = parse_version(COPILOT_VERSION)
    if required_version == (0, 0, 0):
        print(f"[WARN] Invalid COPILOT_VERSION format: {COPILOT_VERSION}")
        return True  # Continue anyway
    
    # Get current version
    try:
        result = subprocess.run(
            ["copilot", "--version"],
            capture_output=True, text=True, timeout=30
        )
        current_version_str = result.stdout.strip() + result.stderr.strip()
        current_version = parse_version(current_version_str)
        
        print(f"[VERSION] Current: {'.'.join(map(str, current_version))}, Required: {COPILOT_VERSION}")
        
        if current_version >= required_version:
            print(f"[VERSION] Copilot CLI is up to date")
            return True
        
        # Need to upgrade
        print(f"[VERSION] Upgrading Copilot CLI to {COPILOT_VERSION}...")
        upgrade_result = subprocess.run(
            ["npm", "install", "-g", f"@github/copilot@{COPILOT_VERSION}"],
            capture_output=True, text=True, timeout=300
        )
        
        if upgrade_result.returncode == 0:
            print(f"[VERSION] Successfully upgraded to {COPILOT_VERSION}")
            return True
        else:
            print(f"[ERROR] Failed to upgrade Copilot CLI: {upgrade_result.stderr}")
            return False
            
    except FileNotFoundError:
        print("[ERROR] Copilot CLI not found, attempting install...")
        try:
            install_result = subprocess.run(
                ["npm", "install", "-g", f"@github/copilot@{COPILOT_VERSION}"],
                capture_output=True, text=True, timeout=300
            )
            if install_result.returncode == 0:
                print(f"[VERSION] Successfully installed Copilot CLI {COPILOT_VERSION}")
                return True
            else:
                print(f"[ERROR] Failed to install Copilot CLI: {install_result.stderr}")
                return False
        except Exception as e:
            print(f"[ERROR] Failed to install Copilot CLI: {e}")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to check Copilot version: {e}")
        return True  # Continue anyway


def send_notification(event: str, subject: str, description: str, importance: str = "normal", message: str = ""):
    """Send notification to Unraid notification system.
    
    Uses the /usr/local/bin/notify wrapper script which handles nsenter internally.
    This wrapper exists because direct nsenter calls are blocked by Copilot CLI.
    """
    # Use the wrapper script installed in the container
    cmd = ["/usr/local/bin/notify", "-e", event, "-s", subject, "-d", description, "-i", importance]
    if message:
        cmd.extend(["-m", message])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"[NOTIFY] Sent: {importance.upper()} - {subject}")
            return True
        else:
            print(f"[WARN] Notify failed (exit {result.returncode}): {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        print("[WARN] Notify wrapper script not found at /usr/local/bin/notify")
        return False
    except Exception as e:
        print(f"[WARN] Notify error: {e}")
        return False

def load_prompt() -> str:
    """Load the AI instructions from prompt file."""
    try:
        with open(PROMPT_FILE) as f:
            return f.read()
    except Exception as e:
        return f"Analyze the logs and fix any issues with the Playwright script. Error loading prompt: {e}"


def save_analysis(prompt: str, output: str, timestamp: str):
    """Save the analysis prompt and output to the analysis directory."""
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
        
    # Save output
    output_file = os.path.join(ANALYSIS_DIR, f"output_{timestamp}.txt")
    with open(output_file, "w") as f:
        f.write(output)
    print(f"Analysis saved to: {output_file}")
    
    return output_file


def run_copilot(prompt: str, timestamp: str) -> tuple[int, str]:
    """
    Run GitHub Copilot CLI (the new agentic CLI) with the full prompt.
    
    This uses programmatic mode with --allow-all-tools to let the agent:
    - Edit files directly
    - Run docker commands
    - Apply fixes automatically
    """
    # Save prompt to temp file
    prompt_path = "/tmp/copilot_prompt.txt"
    with open(prompt_path, "w") as f:
        f.write(prompt)
    
    print(f"[{datetime.now()}] Calling GitHub Copilot CLI (agentic mode)...")
    print("=" * 60)
    
    # Trust the working directory for this session
    config_dir = Path.home() / ".copilot"
    config_dir.mkdir(exist_ok=True)
    config_file = config_dir / "config.json"
    
    # Pre-trust the directories we'll be working in
    trusted_folders = [
        str(Path(PROJECT_DIR).resolve()),
    ]
    config = {"trusted_folders": trusted_folders}
    with open(config_file, "w") as f:
        json.dump(config, f)
    
    # Read the prompt and use it with -p flag (programmatic mode)
    # --allow-all-tools: Let the agent do anything needed
    # --deny-tool 'shell(rm -rf)': Safety - don't allow recursive delete
    try:
        result = subprocess.run(
            [
                "copilot",
                "-p", prompt,
                "--model", COPILOT_MODEL,
                "--allow-all-tools",
                "--deny-tool", "shell(rm -rf)",
            ],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
            cwd=PROJECT_DIR
        )
        
        output = result.stdout + result.stderr
        print(output)
        
        # Save analysis
        save_analysis(prompt, output, timestamp)
        
        return result.returncode, output
        
    except subprocess.TimeoutExpired:
        msg = "Copilot CLI timed out after 10 minutes"
        print(f"[ERROR] {msg}")
        return 1, msg
    except FileNotFoundError:
        msg = "Copilot CLI not found. Make sure @github/copilot is installed."
        print(f"[ERROR] {msg}")
        return 1, msg
    except Exception as e:
        msg = f"Error running Copilot CLI: {e}"
        print(f"[ERROR] {msg}")
        return 1, msg


def parse_status(output: str) -> tuple[str, str]:
    """Parse the STATUS and DIAGNOSIS from Copilot's output."""
    status = "UNKNOWN"
    diagnosis = ""
    
    lines = output.split('\n')
    in_diagnosis = False
    
    for line in lines:
        if line.startswith("STATUS:"):
            status = line.split(":", 1)[1].strip()
            in_diagnosis = False
        elif line.startswith("DIAGNOSIS:"):
            diagnosis = line.split(":", 1)[1].strip()
            in_diagnosis = True
        elif line.startswith("FAILED_ELEMENT:") or line.startswith("FIX_APPLIED:"):
            in_diagnosis = False
        elif in_diagnosis and line.strip():
            diagnosis += " " + line.strip()
    
    return status, diagnosis


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    print("=" * 60)
    print(f"[{datetime.now()}] Automated Takeout Monitor")
    print(f"Agent: GitHub Copilot CLI (Agentic Mode)")
    print(f"Model: {COPILOT_MODEL}")
    print("=" * 60)
    
    # Ensure Copilot CLI version if specified
    if not ensure_copilot_version():
        print("[ERROR] Failed to ensure Copilot CLI version")
        return 1
    
    # Load GitHub token for Copilot CLI
    if not load_github_token():
        print("[ERROR] Cannot proceed without GitHub authentication")
        return 1
    
    # Load instructions
    instructions = load_prompt()
    
    # Build full prompt
    full_prompt = f"{instructions}"
    
    # Log prompt size
    print(f"Prompt size: {len(full_prompt)} chars")
    
    # Hand off to Copilot
    returncode, output = run_copilot(full_prompt, timestamp)
    
    # Parse the result and send notification if there's an issue
    status, diagnosis = parse_status(output)
    
    if status in ["FAILURE", "AUTH_REQUIRED"]:
        importance = "alert" if status == "FAILURE" else "warning"
        send_notification(
            event="vscode-monitor",
            subject=f"Takeout Script: {status}",
            description=diagnosis[:200] if diagnosis else f"Status: {status}",
            importance=importance,
            message=f"The automated-takeout script reported: {status}\n\n{diagnosis}"
        )
    elif status == "SUCCESS":
        # Optional: notify on success too (comment out if too noisy)
        # send_notification(
        #     event="vscode-monitor",
        #     subject="Takeout Script: Success",
        #     description="Automated takeout completed successfully",
        #     importance="normal"
        # )
        pass
    
    print(f"\n[{datetime.now()}] Monitor complete. Status: {status}")
    return returncode


if __name__ == "__main__":
    sys.exit(main())
