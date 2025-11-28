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
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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


def get_zip_contents(zip_path: Path) -> list[dict]:
    """Get a list of all files in a zip with their sizes and metadata."""
    contents = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for info in zf.infolist():
                if not info.is_dir():
                    filename = Path(info.filename).name
                    contents.append({
                        "path": info.filename,
                        "filename": filename,
                        "size": info.file_size,
                        "is_media": is_media_file(filename),
                        "is_google_photos": is_google_photos_path(info.filename),
                        "is_json": filename.endswith('.json'),
                    })
    except Exception as e:
        print(f"[WARNING] Could not read zip contents: {e}")
    return contents


def get_folder_contents(folder_path: Path, base_path: Optional[Path] = None) -> list[dict]:
    """Get a list of all files in a folder with their sizes and metadata."""
    contents = []
    base = base_path or folder_path
    
    try:
        for file_path in folder_path.rglob("*"):
            if file_path.is_file():
                try:
                    rel_path = str(file_path.relative_to(base))
                    filename = file_path.name
                    contents.append({
                        "path": rel_path,
                        "filename": filename,
                        "size": file_path.stat().st_size,
                        "is_media": is_media_file(filename),
                        "is_google_photos": is_google_photos_path(rel_path),
                        "is_json": filename.endswith('.json'),
                    })
                except Exception as e:
                    print(f"[WARNING] Could not process {file_path}: {e}")
    except Exception as e:
        print(f"[WARNING] Could not read folder contents: {e}")
    return contents


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


def apply_immich_results_to_manifest(file_manifest: list[dict], immich_results: dict) -> None:
    """Apply immich-go log results to the file manifest (modifies in place)."""
    files_map = immich_results.get('files', {})
    
    for f in file_manifest:
        if not f.get('is_media', False):
            continue
        
        filename = f['filename']
        if filename in files_map:
            result = files_map[filename]
            f['immich_status'] = result.get('status')
            f['immich_reason'] = result.get('reason')
            f['albums'] = result.get('albums', [])
            f['tags'] = result.get('tags', [])
            
            # Update disposition based on status
            if result.get('status') in ('uploaded', 'upgraded'):
                f['disposition'] = 'imported_to_immich'
            elif result.get('status') in ('server_duplicate', 'local_duplicate', 'server_better'):
                f['disposition'] = 'skipped_duplicate'
            elif result.get('status') == 'error':
                f['disposition'] = 'error'
            else:
                f['disposition'] = 'processed'
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


