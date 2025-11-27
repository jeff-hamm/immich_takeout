#!/usr/bin/env python3
import os
import subprocess
import time
import zipfile
from pathlib import Path

# CONFIGURABLE PATHS (mapped in container)
RCLONE_REMOTE = "gdrive:Takeout"  # rclone remote:path where Takeout exports appear
GDRIVE_DIR = Path("/data/gdrive/Takeout")  # Primary sync location


def ensure_dirs():
    GDRIVE_DIR.mkdir(parents=True, exist_ok=True)


def is_multipart_zip(zip_path):
    """Check if a zip file is part of a multi-part archive (can't be opened alone)."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # If we can open it and list contents, it's a valid single-part zip
            zf.namelist()
            return False
    except zipfile.BadZipFile as e:
        # Check if error message indicates multi-part archive
        error_msg = str(e).lower()
        if "not a zip file" in error_msg or "multi-part" in error_msg:
            return True
        return False
    except Exception:
        return False


def has_google_photos(zip_path):
    """Check if a zip file contains Google Photos content."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                if "Google Photos" in name or "Google Foto's" in name:
                    return True
        return False
    except Exception as e:
        # If we can't read it, assume it might be multi-part and skip
        return False


def get_multipart_group(zip_path):
    """Get all parts of a multi-part archive by finding matching numbered files."""
    import re
    # Match pattern like takeout-20240427T195310Z-001.zip
    match = re.match(r'(.+)-(\d{3})\.zip$', zip_path.name)
    if not match:
        return [zip_path]
    
    prefix = match.group(1)
    parts = []
    for sibling in zip_path.parent.glob(f"{prefix}-*.zip"):
        if re.match(r'.+-\d{3}\.zip$', sibling.name):
            parts.append(sibling)
    
    return sorted(parts) if parts else [zip_path]


def extract_zip(zip_path, related_parts=None):
    """Extract a zip file (single or multi-part) and remove the original(s)."""
    try:
        extract_dir = zip_path.parent / zip_path.stem.rsplit('-', 1)[0]
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        if related_parts and len(related_parts) > 1:
            print(f"[INFO] Extracting multi-part archive: {zip_path.name} ({len(related_parts)} parts)")
        else:
            print(f"[INFO] Extracting zip: {zip_path.name}")
        
        # Use unzip command which handles multi-part archives better
        cmd = ["unzip", "-q", "-o", str(zip_path), "-d", str(extract_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            # Fall back to Python zipfile for single-part archives
            if not related_parts or len(related_parts) == 1:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extract_dir)
            else:
                raise Exception(f"unzip failed: {result.stderr}")
        
        # Remove all parts after successful extraction
        parts_to_remove = related_parts if related_parts else [zip_path]
        for part in parts_to_remove:
            if part.exists():
                part.unlink()
        
        if related_parts and len(related_parts) > 1:
            print(f"[INFO] Extracted and removed {len(related_parts)} parts")
        else:
            print(f"[INFO] Extracted and removed: {zip_path.name}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to extract {zip_path.name}: {e}")
        return False


def process_extracted_zips():
    """Find and extract zips that don't contain Google Photos."""
    print(f"[INFO] Checking for zips to extract...")
    
    extracted_groups = 0
    skipped_photos = 0
    processed_files = set()
    
    for zip_path in sorted(GDRIVE_DIR.rglob("*.zip")):
        if not zip_path.is_file() or zip_path in processed_files:
            continue
        
        # Get all parts of this archive (if multi-part)
        related_parts = get_multipart_group(zip_path)
        
        # Check if any part contains Google Photos (let immich-go handle those)
        has_photos = False
        for part in related_parts:
            if has_google_photos(part):
                has_photos = True
                break
        
        if has_photos:
            print(f"[DEBUG] Skipping Google Photos archive (for immich-go): {zip_path.name}")
            if len(related_parts) > 1:
                print(f"[DEBUG]   Multi-part: {len(related_parts)} parts")
            skipped_photos += 1
            processed_files.update(related_parts)
            continue
        
        # Extract non-photos archives
        if extract_zip(zip_path, related_parts):
            extracted_groups += 1
        processed_files.update(related_parts)
    
    if extracted_groups > 0:
        print(f"[INFO] Extracted {extracted_groups} archive(s)")
    if skipped_photos > 0:
        print(f"[INFO] Skipped {skipped_photos} Google Photos archive(s) for immich-go")
    if extracted_groups == 0 and skipped_photos == 0:
        print(f"[INFO] No archives found to process")


def cleanup_existing_files():
    """Check remote files against local, delete remote if already exists with matching size."""
    print(f"[INFO] Checking for files already synced...")
    
    # Get list of files from remote with size and modification time
    cmd = [
        "rclone",
        "lsjson",
        "-R",  # Recursive
        RCLONE_REMOTE,
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        import json
        remote_files = json.loads(result.stdout)
        
        deleted_count = 0
        for remote_file in remote_files:
            if remote_file.get('IsDir'):
                continue
            
            remote_path = remote_file['Path']
            remote_size = remote_file['Size']
            
            # Check if file exists locally
            local_file = GDRIVE_DIR / remote_path
            if local_file.exists():
                local_size = local_file.stat().st_size
                
                # Compare size
                if local_size == remote_size:
                    print(f"[INFO] File already exists locally with matching size: {remote_path}")
                    # Delete from remote
                    delete_cmd = [
                        "rclone",
                        "deletefile",
                        f"{RCLONE_REMOTE}/{remote_path}",
                    ]
                    delete_result = subprocess.run(delete_cmd, capture_output=True, text=True)
                    if delete_result.returncode == 0:
                        deleted_count += 1
                        print(f"[INFO] Deleted from remote: {remote_path}")
                    else:
                        print(f"[WARNING] Failed to delete from remote: {remote_path}")
        
        if deleted_count > 0:
            print(f"[INFO] Cleaned up {deleted_count} files already synced")
        else:
            print(f"[INFO] No duplicate files found on remote")
            
    except subprocess.CalledProcessError as e:
        print(f"[WARNING] Failed to list remote files: {e}")
    except Exception as e:
        print(f"[WARNING] Error during cleanup: {e}")


def run_sync():
    """Run a single sync cycle - move all files from Google Drive to local storage."""
    cleanup_existing_files()
    
    # Run rclone move
    cmd = [
        "rclone",
        "move",
        RCLONE_REMOTE,
        str(GDRIVE_DIR),
        "--create-empty-src-dirs",
        "--verbose",
        "--stats", "10s",
        "--transfers", "4",
        "--delete-empty-src-dirs",
    ]
    
    print(f"[INFO] Starting rclone move from {RCLONE_REMOTE} to {GDRIVE_DIR}")
    result = subprocess.run(cmd)
    
    if result.returncode != 0:
        print("[ERROR] Rclone move failed")
        raise RuntimeError("rclone move failed")
    
    print("[INFO] Takeout sync complete.")
    
    # Extract any single-part zips (non-Takeout exports)
    process_extracted_zips()


def main():
    ensure_dirs()

    print(f"[INFO] Starting Takeout sync...")
    print(f"[INFO] Syncing to: {GDRIVE_DIR}")
    print(f"[INFO] NOTE: All files will be synced. immich-import will handle Google Takeout multi-part archives.")

    try:
        run_sync()
        print("[INFO] Takeout sync completed successfully")
    except Exception as e:
        print(f"[ERROR] Sync failed: {e}")
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
