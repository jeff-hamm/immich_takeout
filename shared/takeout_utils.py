#!/usr/bin/env python3
"""
Shared utilities for Google Takeout and Immich import processing.
Used by:
- takeout-backup (server_backup.py)
- immich-import (immich_import.py)
- sd-import (sd_import.py)
"""
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

# Import ImportMetadata class - handle both package and direct import
try:
    from .import_metadata import ImportMetadata
except ImportError:
    from import_metadata import ImportMetadata

# Media file extensions that Immich supports
MEDIA_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp',
    '.heic', '.heif', '.raw', '.cr2', '.nef', '.arw', '.dng',
    '.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v',
    '.3gp', '.3g2', '.mpeg', '.mpg', '.mts', '.m2ts'
}

# =============================================================================
# Common configuration - loaded from environment with sensible defaults
# =============================================================================
DEFAULT_IMMICH_SERVER = os.getenv("IMMICH_SERVER", "http://192.168.1.216:2283")
DEFAULT_IMMICH_API_URL = os.getenv("IMMICH_API_URL", f"{DEFAULT_IMMICH_SERVER}/api")
DEFAULT_IMMICH_API_KEY_FILE = os.getenv("IMMICH_API_KEY_FILE", "/run/secrets/immich_api_key")
DEFAULT_IMMICH_API_KEY = os.getenv("IMMICH_API_KEY", None)
DEFAULT_METADATA_DIR = Path(os.getenv("METADATA_DIR", "/data/metadata"))
DEFAULT_LOG_DIR = Path(os.getenv("LOG_DIR", str(DEFAULT_METADATA_DIR / "logs")))
DEFAULT_EXTRACT_DIR = Path(os.getenv("EXTRACT_DIR", "/data/extracted"))
DEFAULT_MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
DEFAULT_RETRY_DELAY = int(os.getenv("RETRY_DELAY", "30"))
DEFAULT_COPY_FAILED_FILES = os.getenv("COPY_FAILED_FILES", "false").lower() == "true"


def is_media_file(filename: str) -> bool:
    """Check if a filename is a supported media file."""
    return Path(filename).suffix.lower() in MEDIA_EXTENSIONS


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def is_google_photos_path(filepath: str) -> bool:
    """Check if a file path is inside a Google Photos folder."""
    return 'Google Photos' in filepath or "Google Foto's" in filepath


def get_zip_contents(zip_path: Path) -> dict[str, dict]:
    """Get a dict of all files in a zip with their sizes and metadata, keyed by path."""
    contents = {}
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for info in zf.infolist():
                if not info.is_dir():
                    filename = Path(info.filename).name
                    contents[info.filename] = {
                        "path": info.filename,
                        "filename": filename,
                        "size": info.file_size,
                        "is_media": is_media_file(filename),
                        "is_google_photos": is_google_photos_path(info.filename),
                        "is_json": filename.endswith('.json'),
                    }
    except Exception as e:
        print(f"[WARNING] Could not read zip contents: {e}")
    return contents


def get_folder_contents(folder_path: Path, base_path: Optional[Path] = None) -> dict[str, dict]:
    """Get a dict of all files in a folder with their sizes and metadata, keyed by relative path."""
    contents = {}
    base = base_path or folder_path
    
    try:
        for file_path in folder_path.rglob("*"):
            if file_path.is_file():
                try:
                    rel_path = str(file_path.relative_to(base))
                    filename = file_path.name
                    contents[rel_path] = {
                        "path": rel_path,
                        "filename": filename,
                        "size": file_path.stat().st_size,
                        "is_media": is_media_file(filename),
                        "is_google_photos": is_google_photos_path(rel_path),
                        "is_json": filename.endswith('.json'),
                    }
                except Exception as e:
                    print(f"[WARNING] Could not process {file_path}: {e}")
    except Exception as e:
        print(f"[WARNING] Could not read folder contents: {e}")
    return contents


