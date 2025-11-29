#!/usr/bin/env python3
"""
Resume all paused jobs in Immich.
Can be run standalone or imported as a module.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


def get_api_key(api_key_file: str = None) -> str:
    """Get the Immich API key from file or environment."""
    # Try environment variable first
    api_key = os.getenv("IMMICH_API_KEY")
    if api_key:
        return api_key
    
    # Try file
    if api_key_file is None:
        api_key_file = os.getenv("IMMICH_API_KEY_FILE", "/app/state/.immich_api_key")
    
    key_path = Path(api_key_file)
    if key_path.exists():
        return key_path.read_text().strip()
    
    # Try alternate locations
    alt_paths = [
        Path("/app/cache/.immich_api_key"),
        Path("state/.immich_api_key"),
        Path("cache/.immich_api_key"),
    ]
    for path in alt_paths:
        if path.exists():
            return path.read_text().strip()
    
    raise ValueError("No API key found. Set IMMICH_API_KEY or provide key file.")


def get_jobs_status(server_url: str, api_key: str) -> dict:
    """Get current status of all jobs."""
    url = f"{server_url}/api/jobs"
    
    req = urllib.request.Request(
        url,
        headers={
            'x-api-key': api_key,
            'Accept': 'application/json'
        },
        method='GET'
    )
    
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def send_job_command(server_url: str, api_key: str, job_name: str, command: str) -> dict:
    """Send a command to a specific job."""
    url = f"{server_url}/api/jobs/{job_name}"
    data = json.dumps({"command": command, "force": False}).encode('utf-8')
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'x-api-key': api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        method='PUT'
    )
    
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def resume_all_jobs(server_url: str, api_key: str) -> dict:
    """Resume all paused jobs in Immich."""
    results = {
        'resumed': [],
        'already_running': [],
        'errors': []
    }
    
    try:
        jobs = get_jobs_status(server_url, api_key)
    except Exception as e:
        print(f"[ERROR] Failed to get jobs status: {e}")
        results['errors'].append(f"Failed to get jobs: {e}")
        return results
    
    for job_name, job_info in jobs.items():
        # Skip if no queue info
        if not isinstance(job_info, dict):
            continue
        
        queue_status = job_info.get('queueStatus', {})
        is_paused = queue_status.get('isPaused', False)
        is_active = queue_status.get('isActive', False)
        
        if is_paused:
            try:
                send_job_command(server_url, api_key, job_name, "resume")
                print(f"[INFO] Resumed job: {job_name}")
                results['resumed'].append(job_name)
            except Exception as e:
                print(f"[ERROR] Failed to resume {job_name}: {e}")
                results['errors'].append(f"{job_name}: {e}")
        elif is_active:
            results['already_running'].append(job_name)
    
    return results


def pause_all_jobs(server_url: str, api_key: str) -> dict:
    """Pause all active jobs in Immich."""
    results = {
        'paused': [],
        'already_paused': [],
        'errors': []
    }
    
    try:
        jobs = get_jobs_status(server_url, api_key)
    except Exception as e:
        print(f"[ERROR] Failed to get jobs status: {e}")
        results['errors'].append(f"Failed to get jobs: {e}")
        return results
    
    for job_name, job_info in jobs.items():
        # Skip if no queue info
        if not isinstance(job_info, dict):
            continue
        
        queue_status = job_info.get('queueStatus', {})
        is_paused = queue_status.get('isPaused', False)
        is_active = queue_status.get('isActive', False)
        
        if is_active and not is_paused:
            try:
                send_job_command(server_url, api_key, job_name, "pause")
                print(f"[INFO] Paused job: {job_name}")
                results['paused'].append(job_name)
            except Exception as e:
                print(f"[ERROR] Failed to pause {job_name}: {e}")
                results['errors'].append(f"{job_name}: {e}")
        elif is_paused:
            results['already_paused'].append(job_name)
    
    return results


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Manage Immich jobs')
    parser.add_argument('action', nargs='?', default='status',
                        choices=['resume', 'pause', 'status'],
                        help='Action to perform (default: status)')
    parser.add_argument('--server', '-s', 
                        default=os.getenv('IMMICH_SERVER', 'http://192.168.1.216:2283'),
                        help='Immich server URL')
    parser.add_argument('--key-file', '-k',
                        help='Path to API key file')
    parser.add_argument('--wait', '-w', action='store_true',
                        help='Wait for immich-import container to finish first')
    args = parser.parse_args()
    
    server_url = args.server.rstrip('/')
    if server_url.endswith('/api'):
        server_url = server_url[:-4]
    
    try:
        api_key = get_api_key(args.key_file)
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    
    if args.wait:
        print("[INFO] Waiting for immich-import container to complete...")
        import subprocess
        import time
        
        while True:
            result = subprocess.run(
                ['docker', 'ps', '--filter', 'name=immich-import', '--format', '{{.Status}}'],
                capture_output=True, text=True
            )
            status = result.stdout.strip()
            
            if not status or 'Up' not in status:
                print("[INFO] immich-import container is not running")
                break
            
            print(f"[INFO] Container status: {status}, waiting...")
            time.sleep(30)
    
    if args.action == 'status':
        try:
            jobs = get_jobs_status(server_url, api_key)
            print(json.dumps(jobs, indent=2))
        except Exception as e:
            print(f"[ERROR] Failed to get status: {e}")
            sys.exit(1)
    
    elif args.action == 'resume':
        results = resume_all_jobs(server_url, api_key)
        if results['resumed']:
            print(f"[INFO] Resumed {len(results['resumed'])} job(s): {', '.join(results['resumed'])}")
        if results['already_running']:
            print(f"[INFO] Already running: {', '.join(results['already_running'])}")
        if results['errors']:
            print(f"[ERROR] Errors: {len(results['errors'])}")
            sys.exit(1)
    
    elif args.action == 'pause':
        results = pause_all_jobs(server_url, api_key)
        if results['paused']:
            print(f"[INFO] Paused {len(results['paused'])} job(s): {', '.join(results['paused'])}")
        if results['already_paused']:
            print(f"[INFO] Already paused: {', '.join(results['already_paused'])}")
        if results['errors']:
            print(f"[ERROR] Errors: {len(results['errors'])}")
            sys.exit(1)


if __name__ == "__main__":
    main()
