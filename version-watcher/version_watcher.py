#!/usr/bin/env python3
"""
Generic Docker image version watcher
Checks Docker Hub for new versions, updates .env file, and triggers rebuild
Designed to run once per execution via Ophelia scheduler
"""
import os
import sys
import re
import subprocess
import requests
from pathlib import Path

# Configuration from environment variables
DOCKER_IMAGE = os.getenv("DOCKER_IMAGE", "kasmweb/chrome")
SERVICE_NAME = os.getenv("SERVICE_NAME", "login-helper")
ENV_VAR_NAME = os.getenv("ENV_VAR_NAME", "kasmweb_version")
COMPOSE_FILE_PATH = os.getenv("COMPOSE_FILE", "/app/project/docker-compose.yml")

# Derived values
DOCKER_HUB_API = f"https://registry.hub.docker.com/v2/repositories/{DOCKER_IMAGE}/tags"
ENV_FILE = Path(COMPOSE_FILE_PATH).parent / ".env"
COMPOSE_FILE = Path(COMPOSE_FILE_PATH)


def load_env_vars():
    """Load environment variables from .env file."""
    env = os.environ.copy()
    
    if not ENV_FILE.exists():
        print(f"[WARNING] .env file not found: {ENV_FILE}")
        return env
    
    with open(ENV_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            # Parse KEY=VALUE format
            if '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
    
    return env


def get_current_version():
    """Read current version from .env file."""
    if not ENV_FILE.exists():
        print(f"[ERROR] .env file not found: {ENV_FILE}")
        return None
    
    with open(ENV_FILE, 'r') as f:
        content = f.read()
    
    pattern = rf'{ENV_VAR_NAME}=(\d+\.\d+\.\d+)'
    match = re.search(pattern, content)
    if match:
        return match.group(1)
    
    print(f"[ERROR] Could not find {ENV_VAR_NAME} in .env")
    return None


def get_latest_version():
    """Query Docker Hub API for latest kasmweb/chrome version."""
    try:
        response = requests.get(f"{DOCKER_HUB_API}?page_size=100", timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Extract all version tags (e.g., "1.18.0", "1.19.0")
        version_pattern = re.compile(r'^(\d+\.\d+\.\d+)$')
        versions = []
        
        for tag in data.get('results', []):
            tag_name = tag.get('name', '')
            match = version_pattern.match(tag_name)
            if match:
                versions.append(match.group(1))
        
        if not versions:
            print("[WARNING] No version tags found")
            return None
        
        # Sort versions and return the latest
        versions.sort(key=lambda v: [int(x) for x in v.split('.')], reverse=True)
        return versions[0]
    
    except requests.RequestException as e:
        print(f"[ERROR] Failed to query Docker Hub: {e}")
        return None


def update_env_file(new_version):
    """Update .env file with new version."""
    if not ENV_FILE.exists():
        print(f"[ERROR] .env file not found: {ENV_FILE}")
        return False
    
    with open(ENV_FILE, 'r') as f:
        content = f.read()
    
    # Replace version
    pattern = rf'{ENV_VAR_NAME}=\d+\.\d+\.\d+'
    new_content = re.sub(
        pattern,
        f'{ENV_VAR_NAME}={new_version}',
        content
    )
    
    if new_content == content:
        print(f"[WARNING] No changes made to .env file")
        return False
    
    with open(ENV_FILE, 'w') as f:
        f.write(new_content)
    
    print(f"[SUCCESS] Updated .env: {ENV_VAR_NAME}={new_version}")
    return True


def rebuild_service():
    """Rebuild and restart the login-helper service."""
    try:
        print(f"[INFO] Rebuilding {SERVICE_NAME} service...")
        
        # Load environment variables from .env file
        env = load_env_vars()
        
        # Build the new image
        result = subprocess.run(
            ["docker-compose", "build", "--no-cache", SERVICE_NAME],
            cwd=COMPOSE_FILE.parent,
            capture_output=True,
            text=True,
            timeout=600,
            env=env
        )
        
        if result.returncode != 0:
            print(f"[ERROR] Build failed: {result.stderr}")
            return False
        
        print(f"[SUCCESS] Built new {SERVICE_NAME} image")
        
        # Stop existing container if running
        subprocess.run(
            ["docker-compose", "stop", SERVICE_NAME],
            cwd=COMPOSE_FILE.parent,
            capture_output=True,
            env=env
        )
        
        # Remove old container
        subprocess.run(
            ["docker-compose", "rm", "-f", SERVICE_NAME],
            cwd=COMPOSE_FILE.parent,
            capture_output=True,
            env=env
        )
        
        print(f"[SUCCESS] Rebuilt {SERVICE_NAME} service with new version")
        return True
    
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Build timeout after 600 seconds")
        return False
    except Exception as e:
        print(f"[ERROR] Rebuild failed: {e}")
        return False


def main():
    """Check for updates and exit."""
    print(f"[INFO] Version watcher starting")
    print(f"[INFO] Image: {DOCKER_IMAGE}")
    print(f"[INFO] Service: {SERVICE_NAME}")
    print(f"[INFO] Env var: {ENV_VAR_NAME}")
    print(f"[INFO] Checking for new versions...")
    
    try:
        current_version = get_current_version()
        if not current_version:
            print("[ERROR] Could not determine current version")
            sys.exit(1)
        
        print(f"[INFO] Current version: {current_version}")
        
        latest_version = get_latest_version()
        if not latest_version:
            print("[ERROR] Could not determine latest version")
            sys.exit(1)
        
        print(f"[INFO] Latest version: {latest_version}")
        
        # Compare versions
        current_parts = [int(x) for x in current_version.split('.')]
        latest_parts = [int(x) for x in latest_version.split('.')]
        
        if latest_parts > current_parts:
            print(f"\n[UPDATE] New version available: {current_version} -> {latest_version}")
            
            if update_env_file(latest_version):
                if rebuild_service():
                    print(f"[SUCCESS] Successfully updated to version {latest_version}")
                    sys.exit(0)
                else:
                    print(f"[ERROR] Failed to rebuild service")
                    # Rollback .env
                    update_env_file(current_version)
                    sys.exit(1)
            else:
                print(f"[ERROR] Failed to update .env file")
                sys.exit(1)
        else:
            print(f"[INFO] Already on latest version")
            sys.exit(0)
    
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
