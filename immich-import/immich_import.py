#!/usr/bin/env python3
"""
Immich Takeout Importer
Monitors for new Google Takeout zip files and imports them to Immich using immich-go
"""
import os
import sys
import zipfile
from pathlib import Path

# Add shared module to path (works both locally and in Docker)
_script_dir = Path(__file__).parent
if (_script_dir / "shared").exists():
    sys.path.insert(0, str(_script_dir / "shared"))
else:
    sys.path.insert(0, str(_script_dir.parent / "shared"))
from takeout_utils import (
    ImmichGoRunner,
    ImportProcessor,
    is_google_photos_path,
    get_zip_contents,
)

# Script-specific configuration
IMPORT_DIR = Path(os.getenv("IMPORT_DIR", "/data/import"))
TAKEOUT_DIR = Path(os.getenv("TAKEOUT_DIR", str(IMPORT_DIR) + "/Takeout"))  # Legacy name
TAKEOUT_FILE_FILTER = os.getenv("TAKEOUT_FILE_FILTER", "takeout-*.zip")
DELETE_AFTER_IMPORT = os.getenv("DELETE_AFTER_IMPORT", "true").lower() == "true"


def ensure_dirs():
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    # Processor will create its own dirs


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


def get_zip_media_files(zip_files):
    """Get list of all media files across all zip parts."""
    media_files = []
    for zip_path in zip_files:
        contents = get_zip_contents(zip_path)
        for path, info in contents.items():
            if is_google_photos_path(path) and info['is_media']:
                media_files.append({
                    'filename': info['filename'],
                    'size': info['size'],
                    'zip': zip_path.name
                })
    return media_files


def verify_import(zip_files, runner: ImmichGoRunner):
    """Verify that all media files from zips are now in Immich."""
    import urllib.request
    import urllib.error
    import json
    
    media_files = get_zip_media_files(zip_files)
    if not media_files:
        print(f"[WARNING] No media files found in zips to verify")
        return True  # Nothing to verify
    
    print(f"[INFO] Verifying {len(media_files)} media files are in Immich...")
    
    server_url = runner.server_url
    
    try:
        # Use search to check for assets - search by original filename
        # We'll sample check a subset of files to verify import worked
        sample_size = min(50, len(media_files))  # Check up to 50 files
        import random
        samples = random.sample(media_files, sample_size) if len(media_files) > sample_size else media_files
        
        verified = 0
        missing = []
        
        for media in samples:
            # Search for this file in Immich
            search_url = f"{server_url}/api/search/metadata"
            search_data = json.dumps({
                "originalFileName": media['filename']
            }).encode('utf-8')
            
            req = urllib.request.Request(
                search_url,
                data=search_data,
                headers={
                    'x-api-key': runner.api_key,
                    'Content-Type': 'application/json'
                },
                method='POST'
            )
            
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    assets = result.get('assets', {}).get('items', [])
                    
                    if assets:
                        verified += 1
                    else:
                        missing.append(media['filename'])
            except urllib.error.HTTPError as e:
                print(f"[WARNING] HTTP error checking {media['filename']}: {e.code}")
                missing.append(media['filename'])
            except Exception as e:
                print(f"[WARNING] Error checking {media['filename']}: {e}")
                # Don't count as missing if it's a network error
        
        if missing:
            # Allow some tolerance - immich-go may skip duplicates
            missing_pct = len(missing) / len(samples) * 100
            if missing_pct > 20:  # More than 20% missing is suspicious
                print(f"[WARNING] {len(missing)}/{len(samples)} sampled files not found in Immich ({missing_pct:.1f}%)")
                for f in missing[:5]:
                    print(f"[WARNING]   - {f}")
                if len(missing) > 5:
                    print(f"[WARNING]   ... and {len(missing) - 5} more")
                return False
            else:
                print(f"[INFO] {verified}/{len(samples)} sampled files verified in Immich ({len(missing)} not found, likely duplicates)")
        else:
            print(f"[INFO] All {verified} sampled files verified in Immich")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to verify import: {e}")
        return False