class MetadataBuilder:
    """Builder class for creating import metadata files."""
    
    def __init__(self, metadata_dir: Optional[Path] = None):
        self.metadata_dir = metadata_dir or DEFAULT_METADATA_DIR
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
    
    def create_extraction_metadata(
        self,
        source_name: str,
        import_type: str,  # 'extract', 'immich-go', 'sd-import'
        source_type: str,  # 'google-takeout', 'google-photos', 'sd-card', 'folder'
        files: list[dict],
        total_size: int = 0,
        extra_fields: Optional[dict] = None
    ) -> dict:
        """Create base metadata structure."""
        metadata = {
            "import_type": import_type,
            "source_type": source_type,
            "source_name": source_name,
            "total_size": total_size,
            "extraction_date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "total_files": len(files),
            "files": files,
        }
        
        if extra_fields:
            metadata.update(extra_fields)
        
        # Calculate summary
        metadata["summary"] = self._calculate_summary(files, import_type)
        
        return metadata
    
    def _calculate_summary(self, files: list[dict], import_type: str) -> dict:
        """Calculate summary statistics from file list."""
        summary = {
            "total": len(files),
            "media_files": sum(1 for f in files if f.get('is_media', False)),
            "json_files": sum(1 for f in files if f.get('is_json', False)),
        }
        
        if import_type == 'immich-go' or import_type == 'sd-import':
            summary.update({
                "uploaded_success": sum(1 for f in files if f.get('immich_status') == 'uploaded'),
                "server_duplicate": sum(1 for f in files if f.get('immich_status') == 'server_duplicate'),
                "local_duplicate": sum(1 for f in files if f.get('immich_status') == 'local_duplicate'),
                "server_better": sum(1 for f in files if f.get('immich_status') == 'server_better'),
                "upgraded": sum(1 for f in files if f.get('immich_status') == 'upgraded'),
                "errors": sum(1 for f in files if f.get('immich_status') == 'error'),
            })
        elif import_type == 'extract':
            summary.update({
                "extracted": sum(1 for f in files if f.get('disposition') == 'extracted'),
            })
        
        return summary
    
    def save_metadata(self, metadata: dict, filename: str) -> Path:
        """Save metadata to JSON file."""
        # Ensure filename ends with .metadata.json
        if not filename.endswith('.metadata.json'):
            filename = f"{filename}.metadata.json"
        
        metadata_file = self.metadata_dir / filename
        
        try:
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            print(f"[INFO] Saved metadata: {metadata_file.name}")
            return metadata_file
        except Exception as e:
            print(f"[ERROR] Failed to save metadata: {e}")
            raise
    
    def create_zip_import_metadata(
        self,
        zip_files: list[Path],
        export_prefix: str,
        immich_results: Optional[dict] = None,
        log_file_path: Optional[str] = None,
        immich_go_command: Optional[str] = None
    ) -> Path:
        """Create single aggregated metadata for Google Photos zip import via immich-go."""
        # Copy log file
        relative_log_path = None
        if log_file_path:
            relative_log_path = copy_log_to_metadata(log_file_path, self.metadata_dir)
        
        # Build zip_files array with name and size
        zip_files_info = []
        total_size = 0
        for zip_path in zip_files:
            size = zip_path.stat().st_size if zip_path.exists() else 0
            total_size += size
            zip_files_info.append({
                'name': zip_path.name,
                'size': size
            })
        
        # Get all file contents from all zips
        all_files = []
        for zip_path in zip_files:
            contents = get_zip_contents(zip_path)
            for f in contents:
                f['zip_file'] = zip_path.name
                f['disposition'] = 'pending'
                if f.get('is_google_photos') and f.get('is_media'):
                    f['disposition'] = 'imported_to_immich'
                elif f.get('is_json'):
                    f['disposition'] = 'skipped_json'
                elif not f.get('is_google_photos'):
                    f['disposition'] = 'extracted'
                else:
                    f['disposition'] = 'skipped_other'
            all_files.extend(contents)
        
        # Apply immich-go results if available
        if immich_results:
            apply_immich_results_to_manifest(all_files, immich_results)
        
        # Create single aggregated metadata
        metadata = self.create_extraction_metadata(
            source_name=export_prefix,
            import_type='immich-go',
            source_type='google-photos',
            files=all_files,
            total_size=total_size,
            extra_fields={
                'zip_files': zip_files_info,
                'export_prefix': export_prefix,
                'immich_go_log': relative_log_path,
                'immich_go_command': immich_go_command,
                'immich_go_results': immich_results.get('summary') if immich_results else None,
            }
        )
        
        # Save with export prefix as filename
        saved_file = self.save_metadata(metadata, export_prefix)
        return saved_file
    
    def create_folder_import_metadata(
        self,
        folder_path: Path,
        source_type: str,  # 'sd-card', 'folder'
        immich_results: Optional[dict] = None,
        log_file_path: Optional[str] = None,
        extra_fields: Optional[dict] = None
    ) -> Path:
        """Create metadata for folder-based import (SD card, etc)."""
        # Copy log file
        relative_log_path = None
        if log_file_path:
            relative_log_path = copy_log_to_metadata(log_file_path, self.metadata_dir)
        
        # Get folder contents
        files = get_folder_contents(folder_path)
        
        # Set initial disposition
        for f in files:
            if f['is_media']:
                f['disposition'] = 'imported_to_immich'
            else:
                f['disposition'] = 'skipped_non_media'
        
        # Apply immich-go results if available
        if immich_results:
            apply_immich_results_to_manifest(files, immich_results)
        
        # Calculate total size
        total_size = sum(f.get('size', 0) for f in files)
        
        # Build extra fields
        all_extra = {
            'source_path': str(folder_path),
            'immich_go_log': relative_log_path,
            'immich_go_results': immich_results.get('summary') if immich_results else None,
        }
        if extra_fields:
            all_extra.update(extra_fields)
        
        metadata = self.create_extraction_metadata(
            source_name=folder_path.name,
            import_type='sd-import' if source_type == 'sd-card' else 'folder-import',
            source_type=source_type,
            files=files,
            total_size=total_size,
            extra_fields=all_extra
        )
        
        # Use folder name + timestamp for unique filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{folder_path.name}_{timestamp}"
        
        return self.save_metadata(metadata, filename)
    
    def create_extraction_only_metadata(
        self,
        zip_path: Path,
        extract_dir: Path,
        related_parts: Optional[list[Path]] = None
    ) -> Path:
        """Create metadata for non-Google-Photos zip extraction."""
        parts = related_parts if related_parts else [zip_path]
        
        # Build zip_files array with name and size
        zip_files_info = []
        total_size = 0
        for part in parts:
            size = part.stat().st_size if part.exists() else 0
            total_size += size
            zip_files_info.append({
                'name': part.name,
                'size': size
            })
        
        # Gather all file info from all parts
        all_files = []
        for part in parts:
            contents = get_zip_contents(part)
            for f in contents:
                f['zip_file'] = part.name
                f['disposition'] = 'extracted'
            all_files.extend(contents)
        
        # Determine base name for metadata file
        if related_parts and len(related_parts) > 1:
            match = re.match(r'(.+)-\d{3}\.zip$', zip_path.name)
            base_name = match.group(1) if match else zip_path.stem
        else:
            base_name = zip_path.stem
        
        # Calculate relative extract path
        try:
            relative_extract_path = str(extract_dir.name)
        except Exception:
            relative_extract_path = str(extract_dir)
        
        metadata = self.create_extraction_metadata(
            source_name=base_name,
            import_type='extract',
            source_type='google-takeout',
            files=all_files,
            total_size=total_size,
            extra_fields={
                'zip_files': zip_files_info,
                'extract_destination': str(extract_dir),
                'relative_extract_path': relative_extract_path,
            }
        )
        
        return self.save_metadata(metadata, base_name)


