#!/usr/bin/env python3
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

# Add shared module to path (works both locally and in Docker)
_script_dir = Path(__file__).parent
if (_script_dir / "shared").exists():
    sys.path.insert(0, str(_script_dir / "shared"))
else:
    sys.path.insert(0, str(_script_dir.parent / "shared"))
from import_metadata import ImportMetadata

# CONFIGURABLE PATHS (mapped in container)
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "gdrive:Takeout")  # rclone remote:path where Takeout exports appear
GDRIVE_DIR = Path(os.getenv("GDRIVE_DIR", "/data/gdrive/Takeout"))  # Primary sync location
METADATA_DIR = Path(os.getenv("METADATA_DIR", "/data/metadata"))  # Extraction metadata directory
DELETE_AFTER_EXTRACT = os.getenv("DELETE_AFTER_EXTRACT", "true").lower() == "true"


def save_extraction_metadata(zip_path, extract_dir, related_parts=None):
    """Save metadata about extracted files to a JSON file using ImportMetadata."""
    try:
        parts = related_parts if related_parts else [zip_path]
        metadata = ImportMetadata(
            import_type='extract',
            source_type='google-takeout',
            metadata_dir=METADATA_DIR,
            zip_files=parts,
            extract_dir=extract_dir,
        )
        metadata.save()
        return True
    except Exception as e:
        print(f"[WARNING] Failed to save metadata: {e}")
        return False


def ensure_dirs():
    GDRIVE_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)


def is_valid_zip(zip_path):
    """Check if a zip file is valid and not corrupted."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Test the zip file integrity
            bad_file = zf.testzip()
            if bad_file:
                print(f"[WARNING] Corrupted file in zip: {bad_file}")
                return False
            return True
    except zipfile.BadZipFile as e:
        print(f"[WARNING] Invalid/corrupted zip file {zip_path.name}: {e}")
        return False
    except Exception as e:
        print(f"[WARNING] Error checking zip file {zip_path.name}: {e}")
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


def verify_extraction(zip_path, extract_dir):
    """Verify that all files from a zip were extracted correctly."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            missing_files = []
            size_mismatches = []
            
            for info in zf.infolist():
                # Skip directories
                if info.is_dir():
                    continue
                
                extracted_path = extract_dir / info.filename
                
                if not extracted_path.exists():
                    missing_files.append(info.filename)
                elif extracted_path.stat().st_size != info.file_size:
                    size_mismatches.append((info.filename, info.file_size, extracted_path.stat().st_size))
            
            if missing_files:
                print(f"[ERROR] Missing {len(missing_files)} files after extraction:")
                for f in missing_files[:5]:  # Show first 5
                    print(f"[ERROR]   - {f}")
                if len(missing_files) > 5:
                    print(f"[ERROR]   ... and {len(missing_files) - 5} more")
                return False
            
            if size_mismatches:
                print(f"[ERROR] {len(size_mismatches)} files have size mismatches:")
                for f, expected, actual in size_mismatches[:5]:
                    print(f"[ERROR]   - {f}: expected {expected}, got {actual}")
                return False
            
            return True
    except Exception as e:
        print(f"[ERROR] Failed to verify extraction: {e}")
        return False


def extract_zip(zip_path, related_parts=None):
    """Extract a zip file (single or multi-part) and remove the original(s) after verification."""
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
        
        # Verify extraction before considering deletion
        parts_to_verify = related_parts if related_parts else [zip_path]
        all_verified = True
        
        for part in parts_to_verify:
            if not verify_extraction(part, extract_dir):
                print(f"[ERROR] Verification failed for {part.name}, keeping zip files")
                all_verified = False
                break
        
        if not all_verified:
            if related_parts and len(related_parts) > 1:
                print(f"[WARNING] Extracted {len(related_parts)} parts but verification failed, keeping originals")
            else:
                print(f"[WARNING] Extracted {zip_path.name} but verification failed, keeping original")
            return True  # Extraction succeeded, just not deleting
        
        print(f"[DEBUG] Verified all files extracted correctly")
        
        # Save extraction metadata before deletion
        save_extraction_metadata(zip_path, extract_dir, related_parts)
        
        # Remove all parts after successful extraction AND verification
        if DELETE_AFTER_EXTRACT:
            parts_to_remove = related_parts if related_parts else [zip_path]
            for part in parts_to_remove:
                if part.exists():
                    part.unlink()
            
            if related_parts and len(related_parts) > 1:
                print(f"[INFO] Extracted, verified, and removed {len(related_parts)} parts")
            else:
                print(f"[INFO] Extracted, verified, and removed: {zip_path.name}")
        else:
            if related_parts and len(related_parts) > 1:
                print(f"[INFO] Extracted and verified {len(related_parts)} parts (kept originals)")
            else:
                print(f"[INFO] Extracted and verified: {zip_path.name} (kept original)")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to extract {zip_path.name}: {e}")
        return False


def process_extracted_zips():
    """Find and extract zips that don't contain Google Photos."""
    print(f"[INFO] Checking for zips to extract...")
    
    extracted_groups = 0
    skipped_photos = 0
    skipped_corrupt = 0
    processed_files = set()
    
    for zip_path in sorted(GDRIVE_DIR.rglob("*.zip")):
        if not zip_path.is_file() or zip_path in processed_files:
            continue
        
        # Check if zip is valid/complete first
        if not is_valid_zip(zip_path):
            print(f"[WARNING] Skipping corrupted/incomplete zip: {zip_path.name}")
            skipped_corrupt += 1
            processed_files.add(zip_path)
            continue
        
        # Get all parts of this archive (if multi-part)
        related_parts = get_multipart_group(zip_path)
        
        # Validate all parts if multi-part
        if len(related_parts) > 1:
            all_valid = True
            for part in related_parts:
                if not is_valid_zip(part):
                    print(f"[WARNING] Multi-part archive has corrupted part: {part.name}")
                    all_valid = False
                    break
            
            if not all_valid:
                print(f"[WARNING] Skipping incomplete multi-part archive ({len(related_parts)} parts)")
                processed_files.update(related_parts)
                continue
        
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
    if skipped_corrupt > 0:
        print(f"[INFO] Skipped {skipped_corrupt} corrupted/incomplete zip file(s)")
    if extracted_groups == 0 and skipped_photos == 0 and skipped_corrupt == 0:
        print(f"[INFO] No archives found to process")


def run_sync():
    """Run a single sync cycle - move all files from Google Drive to local storage."""
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
    print(f"[INFO] Delete after extract: {DELETE_AFTER_EXTRACT}")
    print(f"[INFO] NOTE: Google Photos archives are left for immich-import.")

    try:
        run_sync()
        print("[INFO] Takeout sync completed successfully")
    except Exception as e:
        print(f"[ERROR] Sync failed: {e}")
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
