#!/usr/bin/env python3
"""
Unraid Notification Helper for Docker Containers

This script uses nsenter to run the Unraid notify command in the host's namespace.
This is necessary because the notify script requires the full Unraid emhttp environment.
"""

import argparse
import subprocess
import sys
import os

def send_notification(event, subject, description, importance, message=None, link=None):
    """Send notification to Unraid using nsenter to access host namespace"""
    
    # Build the notify command
    cmd_parts = [
        'nsenter', '--target', '1', '--mount', '--uts', '--ipc', '--net', '--pid',
        '/usr/local/emhttp/webGui/scripts/notify',
        '-e', event,
        '-s', subject,
        '-d', description,
        '-i', importance
    ]
    
    if message:
        cmd_parts.extend(['-m', message])
    
    if link:
        # Check if link is a path to analysis directory
        if link.startswith('/state/analysis/'):
            # Convert to public FileBrowser URL if FILEBROWSER_BASE_URL is set
            filebrowser_base = os.environ.get('FILEBROWSER_BASE_URL', '')
            if filebrowser_base:
                # Extract filename from path
                filename = link.split('/')[-1]
                # Construct FileBrowser URL (assumes analysis files are in /srv/analysis)
                link = f"{filebrowser_base}/files/srv/analysis/{filename}"
        
        cmd_parts.extend(['-l', link])
    
    try:
        result = subprocess.run(cmd_parts, capture_output=True, text=True, check=True)
        print(f"✅ Notification sent successfully")
        if result.stdout:
            print(result.stdout)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to send notification: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

def main():
    parser = argparse.ArgumentParser(description='Send Unraid notifications from Docker container')
    parser.add_argument('-e', '--event', required=True, help='Event category')
    parser.add_argument('-s', '--subject', required=True, help='Subject line')
    parser.add_argument('-d', '--description', required=True, help='Brief description')
    parser.add_argument('-i', '--importance', required=True, choices=['normal', 'warning', 'alert'], help='Importance level')
    parser.add_argument('-m', '--message', help='Optional longer message body')
    parser.add_argument('-l', '--link', help='Optional link (use /state/analysis/<file> for analysis files)')
    
    args = parser.parse_args()
    
    return send_notification(
        args.event,
        args.subject,
        args.description,
        args.importance,
        args.message,
        args.link
    )

if __name__ == '__main__':
    sys.exit(main())