def parse_log_entry(entry: dict) -> dict | None:
    """
    Parse a single immich-go JSON log entry and return a structured result.
    
    Returns a dict with:
        - event_type: 'file_result', 'discovery', 'album', 'tag', 'stack', 'info', 'error'
        - filename: (for file_result events)
        - status: uploaded, server_duplicate, local_duplicate, server_better, upgraded, error
        - reason: (optional) reason for status
        - album/tag: (for album/tag events)
        - message: original message
        - raw: original entry
    
    Returns None for uninteresting log entries.
    """
    msg = entry.get('msg', '')
    level = entry.get('level', '')
    result = {
        'message': msg,
        'raw': entry,
    }
    
    # File-specific results
    if 'file' in entry:
        file_path = entry['file']
        # Handle format like "takeout-xxx:Takeout/Google Photos/file.jpg"
        if ':' in file_path:
            file_path = file_path.split(':', 1)[1]
        filename = Path(file_path).name
        result['path'] = file_path
        result['filename'] = filename
        result['event_type'] = 'file_result'
        
        if msg == 'uploaded successfully':
            result['status'] = 'uploaded'
        elif msg == 'server has duplicate':
            result['status'] = 'server_duplicate'
            result['reason'] = 'Already exists on server'
        elif msg == 'local duplicate' or msg == 'discarded local duplicate':
            result['status'] = 'local_duplicate'
            result['reason'] = 'Duplicate in upload batch'
        elif msg == 'server has a better asset' or msg == 'discarded server better':
            result['status'] = 'server_better'
            result['reason'] = 'Server has better quality'
        elif msg == 'upgraded' or msg == 'server asset upgraded':
            result['status'] = 'upgraded'
            result['reason'] = 'Replaced server version'
        elif msg == 'added to album':
            result['event_type'] = 'album'
            result['album'] = entry.get('album', '')
        elif msg == 'tagged':
            result['event_type'] = 'tag'
            result['tag'] = entry.get('tag', '')
        elif level == 'ERROR' or 'error' in msg.lower():
            result['status'] = 'error'
            result['reason'] = entry.get('error', msg)
        else:
            # Unknown file event
            return None
        
        return result
    
    # Discovery events
    msg_lower = msg.lower()
    if 'scanned image' in msg_lower or msg == 'discovered image':
        result['event_type'] = 'discovery'
        result['media_type'] = 'image'
        return result
    elif 'scanned video' in msg_lower or msg == 'discovered video':
        result['event_type'] = 'discovery'
        result['media_type'] = 'video'
        return result
    
    # Album events
    if 'album created' in msg_lower or msg == 'album created':
        result['event_type'] = 'album_created'
        result['album'] = entry.get('album', '')
        return result
    
    # Stack events
    if msg == 'stacked' or 'stacked with' in msg_lower:
        result['event_type'] = 'stack'
        return result
    
    # Version info
    if 'version' in entry:
        result['event_type'] = 'info'
        result['version'] = entry['version']
        return result
    
    # General errors
    if level == 'ERROR':
        result['event_type'] = 'error'
        result['error'] = entry.get('error', msg)
        return result
    
    # Skip uninteresting entries
    return None


def status_to_disposition(status: str | None) -> str:
    """Convert immich-go status to disposition string."""
    if status in ('uploaded', 'upgraded'):
        return 'imported_to_immich'
    elif status in ('server_duplicate', 'local_duplicate', 'server_better'):
        return 'skipped_duplicate'
    elif status == 'error':
        return 'error'
    else:
        return 'processed'


def file_result_to_manifest_entry(filename: str, result: dict) -> dict:
    """
    Convert an immich-go file result to a manifest entry format.
    
    Args:
        filename: The filename
        result: Dict with 'status', 'reason', 'albums', 'tags' keys
    
    Returns:
        Dict with 'filename', 'immich_status', 'immich_reason', 'albums', 'tags', 'disposition'
    """
    status = result.get('status')
    return {
        'filename': filename,
        'immich_status': status,
        'immich_reason': result.get('reason'),
        'albums': result.get('albums', []),
        'tags': result.get('tags', []),
        'disposition': status_to_disposition(status),
    }


