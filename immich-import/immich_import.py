#!/usr/bin/env python3
"""
Immich Takeout Importer
Monitors for new Google Takeout zip files and imports them to Immich using immich-go
"""
import os
import subprocess
import time
import hashlib
import zipfile
from pathlib import Path

# CONFIGURABLE PATHS
TAKEOUT_RAW_DIR = Path("/data/photos/import")
IMMICH_API_URL = os.getenv("IMMICH_API_URL", "http://192.168.1.216:2283/api")
IMMICH_API_KEY_FILE = os.getenv("IMMICH_API_KEY_FILE", "/run/secrets/immich_api_key")
IMPORTED_CACHE_FILE = Path("/cache/imported_files.txt")


def ensure_dirs():
    TAKEOUT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    IMPORTED_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_imported_cache():
    """Load the set of already imported file signatures."""
    if not IMPORTED_CACHE_FILE.exists():
        return set()
    return set(line.strip() for line in IMPORTED_CACHE_FILE.read_text().strip().split('\n') if line.strip())


def save_imported_signature(signature):
    """Append a file signature to the imported cache."""
    with open(IMPORTED_CACHE_FILE, 'a') as f:
        f.write(f"{signature}\n")


def get_file_signature(file_path):
    """Get a unique signature for a file based on name, size, and mtime."""
    stat = file_path.stat()
    return f"{file_path.name}|{stat.st_size}|{int(stat.st_mtime)}"


def has_google_photos(zip_path):
    """Check if a zip file contains a Google Photos directory."""
    try:
        print(f"[DEBUG] Inspecting {zip_path.name} ({zip_path.stat().st_size / (1024**3):.2f} GB)")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                if "Google Photos" in name or "Google Foto's" in name:
                    print(f"[DEBUG] Found Google Photos content in {zip_path.name}")
                    return True
        print(f"[DEBUG] No Google Photos content in {zip_path.name}")
        return False
    except Exception as e:
        print(f"[WARNING] Could not inspect {zip_path.name}: {e}")
        return False


def get_api_key():
    """Read API key from file."""
    if not Path(IMMICH_API_KEY_FILE).exists():
        raise RuntimeError(f"API key file not found: {IMMICH_API_KEY_FILE}")
    return Path(IMMICH_API_KEY_FILE).read_text().strip()


def find_takeout_exports():
    """Group takeout zip files by export (by date prefix) and check if they contain Google Photos."""
    if not TAKEOUT_RAW_DIR.exists():
        print("[INFO] No takeout directory found.")
        return []

    print(f"[INFO] Scanning {TAKEOUT_RAW_DIR} for takeout exports...")
    imported_cache = load_imported_cache()
    print(f"[INFO] Loaded {len(imported_cache)} previously imported exports from cache")
    
    # Group zip files by their takeout export prefix (e.g., takeout-20240427T195310Z)
    exports = {}
    all_zips = list(TAKEOUT_RAW_DIR.rglob("takeout-*.zip"))
    print(f"[INFO] Found {len(all_zips)} total zip file(s)")
    
    for zip_path in all_zips:
        if not zip_path.is_file():
            continue
        
        # Extract the export prefix (everything before the part number)
        # e.g., takeout-20240427T195310Z-001.zip -> takeout-20240427T195310Z
        parts = zip_path.stem.rsplit('-', 1)
        if len(parts) == 2:
            export_prefix = parts[0]
            if export_prefix not in exports:
                exports[export_prefix] = []
            exports[export_prefix].append(zip_path)
    
    print(f"[INFO] Found {len(exports)} unique takeout export(s)")
    
    # Check each export to see if it contains Google Photos and hasn't been imported
    exports_to_import = []
    for export_prefix, zip_files in sorted(exports.items()):
        # Create a signature for the entire export based on all parts
        zip_files.sort()
        export_signature = f"{export_prefix}|{len(zip_files)}|{','.join(str(z.stat().st_size) for z in zip_files)}"
        
        if export_signature in imported_cache:
            print(f"[DEBUG] Skipping already imported export: {export_prefix} ({len(zip_files)} parts)")
            continue
        
        # Check if any part contains Google Photos
        has_photos = False
        for zip_path in zip_files:
            if has_google_photos(zip_path):
                has_photos = True
                break
        
        if has_photos:
            print(f"[INFO] Export {export_prefix} has Google Photos ({len(zip_files)} parts)")
            exports_to_import.append((export_prefix, zip_files, export_signature))
        else:
            print(f"[DEBUG] Export {export_prefix} has no Google Photos content, skipping")
    
    return exports_to_import


def import_export_to_immich(export_prefix, zip_files, signature, api_key):
    """Use immich-go to import a Google Takeout export (possibly multi-part)."""
    server_url = IMMICH_API_URL.replace("/api", "")
    
    # For multi-part archives, pass the directory or pattern
    # immich-go is smart enough to handle all parts together
    if len(zip_files) == 1:
        target = str(zip_files[0])
    else:
        # Use the parent directory - immich-go will find all related parts
        target = str(zip_files[0].parent)
    
    cmd = [
        "immich-go",
        "upload",
        "from-google-photos",
        "-s", server_url,
        "-k", api_key,
        "--log-level=DEBUG",
        "--manage-raw-jpeg=StackCoverRaw",
        "--manage-burst=Stack",
        "--sync-albums",
        "--include-untitled-albums",
        "--people-tag",
        "--takeout-tag",
        "--include-archived",
        "--include-unmatched",
        "--session-tag",
        target,
    ]

    total_size_gb = sum(z.stat().st_size for z in zip_files) / (1024**3)
    print(f"[INFO] Importing takeout export: {export_prefix}")
    print(f"[INFO]   Parts: {len(zip_files)}")
    print(f"[INFO]   Total size: {total_size_gb:.2f} GB")
    print(f"[INFO]   Files: {', '.join(z.name for z in sorted(zip_files))}")
    
    # Log the actual command (mask the API key)
    cmd_display = ' '.join(cmd).replace(api_key, '***')
    print(f"[INFO]   Command: {cmd_display}")

    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"[ERROR] immich-go import failed for {export_prefix} (exit code: {result.returncode})")
        return False

    print(f"[INFO] Successfully imported {export_prefix}")
    
    # Save signature to cache
    save_imported_signature(signature)
    print(f"[DEBUG] Saved signature to cache: {signature}")
    
    return True


def process_new_files():
    """Check for and process any new takeout exports."""
    exports = find_takeout_exports()

    if not exports:
        print(f"[INFO] No new takeout exports with Google Photos content found")
        return 0

    print(f"[INFO] Found {len(exports)} takeout export(s) with Google Photos to import")

    api_key = get_api_key()
    processed = 0

    for export_prefix, zip_files, signature in exports:
        print(f"[INFO] Processing {processed + 1}/{len(exports)}: {export_prefix}")
        if import_export_to_immich(export_prefix, zip_files, signature, api_key):
            processed += 1

    return processed


def main():
    ensure_dirs()

    print(f"[INFO] Starting Immich Takeout import...")
    print(f"[INFO] Watching: {TAKEOUT_RAW_DIR}")
    print(f"[INFO] Immich server: {IMMICH_API_URL.replace('/api', '')}")

    try:
        processed = process_new_files()
        if processed > 0:
            print(f"[INFO] Processed {processed} file(s)")
        else:
            print(f"[INFO] No new files found")
        print("[INFO] Import check completed successfully")
    except Exception as e:
        print(f"[ERROR] Import failed: {e}")
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