class ImmichGoRunner:
    """
    Unified runner for immich-go uploads with retry logic and error handling.
    Used by both immich_import.py (Google Photos zips) and sd_import.py (folders).
    """
    
    def __init__(
        self,
        server_url: Optional[str] = None,
        api_key_file: Optional[str] = None,
        log_dir: Optional[Path] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[int] = None,
        api_key: Optional[str] = None,
    ):
        # Use shared defaults
        server_url = server_url or DEFAULT_IMMICH_SERVER
        if(api_key):
            self.api_key = api_key
        elif(api_key_file):
            self.api_key = get_immich_api_key(api_key_file)
        else:
            self.api_key = DEFAULT_IMMICH_API_KEY or get_immich_api_key(DEFAULT_IMMICH_API_KEY_FILE)
        self.server_url = server_url.rstrip('/')
        if self.server_url.endswith('/api'):
            self.server_url = self.server_url[:-4]
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.max_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
        self.retry_delay = retry_delay if retry_delay is not None else DEFAULT_RETRY_DELAY
        
        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def _build_base_cmd(self, log_file: Path) -> list[str]:
        """Build base command with common flags."""
        return [
            "immich-go",
            "upload",
            # subcommand added by caller
        ]
    
    def _build_common_flags(self, log_file: Path) -> list[str]:
        """Build common flags for all upload types."""
        return [
            "-s", self.server_url,
            "-k", self.api_key,
            "--log-level=INFO",
            "--log-type=JSON",
            f"--log-file={log_file}",
            "--manage-raw-jpeg=StackCoverRaw",
            "--manage-burst=Stack",
            "--on-errors=continue",
            "--no-ui",
        ]
    
    def _run_with_retry(self, cmd: list[str], log_file: Path, description: str) -> tuple[int, dict]:
        """Run command with retry logic. Returns (exit_code, parsed_results)."""
        last_exit_code = -1
        last_results = {'summary': {}, 'files': {}}
        
        for attempt in range(1, self.max_retries + 1):
            if attempt > 1:
                print(f"[INFO] Retry attempt {attempt}/{self.max_retries} for {description}")
                time.sleep(self.retry_delay)
                
                # Clear log file for fresh results
                if log_file.exists():
                    log_file.unlink()
            
            result = subprocess.run(cmd, capture_output=False, text=True)
            last_exit_code = result.returncode
            
            # Parse the log file for results
            last_results = parse_immich_go_log(log_file)
            
            if result.returncode == 0:
                print(f"[INFO] {description} completed successfully")
                return last_exit_code, last_results
            
            # Check if we should retry based on error type
            errors = last_results.get('summary', {}).get('errors', 0)
            uploaded = last_results.get('summary', {}).get('uploaded', 0)
            
            # If we made progress (some uploads), consider it partially successful
            if uploaded > 0 and errors > 0:
                print(f"[WARNING] {description} partially completed: {uploaded} uploaded, {errors} errors")
                # Continue to retry to handle remaining files
            elif errors == 0 and result.returncode != 0:
                # Exit code non-zero but no errors logged - might be transient
                print(f"[WARNING] {description} failed with exit code {result.returncode} but no errors logged")
            else:
                print(f"[ERROR] {description} failed: exit code {result.returncode}, {errors} errors")
        
        print(f"[ERROR] {description} failed after {self.max_retries} attempts")
        return last_exit_code, last_results
    
    def _mask_api_key(self, cmd: list[str]) -> str:
        """Create display version of command with masked API key."""
        return ' '.join(cmd).replace(self.api_key, '***API_KEY***')
    
    def upload_google_photos(
        self,
        zip_files: list[Path],
        export_prefix: str,
        extra_flags: Optional[list[str]] = None
    ) -> tuple[int, dict, str, Path]:
        """
        Upload Google Photos takeout zips to Immich.
        
        Returns: (exit_code, parsed_results, command_display, log_file_path)
        """
        log_file = self.log_dir / f"{export_prefix}.immich-go.log"
        
        cmd = ["immich-go", "upload", "from-google-photos"]
        cmd.extend(self._build_common_flags(log_file))
        
        # Google Photos specific flags
        cmd.extend([
            "--sync-albums",
            "--include-untitled-albums",
            "--people-tag",
            "--takeout-tag",
            "--include-archived",
            "--include-unmatched",
            "--session-tag",
        ])
        
        # Add extra flags if provided
        if extra_flags:
            cmd.extend(extra_flags)
        
        # Use glob pattern instead of listing all files
        # e.g., /data/import/Takeout/takeout-20240827T200018Z-*.zip
        if zip_files:
            parent_dir = zip_files[0].parent
            glob_pattern = f"{parent_dir}/{export_prefix}-*.zip"
            cmd.append(glob_pattern)
        
        cmd_display = self._mask_api_key(cmd)
        total_size_gb = sum(z.stat().st_size for z in zip_files) / (1024**3)
        
        print(f"[INFO] Importing Google Photos: {export_prefix}")
        print(f"[INFO]   Parts: {len(zip_files)}, Size: {total_size_gb:.2f} GB")
        print(f"[INFO]   Log file: {log_file}")
        print(f"[INFO]   Command: {cmd_display}")
        
        exit_code, results = self._run_with_retry(cmd, log_file, f"Google Photos import {export_prefix}")
        
        return exit_code, results, cmd_display, log_file
    
    def upload_folder(
        self,
        folder_path: Path,
        tag: str,
        extra_flags: Optional[list[str]] = None
    ) -> tuple[int, dict, str, Path]:
        """
        Upload a folder to Immich.
        
        Returns: (exit_code, parsed_results, command_display, log_file_path)
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = self.log_dir / f"upload-{folder_path.name}-{timestamp}.log"
        
        cmd = ["immich-go", "upload", "from-folder"]
        cmd.extend(self._build_common_flags(log_file))
        
        # Folder-specific flags
        cmd.extend([
            "--session-tag",
            f"--tag={tag}",
        ])
        
        # Add extra flags if provided
        if extra_flags:
            cmd.extend(extra_flags)
        
        # Add folder path
        cmd.append(str(folder_path))
        
        cmd_display = self._mask_api_key(cmd)
        
        print(f"[INFO] Importing folder: {folder_path}")
        print(f"[INFO]   Tag: {tag}")
        print(f"[INFO]   Log file: {log_file}")
        print(f"[INFO]   Command: {cmd_display}")
        
        exit_code, results = self._run_with_retry(cmd, log_file, f"folder import {folder_path.name}")
        
        return exit_code, results, cmd_display, log_file
    
    def has_errors(self, results: dict) -> bool:
        """Check if import results contain errors."""
        return results.get('summary', {}).get('errors', 0) > 0
    
    def is_success(self, exit_code: int, results: dict) -> bool:
        """
        Check if import was successful.
        Success = exit code 0 AND no errors in results.
        """
        return exit_code == 0 and not self.has_errors(results)
    
    def get_summary_line(self, results: dict) -> str:
        """Get a one-line summary of results."""
        s = results.get('summary', {})
        return (f"uploaded={s.get('uploaded', 0)}, "
                f"duplicates={s.get('server_duplicate', 0) + s.get('local_duplicate', 0)}, "
                f"errors={s.get('errors', 0)}")


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
    file_manifest: list[dict],
    skip_google_photos: bool = True
) -> tuple[int, int]:
    """
    Extract files from zips that were NOT successfully imported to Immich.
    
    Args:
        zip_files: List of zip files to extract from
        extract_dir: Directory to extract to
        immich_results: Results from immich-go import
        file_manifest: File manifest to update with disposition
        skip_google_photos: If True, skip Google Photos content (already handled by immich-go)
    
    Returns:
        Tuple of (extracted_count, failed_count)
    """
    # Build lookup from manifest
    manifest_lookup = {(f.get('zip_file'), f['path']): f for f in file_manifest}
    files_map = immich_results.get('files', {})
    
    extracted_count = 0
    failed_count = 0
    
    for zip_path in zip_files:
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    
                    key = (zip_path.name, info.filename)
                    filename = Path(info.filename).name
                    
                    # Check if this file was imported to Immich
                    file_result = files_map.get(filename, {})
                    was_imported = file_result.get('status') in ('uploaded', 'upgraded', 'server_duplicate', 'local_duplicate', 'server_better')
                    
                    # Skip Google Photos media that was imported
                    if skip_google_photos and is_google_photos_path(info.filename):
                        if is_media_file(filename) and was_imported:
                            if key in manifest_lookup:
                                manifest_lookup[key]['disposition'] = 'imported_to_immich'
                            continue
                        elif info.filename.endswith('.json'):
                            if key in manifest_lookup:
                                manifest_lookup[key]['disposition'] = 'skipped_json'
                            continue
                    
                    # Skip json metadata files
                    if info.filename.endswith('.json'):
                        if key in manifest_lookup:
                            manifest_lookup[key]['disposition'] = 'skipped_json'
                        continue
                    
                    # Skip files that were successfully imported
                    if was_imported:
                        if key in manifest_lookup:
                            manifest_lookup[key]['disposition'] = 'imported_to_immich'
                        continue
                    
                    # Extract this file
                    try:
                        target_path = extract_dir / info.filename
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        with zf.open(info) as src, open(target_path, 'wb') as dst:
                            dst.write(src.read())
                        
                        if target_path.exists() and target_path.stat().st_size == info.file_size:
                            extracted_count += 1
                            if key in manifest_lookup:
                                manifest_lookup[key]['disposition'] = 'extracted'
                        else:
                            print(f"[WARNING] Size mismatch after extracting: {info.filename}")
                            failed_count += 1
                            if key in manifest_lookup:
                                manifest_lookup[key]['disposition'] = 'extract_failed'
                    except Exception as e:
                        print(f"[WARNING] Failed to extract {info.filename}: {e}")
                        failed_count += 1
                        if key in manifest_lookup:
                            manifest_lookup[key]['disposition'] = 'extract_failed'
                            
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
    file_manifest: list[dict],
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
        file_manifest: File manifest to update with disposition
        copy_failed: If True, copy non-imported files to extract_dir
    
    Returns:
        Tuple of (imported_count, not_imported_count, copy_failed_count)
    """
    files_map = immich_results.get('files', {})
    
    imported_count = 0
    not_imported_count = 0
    copy_failed_count = 0
    
    for f in file_manifest:
        filename = f['filename']
        file_path = f['path']
        
        # Check if this file was imported to Immich
        file_result = files_map.get(filename, {})
        was_imported = file_result.get('status') in ('uploaded', 'upgraded', 'server_duplicate', 'local_duplicate', 'server_better')
        
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