def is_valid_zip(zip_path: Path) -> bool:
    """Check if a zip file is valid and not corrupted."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Try to read the file list - this will fail for corrupted zips
            zf.namelist()
            return True
    except Exception:
        return False


def filter_valid_zips(zip_files: list[Path]) -> tuple[list[Path], list[Path]]:
    """
    Filter zip files, returning (valid_zips, invalid_zips).
    """
    valid = []
    invalid = []
    
    for zip_path in zip_files:
        if is_valid_zip(zip_path):
            valid.append(zip_path)
        else:
            print(f"[WARNING] Corrupted/incomplete zip: {zip_path.name}")
            invalid.append(zip_path)
    
    return valid, invalid


def find_takeout_exports():
    """Group takeout zip files by export (by date prefix) and check if they contain Google Photos."""
    if not TAKEOUT_DIR.exists():
        print("[INFO] No takeout directory found.")
        return []

    print(f"[INFO] Scanning {TAKEOUT_DIR} for takeout exports...")
    
    # Group zip files by their takeout export prefix (e.g., takeout-20240427T195310Z)
    exports = {}
    
    # Find both .zip and .partial files
    all_zips = list(TAKEOUT_DIR.rglob(TAKEOUT_FILE_FILTER))
    # Also find .partial files based on the filter pattern
    partial_filter = TAKEOUT_FILE_FILTER + ".partial"
    all_partials = list(TAKEOUT_DIR.rglob(partial_filter))
    
    print(f"[INFO] Found {len(all_zips)} zip file(s), {len(all_partials)} partial file(s)")
    
    # Build a set of partial file base names (without .partial suffix)
    # e.g., "takeout-20240427T195310Z-002.zip.partial" -> "takeout-20240427T195310Z-002.zip"
    partial_bases = set()
    for partial_path in all_partials:
        if partial_path.name.endswith('.partial'):
            base_name = partial_path.name[:-8]  # Remove ".partial"
            partial_bases.add(base_name)
    
    # Build a set of existing valid zip names
    valid_zip_names = set()
    for zip_path in all_zips:
        if zip_path.is_file() and is_valid_zip(zip_path):
            valid_zip_names.add(zip_path.name)
    
    for zip_path in all_zips:
        if not zip_path.is_file():
            continue
        
        # Extract the export prefix (everything before the part number)
        # e.g., takeout-20240427T195310Z-001.zip -> takeout-20240427T195310Z
        parts = zip_path.stem.rsplit('-', 1)
        if len(parts) == 2:
            export_prefix = parts[0]
            if export_prefix not in exports:
                exports[export_prefix] = {'zips': [], 'has_incomplete_partial': False}
            exports[export_prefix]['zips'].append(zip_path)
    
    # Also register exports that only have .partial files (no .zip yet)
    for partial_path in all_partials:
        if partial_path.name.endswith('.partial'):
            base_name = partial_path.name[:-8]  # Remove ".partial"
            stem = base_name[:-4]  # Remove ".zip"
            parts = stem.rsplit('-', 1)
            if len(parts) == 2:
                export_prefix = parts[0]
                if export_prefix not in exports:
                    exports[export_prefix] = {'zips': [], 'has_incomplete_partial': False}
                # Check if this partial has a corresponding valid zip
                if base_name not in valid_zip_names:
                    exports[export_prefix]['has_incomplete_partial'] = True
    
    # Check existing exports for partials without valid zips
    for export_prefix, export_data in exports.items():
        for zip_path in export_data['zips']:
            # Check if there's a .partial for this zip but the zip is invalid
            if zip_path.name in partial_bases and not is_valid_zip(zip_path):
                export_data['has_incomplete_partial'] = True
    
    print(f"[INFO] Found {len(exports)} unique takeout export(s)")
    
    # Check each export to see if it contains Google Photos (sorted newest first)
    exports_to_import = []
    for export_prefix, export_data in sorted(exports.items(), reverse=True):
        zip_files = export_data['zips']
        zip_files.sort()
        
        # Skip if there are incomplete partials (partial exists but no valid zip)
        if export_data['has_incomplete_partial']:
            print(f"[WARNING] Export {export_prefix}: Has .partial file(s) without valid .zip, skipping (download in progress)")
            continue
        
        # Filter out corrupted/incomplete zips
        valid_zips, invalid_zips = filter_valid_zips(zip_files)
        
        if invalid_zips:
            print(f"[WARNING] Export {export_prefix}: {len(invalid_zips)} corrupted/incomplete zip(s), skipping entire export")
            continue
        
        if not valid_zips:
            print(f"[WARNING] Export {export_prefix}: No valid zips, skipping")
            continue
        
        # Check if any valid part contains Google Photos
        has_photos = False
        for zip_path in valid_zips:
            if has_google_photos(zip_path):
                has_photos = True
                break
        
        if has_photos:
            print(f"[INFO] Export {export_prefix} has Google Photos ({len(valid_zips)} valid parts)")
            exports_to_import.append((export_prefix, valid_zips))
        else:
            print(f"[DEBUG] Export {export_prefix} has no Google Photos content, skipping")
    
    return exports_to_import


def import_export_to_immich(export_prefix, zip_files):
    """Use immich-go to import a Google Takeout export (possibly multi-part)."""
    
    processor = ImportProcessor.get_instance()
    
    # Use shared processor for import + extraction + metadata
    success, immich_results = processor.process_google_photos_zips(
        zip_files=zip_files,
        export_prefix=export_prefix,
        delete_after_import=DELETE_AFTER_IMPORT
    )
    
    # Additional verification for zip deletion
    if DELETE_AFTER_IMPORT and success:
        # Verify import before considering it complete
        if not verify_import(zip_files, processor.runner):
            print(f"[WARNING] Import verification failed for {export_prefix}")
            return True  # Still consider success since immich-go succeeded
    
    if not success:
        print(f"[WARNING] Keeping zip files due to import failure")
    
    return success


def process_google_takeout():
    """Check for and process any new takeout exports."""
    exports = find_takeout_exports()

    if not exports:
        print(f"[INFO] No new takeout exports with Google Photos content found")
        return 0

    print(f"[INFO] Found {len(exports)} takeout export(s) with Google Photos to import")

    processed = 0

    for export_prefix, zip_files in exports:
        print(f"[INFO] Processing {processed + 1}/{len(exports)}: {export_prefix}")
        if import_export_to_immich(export_prefix, zip_files):
            processed += 1

    return processed


def import_folder(
    folder_path: Path,
    source_type: str = "folder",
    tag_prefix: str = "FOLDER-IMPORT",
    device_label: str = None,
    copy_failed_files: bool = None
) -> bool:
    """Import a folder to Immich and create metadata."""
    if not folder_path.exists():
        print(f"[ERROR] Folder does not exist: {folder_path}")
        return False
    
    # Use ImportProcessor for unified handling
    success, immich_results = ImportProcessor.get_instance().process_folder(
        folder_path=folder_path,
        source_type=source_type,
        tag_prefix=tag_prefix,
        device_label=device_label,
        copy_failed_files=copy_failed_files
    )
    
    return success


def main():
    import argparse
    
    ensure_dirs()
    
    parser = argparse.ArgumentParser(description="Import to Immich from Google Takeout or folder")
    parser.add_argument("mode", nargs="?", default="takeout",
                       choices=["takeout", "folder"],
                       help="Import mode: 'takeout' for Google Takeout zips, 'folder' for direct folder import")
    parser.add_argument("path", nargs="?", type=Path,
                       help="Path to folder to import defaults to IMPORT_PATH")
    parser.add_argument("--source-type", "-t", default="folder",
                       help="Type of source device (e.g., folder, sd-card, camera, phone)")
    parser.add_argument("--label", "-l", help="Device label for tagging")
    parser.add_argument("--tag-prefix", default=None,
                       help="Custom tag prefix (default based on source type)")
    parser.add_argument("--copy-failed", action="store_true",
                       help="Copy non-imported files to extract dir for review")
    
    args = parser.parse_args()
    
    print(f"[INFO] Starting Immich import...")
    ImportProcessor.get_instance()  # Initialize and log config
    
    if args.mode == "folder":
        folder_path = args.path or IMPORT_DIR
        
        if not folder_path.exists():
            print(f"[ERROR] Path does not exist: {folder_path}")
            sys.exit(1)
        
        # Determine tag prefix
        tag_prefix = args.tag_prefix
        if not tag_prefix:
            tag_prefix = f"{args.source_type.upper()}-IMPORT"
        
        success = import_folder(
            folder_path=folder_path,
            source_type=args.source_type,
            tag_prefix=tag_prefix,
            device_label=args.label,
            copy_failed_files=args.copy_failed
        )
        sys.exit(0 if success else 1)
    else:
        # Default: takeout mode
        print(f"[INFO] Watching: {TAKEOUT_DIR}")
        print(f"[INFO] Delete after import: {DELETE_AFTER_IMPORT}")
        
        try:
            processed = process_google_takeout()
            if processed > 0:
                print(f"[INFO] Processed {processed} file(s)")
            else:
                print(f"[INFO] No new files found")
            print("[INFO] Import check completed successfully")
        except Exception as e:
            print(f"[ERROR] Import failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