def parse_immich_go_log(log_file_path: str | Path) -> dict:
    """Parse immich-go JSON log file and extract per-file results and statistics."""
    results = {
        'summary': {
            'uploaded': 0,
            'server_duplicate': 0,
            'local_duplicate': 0,
            'server_better': 0,
            'upgraded': 0,
            'errors': 0,
            'albums_created': 0,
            'albums_updated': 0,
            'tagged': 0,
            'stacked': 0,
            'discovered_images': 0,
            'discovered_videos': 0,
            'start_time': None,
            'end_time': None,
            'duration_seconds': None,
            'immich_go_version': None,
            'albums': [],  # List of unique album names
            'tags': [],    # List of unique tag names
        },
        'files': {}  # Map of filename to status info
    }
    
    # Track unique albums and tags
    albums_set = set()
    tags_set = set()
    
    log_path = Path(log_file_path)
    if not log_path.exists():
        print(f"[WARNING] Log file not found: {log_file_path}")
        return results
    
    first_time = None
    last_time = None
    
    try:
        with open(log_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    msg = entry.get('msg', '')
                    level = entry.get('level', '')
                    
                    # Track timestamps for duration calculation
                    if 'time' in entry:
                        timestamp = entry['time']
                        if first_time is None:
                            first_time = timestamp
                        last_time = timestamp
                    
                    # Capture version info
                    if 'version' in entry:
                        results['summary']['immich_go_version'] = entry['version']
                    
                    # Track per-file results
                    if 'file' in entry:
                        # Extract just the filename from the path
                        file_path = entry['file']
                        # Handle format like "takeout-xxx:Takeout/Google Photos/file.jpg"
                        if ':' in file_path:
                            file_path = file_path.split(':', 1)[1]
                        filename = Path(file_path).name
                        
                        # Initialize file entry if not exists
                        if filename not in results['files']:
                            results['files'][filename] = {'status': None, 'reason': None, 'albums': [], 'tags': []}
                        results['files'][filename]['path'] = file_path
                        if msg == 'uploaded successfully':
                            results['files'][filename]['status'] = 'uploaded'
                            results['files'][filename]['reason'] = None
                            results['summary']['uploaded'] += 1
                        elif msg == 'server has duplicate':
                            results['files'][filename]['status'] = 'server_duplicate'
                            results['files'][filename]['reason'] = 'Already exists on server'
                            results['summary']['server_duplicate'] += 1
                        elif msg == 'local duplicate' or msg == 'discarded local duplicate':
                            results['files'][filename]['status'] = 'local_duplicate'
                            results['files'][filename]['reason'] = 'Duplicate in upload batch'
                            results['summary']['local_duplicate'] += 1
                        elif msg == 'server has a better asset' or msg == 'discarded server better':
                            results['files'][filename]['status'] = 'server_better'
                            results['files'][filename]['reason'] = 'Server has better quality'
                            results['summary']['server_better'] += 1
                        elif msg == 'upgraded' or msg == 'server asset upgraded':
                            results['files'][filename]['status'] = 'upgraded'
                            results['files'][filename]['reason'] = 'Replaced server version'
                            results['summary']['upgraded'] += 1
                        elif msg == 'added to album':
                            # Track album for this file
                            if 'album' in entry and entry['album'] not in results['files'][filename]['albums']:
                                results['files'][filename]['albums'].append(entry['album'])
                            results['summary']['albums_updated'] += 1
                            albums_set.add(entry.get('album', ''))
                        elif msg == 'tagged':
                            # Track tag for this file
                            if 'tag' in entry and entry['tag'] not in results['files'][filename]['tags']:
                                results['files'][filename]['tags'].append(entry['tag'])
                            results['summary']['tagged'] += 1
                            tags_set.add(entry.get('tag', ''))
                        elif level == 'ERROR' or 'error' in msg.lower():
                            error_detail = entry.get('error', msg)
                            results['files'][filename]['status'] = 'error'
                            results['files'][filename]['reason'] = error_detail
                            results['summary']['errors'] += 1
                    
                    # Track discovery and action counts (non-file specific)
                    msg_lower = msg.lower()
                    if 'scanned image' in msg_lower or msg == 'discovered image':
                        results['summary']['discovered_images'] += 1
                    elif 'scanned video' in msg_lower or msg == 'discovered video':
                        results['summary']['discovered_videos'] += 1
                    elif 'album created' in msg_lower or msg == 'album created':
                        results['summary']['albums_created'] += 1
                        if 'album' in entry:
                            albums_set.add(entry['album'])
                    elif msg == 'discovered sidecar' and entry.get('type') == 'album metadata':
                        # Capture album title from discovered sidecar
                        if 'title' in entry:
                            albums_set.add(entry['title'])
                    elif msg == 'stacked' or 'stacked with' in msg_lower:
                        results['summary']['stacked'] += 1
                        
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[WARNING] Error parsing log file: {e}")
    
    # Store sorted lists of albums and tags
    results['summary']['albums'] = sorted(albums_set)
    results['summary']['tags'] = sorted(tags_set)
    
    # Calculate duration
    results['summary']['start_time'] = first_time
    results['summary']['end_time'] = last_time
    if first_time and last_time:
        try:
            from datetime import datetime
            # Parse ISO format timestamps
            start = datetime.fromisoformat(first_time.replace('Z', '+00:00'))
            end = datetime.fromisoformat(last_time.replace('Z', '+00:00'))
            results['summary']['duration_seconds'] = (end - start).total_seconds()
        except Exception:
            pass
    
    total_discovered = results['summary']['discovered_images'] + results['summary']['discovered_videos']
    total_processed = (results['summary']['uploaded'] + results['summary']['server_duplicate'] +
                       results['summary']['local_duplicate'] + results['summary']['server_better'] +
                       results['summary']['upgraded'])
    
    print(f"[DEBUG] Parsed immich-go log: discovered={total_discovered}, processed={total_processed}, "
          f"uploaded={results['summary']['uploaded']}, duplicates={results['summary']['server_duplicate']}, "
          f"errors={results['summary']['errors']}")
    return results


def apply_immich_results_to_manifest(file_manifest: dict[str, dict], immich_results: dict) -> None:
    """Apply immich-go log results to the file manifest (modifies in place).
    
    Args:
        file_manifest: Dict keyed by path with file info dicts as values
        immich_results: Results from immich-go parsing
    """
    files_map = immich_results.get('files', {})
    
    for path, f in file_manifest.items():
        if not f.get('is_media', False):
            continue
        
        filename = f['filename']
        if filename in files_map:
            result = files_map[filename]
            f.update(file_result_to_manifest_entry(filename, result))
        else:
            # File not found in immich-go results
            f['immich_status'] = 'unknown'
            f['immich_reason'] = 'Not found in immich-go log'
            f['disposition'] = 'unknown'
            f['albums'] = []
            f['tags'] = []


def copy_log_to_metadata(log_file_path: str | Path, metadata_dir: Path) -> Optional[str]:
    """Copy immich-go log file to metadata/logs/ directory. Returns relative path."""
    log_path = Path(log_file_path).resolve()
    if not log_path.exists():
        return None
    
    logs_dir = metadata_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    dest_log_file = (logs_dir / log_path.name).resolve()
    
    # Check if source and destination are the same file
    if log_path == dest_log_file:
        print(f"[DEBUG] Log file already in metadata dir: {log_path.name}")
        return f"logs/{log_path.name}"
    
    try:
        shutil.copy2(log_path, dest_log_file)
        print(f"[DEBUG] Copied log to metadata: {dest_log_file.name}")
        return f"logs/{log_path.name}"
    except Exception as e:
        print(f"[WARNING] Failed to copy log file: {e}")
        return None


def create_extraction_only_metadata(
    zip_path: Path,
    extract_dir: Path,
    metadata_dir: Optional[Path] = None,
    related_parts: Optional[list[Path]] = None
) -> Path:
    """
    Create metadata for non-Google-Photos zip extraction.
    This is a standalone function for extraction-only operations.
    
    Delegates to ImportMetadata with extract_dir parameter.
    """
    parts = related_parts if related_parts else [zip_path]
    
    metadata = ImportMetadata(
        import_type='extract',
        source_type='google-takeout',
        metadata_dir=metadata_dir,
        zip_files=parts,
        extract_dir=extract_dir,
    )
    return metadata.save()


def get_immich_api_key(key_file: str = "/run/secrets/immich_api_key") -> str:
    """Read Immich API key from file or environment."""
    # Check environment first
    if os.getenv("IMMICH_API_KEY"):
        return os.getenv("IMMICH_API_KEY")
    
    # Then check file
    key_path = Path(key_file)
    if key_path.exists():
        return key_path.read_text().strip()
    
    raise RuntimeError(f"API key not found in environment or {key_file}")


def extract_non_imported_from_zip(
    zip_files: list[Path],
    extract_dir: Path,
    immich_results: dict,
    file_manifest: dict[str, dict],
    skip_google_photos: bool = True
) -> tuple[int, int]:
    """
    Extract files from zips that were NOT successfully imported to Immich.
    
    Args:
        zip_files: List of zip files to extract from
        extract_dir: Directory to extract to
        immich_results: Results from immich-go import
        file_manifest: Dict keyed by path with file info dicts as values
        skip_google_photos: If True, skip Google Photos content (already handled by immich-go)
    
    Returns:
        Tuple of (extracted_count, failed_count)
    """
    files_map = immich_results.get('files', {})
    
    extracted_count = 0
    failed_count = 0
    
    for zip_path in zip_files:
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    
                    # The manifest is keyed by path
                    manifest_entry = file_manifest.get(info.filename)
                    filename = Path(info.filename).name
                    
                    # Check if this file was imported to Immich
                    file_result = files_map.get(filename, {})
                    was_imported = is_imported_status(file_result.get('status', ''))
                    
                    # Skip Google Photos media that was imported
                    if skip_google_photos and is_google_photos_path(info.filename):
                        if is_media_file(filename) and was_imported:
                            if manifest_entry:
                                manifest_entry['disposition'] = 'imported_to_immich'
                            continue
                        elif info.filename.endswith('.json'):
                            if manifest_entry:
                                manifest_entry['disposition'] = 'skipped_json'
                            continue
                    
                    # Skip json metadata files
                    if info.filename.endswith('.json'):
                        if manifest_entry:
                            manifest_entry['disposition'] = 'skipped_json'
                        continue
                    
                    # Skip files that were successfully imported
                    if was_imported:
                        if manifest_entry:
                            manifest_entry['disposition'] = 'imported_to_immich'
                        continue
                    
                    # Extract this file
                    try:
                        target_path = extract_dir / info.filename
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        with zf.open(info) as src, open(target_path, 'wb') as dst:
                            dst.write(src.read())
                        
                        if target_path.exists() and target_path.stat().st_size == info.file_size:
                            extracted_count += 1
                            if manifest_entry:
                                manifest_entry['disposition'] = 'extracted'
                        else:
                            print(f"[WARNING] Size mismatch after extracting: {info.filename}")
                            failed_count += 1
                            if manifest_entry:
                                manifest_entry['disposition'] = 'extract_failed'
                    except Exception as e:
                        print(f"[WARNING] Failed to extract {info.filename}: {e}")
                        failed_count += 1
                        if manifest_entry:
                            manifest_entry['disposition'] = 'extract_failed'
                            
        except Exception as e:
            print(f"[WARNING] Could not read {zip_path.name} for extraction: {e}")
    
    if extracted_count > 0 or failed_count > 0:
        print(f"[INFO] Extracted {extracted_count} non-imported files to {extract_dir}")
        if failed_count > 0:
            print(f"[WARNING] {failed_count} files failed to extract")
    
    return extracted_count, failed_count


def copy_remaining_from_folder(
    source_folder: Path,
    extract_dir: Optional[Path],
    immich_results: dict,
    file_manifest: dict[str, dict],
    copy_failed: bool = False
) -> tuple[int, int, int]:
    """
    Identify and optionally copy files from folder that were NOT successfully imported to Immich.
    
    For folder imports (SD cards, etc), this updates the manifest with import status.
    Optionally copies failed files to a separate directory for review.
    
    Args:
        source_folder: Source folder to copy from
        extract_dir: Directory to copy to (only used if copy_failed=True)
        immich_results: Results from immich-go import
        file_manifest: Dict keyed by path with file info dicts as values
        copy_failed: If True, copy non-imported files to extract_dir
    
    Returns:
        Tuple of (imported_count, not_imported_count, copy_failed_count)
    """
    files_map = immich_results.get('files', {})
    
    imported_count = 0
    not_imported_count = 0
    copy_failed_count = 0
    
    for file_path, f in file_manifest.items():
        filename = f['filename']
        
        # Check if this file was imported to Immich
        file_result = files_map.get(filename, {})
        was_imported = is_imported_status(file_result.get('status', ''))
        
        if was_imported:
            f['disposition'] = 'imported_to_immich'
            imported_count += 1
            continue
        
        # Skip json files
        if file_path.endswith('.json'):
            f['disposition'] = 'skipped_json'
            continue
        
        # File was not imported
        not_imported_count += 1
        
        # Check if it had an error
        if file_result.get('status') == 'error':
            f['disposition'] = 'error'
        elif file_result.get('status'):
            f['disposition'] = file_result.get('status')
        else:
            f['disposition'] = 'not_processed'
        
        # Optionally copy to extract dir
        if copy_failed and extract_dir:
            source_path = source_folder / file_path
            if not source_path.exists():
                continue
                
            try:
                target_path = extract_dir / file_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
                
                if target_path.exists() and target_path.stat().st_size == source_path.stat().st_size:
                    f['disposition'] = 'copied_for_review'
                else:
                    print(f"[WARNING] Size mismatch after copying: {file_path}")
                    copy_failed_count += 1
                    f['disposition'] = 'copy_failed'
            except Exception as e:
                print(f"[WARNING] Failed to copy {file_path}: {e}")
                copy_failed_count += 1
                f['disposition'] = 'copy_failed'
    
    if not_imported_count > 0:
        print(f"[INFO] {imported_count} files imported, {not_imported_count} not imported")
        if copy_failed and extract_dir:
            print(f"[INFO] Copied {not_imported_count - copy_failed_count} non-imported files to {extract_dir}")
    
    return imported_count, not_imported_count, copy_failed_count


# Re-export ImportProcessor and ImmichGoRunner for backwards compatibility
try:
    from .import_processor import ImportProcessor
    from .immich_go_runner import ImmichGoRunner
except ImportError:
    from import_processor import ImportProcessor
    from immich_go_runner import ImmichGoRunner

__all__ = [
    'ImportMetadata',
    'ImportProcessor',
    'ImmichGoRunner',
    'MEDIA_EXTENSIONS',
    'DEFAULT_IMMICH_SERVER',
    'DEFAULT_IMMICH_API_URL',
    'DEFAULT_METADATA_DIR',
    'DEFAULT_LOG_DIR',
    'DEFAULT_EXTRACT_DIR',
    'DEFAULT_MAX_RETRIES',
    'DEFAULT_RETRY_DELAY',
    'DEFAULT_COPY_FAILED_FILES',
    'is_media_file',
    'format_size',
    'is_google_photos_path',
    'get_zip_contents',
    'get_folder_contents',
    'parse_log_entry',
    'parse_immich_go_log',
    'status_to_disposition',
    'is_imported_status',
    'file_result_to_manifest_entry',
    'apply_immich_results_to_manifest',
    'copy_log_to_metadata',
    'create_extraction_only_metadata',
    'get_immich_api_key',
    'extract_non_imported_from_zip',
    'copy_remaining_from_folder',
]