class ImportProcessor:
    """
    Unified import processor for both Google Photos zips and folders.
    Handles immich-go import + extraction of non-imported files + metadata creation.
    """
    
    _instance: 'ImportProcessor' = None
    
    @classmethod
    def get_instance(cls) -> 'ImportProcessor':
        """Get or create a singleton ImportProcessor instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(
        self,
        runner: Optional[ImmichGoRunner] = None,
        metadata_builder: Optional[MetadataBuilder] = None,
        extract_base_dir: Optional[Path] = None,
        copy_failed_files: Optional[bool] = None
    ):
        self.runner = runner or ImmichGoRunner()
        self.metadata_builder = metadata_builder or MetadataBuilder()
        self.extract_base_dir = extract_base_dir or DEFAULT_EXTRACT_DIR
        self.copy_failed_files = copy_failed_files if copy_failed_files is not None else DEFAULT_COPY_FAILED_FILES
        self.log_config()
    
    def log_config(self):
        """Log current configuration."""
        print(f"[INFO] Immich server: {self.runner.server_url}")
        print(f"[INFO] Metadata dir: {self.metadata_builder.metadata_dir}")
        print(f"[INFO] Extract dir: {self.extract_base_dir}")
        print(f"[INFO] Max retries: {self.runner.max_retries}, Retry delay: {self.runner.retry_delay}s")
        print(f"[INFO] Copy failed files: {self.copy_failed_files}")
    
    def process_google_photos_zips(
        self,
        zip_files: list[Path],
        export_prefix: str,
        delete_after_import: bool = False
    ) -> tuple[bool, dict]:
        """
        Process Google Photos takeout zip files:
        1. Import to Immich via immich-go
        2. Extract non-Google-Photos content
        3. Save metadata
        4. Optionally delete zips (only if no errors)
        
        Returns: (success, immich_results)
        """
        # Run immich-go import
        exit_code, immich_results, cmd_display, log_file = self.runner.upload_google_photos(
            zip_files=zip_files,
            export_prefix=export_prefix
        )
        
        has_errors = self.runner.has_errors(immich_results)
        is_success = self.runner.is_success(exit_code, immich_results)
        
        print(f"[INFO] Import results: {self.runner.get_summary_line(immich_results)}")
        
        # Build file manifest from all zips
        file_manifest = []
        for zip_path in zip_files:
            contents = get_zip_contents(zip_path)
            for f in contents:
                f['zip_file'] = zip_path.name
                f['disposition'] = 'pending'
            file_manifest.extend(contents)
        
        # Apply immich-go results to manifest
        apply_immich_results_to_manifest(file_manifest, immich_results)
        
        # Extract non-imported content
        extract_dir = self.extract_base_dir / f"{export_prefix}-extracted"
        extracted, failed = extract_non_imported_from_zip(
            zip_files=zip_files,
            extract_dir=extract_dir,
            immich_results=immich_results,
            file_manifest=file_manifest,
            skip_google_photos=True
        )
        
        # Save metadata
        saved_file = self.metadata_builder.create_zip_import_metadata(
            zip_files=zip_files,
            export_prefix=export_prefix,
            immich_results=immich_results,
            log_file_path=str(log_file),
            immich_go_command=cmd_display
        )
        print(f"[DEBUG] Saved metadata: {saved_file.name}")
        
        # Delete zips only if successful and no errors
        if delete_after_import and is_success and not has_errors:
            deleted_count = 0
            for zip_file in zip_files:
                try:
                    if zip_file.exists():
                        zip_file.unlink()
                        deleted_count += 1
                        print(f"[DEBUG] Deleted: {zip_file.name}")
                except Exception as e:
                    print(f"[WARNING] Failed to delete {zip_file.name}: {e}")
            print(f"[INFO] Deleted {deleted_count} zip file(s)")
        elif delete_after_import and has_errors:
            print(f"[WARNING] Not deleting zips due to {immich_results.get('summary', {}).get('errors', 0)} errors")
        
        return is_success, immich_results
    
    def process_folder(
        self,
        folder_path: Path,
        source_type: str = "folder",
        tag_prefix: str = "IMPORT",
        device_label: Optional[str] = None,
        copy_failed_files: Optional[bool] = None
    ) -> tuple[bool, dict]:
        """
        Process a folder import:
        1. Import to Immich via immich-go
        2. Track which files were imported vs not imported
        3. Optionally copy non-imported files to extract dir for review
        4. Save metadata
        
        Args:
            folder_path: Path to folder to import
            source_type: Type of source (folder, sd-card, camera, phone)
            tag_prefix: Tag prefix for Immich
            device_label: Optional device label for tagging
            copy_failed_files: If True, copy non-imported files to extract dir (defaults to self.copy_failed_files)
        
        Returns: (success, immich_results)
        """
        print(f"[INFO] Starting import from {folder_path}")
        print(f"[INFO] Source type: {source_type}")
        
        # Use instance default if not specified
        if copy_failed_files is None:
            copy_failed_files = self.copy_failed_files
        
        # Count files in folder
        media_count = 0
        total_size = 0
        for f in folder_path.rglob("*"):
            if f.is_file():
                media_count += 1
                total_size += f.stat().st_size
        
        if media_count == 0:
            print(f"[INFO] No files found in {folder_path}")
            return True, {'summary': {}, 'files': {}}
        
        print(f"[INFO] Found {media_count} files ({format_size(total_size)}) in {folder_path}")
        
        # Create import tag
        import_date = datetime.now().strftime('%Y-%m-%d')
        tag = f"{tag_prefix}/{import_date}"
        if device_label:
            tag = f"{tag_prefix}/{device_label}/{import_date}"
        
        # Run immich-go import
        exit_code, immich_results, cmd_display, log_file = self.runner.upload_folder(
            folder_path=folder_path,
            tag=tag
        )
        
        has_errors = self.runner.has_errors(immich_results)
        is_success = self.runner.is_success(exit_code, immich_results)
        
        print(f"[INFO] Results: {self.runner.get_summary_line(immich_results)}")
        
        if not is_success:
            print(f"[ERROR] Import failed (exit_code={exit_code}, has_errors={has_errors})")
        else:
            print(f"[INFO] Import completed successfully")
        
        # Build file manifest
        file_manifest = get_folder_contents(folder_path)
        for f in file_manifest:
            f['disposition'] = 'pending'
        
        # Apply immich-go results and track non-imported files
        extract_dir = None
        if copy_failed_files:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            extract_dir = self.extract_base_dir / f"{folder_path.name}-{timestamp}-failed"
        
        imported_count, not_imported_count, copy_failed_count = copy_remaining_from_folder(
            source_folder=folder_path,
            extract_dir=extract_dir,
            immich_results=immich_results,
            file_manifest=file_manifest,
            copy_failed=copy_failed_files
        )
        
        # Save metadata
        try:
            metadata_file = self.metadata_builder.create_folder_import_metadata(
                folder_path=folder_path,
                source_type=source_type,
                immich_results=immich_results,
                log_file_path=str(log_file),
                extra_fields={
                    'tag': tag,
                    'device_label': device_label,
                    'import_exit_code': exit_code,
                    'immich_go_command': cmd_display,
                    'has_errors': has_errors,
                    'imported_count': imported_count,
                    'not_imported_count': not_imported_count,
                    'copy_failed_count': copy_failed_count if copy_failed_files else None,
                }
            )
            print(f"[INFO] Created metadata: {metadata_file.name}")
        except Exception as e:
            print(f"[WARNING] Failed to create metadata: {e}")
        
        return is_success, immich_results
