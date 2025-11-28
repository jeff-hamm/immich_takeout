#!/usr/bin/env python3
"""
ImmichGoRunner - Unified runner for immich-go uploads with retry logic and error handling.
Used by both immich_import.py (Google Photos zips) and sd_import.py (folders).
"""
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# Import from takeout_utils - handle both package and direct import
try:
    from .takeout_utils import (
        parse_log_entry,
        parse_immich_go_log,
        get_immich_api_key,
        file_result_to_manifest_entry,
        DEFAULT_IMMICH_SERVER,
        DEFAULT_IMMICH_API_KEY,
        DEFAULT_IMMICH_API_KEY_FILE,
        DEFAULT_LOG_DIR,
        DEFAULT_MAX_RETRIES,
        DEFAULT_RETRY_DELAY,
    )
    from .import_metadata import ImportMetadata
except ImportError:
    from takeout_utils import (
        parse_log_entry,
        parse_immich_go_log,
        get_immich_api_key,
        file_result_to_manifest_entry,
        DEFAULT_IMMICH_SERVER,
        DEFAULT_IMMICH_API_KEY,
        DEFAULT_IMMICH_API_KEY_FILE,
        DEFAULT_LOG_DIR,
        DEFAULT_MAX_RETRIES,
        DEFAULT_RETRY_DELAY,
    )
    from import_metadata import ImportMetadata


def create_metadata_callback(metadata: 'ImportMetadata') -> Callable[[dict], None]:
    """
    Create a callback that updates metadata.file_manifest and appends to metadata.files.
    
    Args:
        metadata: ImportMetadata instance with file_manifest dict keyed by path
    
    Returns:
        Callback function for use with ImmichGoRunner
    """
    def callback(result: dict) -> None:
        event_type = result.get('event_type', 'unknown')
        path = result.get('path')
        filename = result.get('filename')
        
        if event_type == 'file_result' and path:
            # Direct dict lookup by path
            manifest_entry = metadata.file_manifest.get(path)
            
            if manifest_entry:
                # Update the manifest entry with immich results
                manifest_entry.update(file_result_to_manifest_entry(filename, result))
                
                # Append to files list
                metadata.files.append(manifest_entry)
                metadata.save()
        
        elif event_type == 'album' and path:
            # Update album info for existing entry
            manifest_entry = metadata.file_manifest.get(path)
            if manifest_entry:
                album = result.get('album', '')
                if 'albums' not in manifest_entry:
                    manifest_entry['albums'] = []
                if album and album not in manifest_entry['albums']:
                    manifest_entry['albums'].append(album)
                    metadata.save()
        
        elif event_type == 'tag' and path:
            # Update tag info for existing entry
            manifest_entry = metadata.file_manifest.get(path)
            if manifest_entry:
                tag = result.get('tag', '')
                if 'tags' not in manifest_entry:
                    manifest_entry['tags'] = []
                if tag and tag not in manifest_entry['tags']:
                    manifest_entry['tags'].append(tag)
                    metadata.save()
        # Also call default callback for logging
        default_result_callback(result)
    
    return callback


def default_result_callback(result: dict) -> None:
    """Default callback that logs each result."""
    event_type = result.get('event_type', 'unknown')
    
    if event_type == 'file_result':
        status = result.get('status', 'unknown')
        filename = result.get('path', 'unknown')
        reason = result.get('reason', '')
        if status == 'uploaded':
            print(f"[UPLOAD] ✓ {filename}")
        elif status == 'server_duplicate':
            print(f"[SKIP] ≡ {filename} (duplicate)")
        elif status == 'local_duplicate':
            print(f"[SKIP] ≡ {filename} (local dup)")
        elif status == 'server_better':
            print(f"[SKIP] ↓ {filename} (server better)")
        elif status == 'upgraded':
            print(f"[UPGRADE] ↑ {filename}")
        elif status == 'error':
            print(f"[ERROR] ✗ {filename}: {reason}")
    # elif event_type == 'album':
    #     print(f"[ALBUM] + {result.get('filename', '')} → {result.get('album', '')}")
    # elif event_type == 'tag':
    #     print(f"[TAG] # {result.get('filename', '')} → {result.get('tag', '')}")
    # elif event_type == 'album_created':
    #     print(f"[ALBUM] Created: {result.get('album', '')}")
    elif event_type == 'discovery':
        # Don't log every discovery - too noisy
        pass
    elif event_type == 'error':
        print(f"[ERROR] {result.get('error', result.get('message', ''))}")


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
    
    def _tail_log_file(
        self,
        log_file: Path,
        stop_event: threading.Event,
        results_accumulator: dict,
        result_callback: Optional[Callable[[dict], None]] = None
    ) -> None:
        """
        Tail a log file in real-time, parsing entries and calling the callback.
        Also accumulates results for final summary.
        """
        # Wait for log file to be created
        wait_count = 0
        while not log_file.exists() and not stop_event.is_set() and wait_count < 30:
            time.sleep(0.1)
            wait_count += 1
        
        if not log_file.exists():
            return
        
        # Track albums and tags
        albums_set = set()
        tags_set = set()
        
        with open(log_file, 'r') as f:
            while not stop_event.is_set():
                line = f.readline()
                if not line:
                    # No new data, wait a bit
                    time.sleep(0.05)
                    continue
                
                line = line.strip()
                if not line:
                    continue
                
                try:
                    entry = json.loads(line)
                    
                    # Capture version info
                    if 'version' in entry:
                        results_accumulator['summary']['immich_go_version'] = entry['version']
                    
                    # Track timestamps
                    if 'time' in entry:
                        timestamp = entry['time']
                        if results_accumulator['summary']['start_time'] is None:
                            results_accumulator['summary']['start_time'] = timestamp
                        results_accumulator['summary']['end_time'] = timestamp
                    
                    # Parse and dispatch to callback
                    result = parse_log_entry(entry)
                    if result:
                        # Accumulate results
                        event_type = result.get('event_type')
                        
                        if event_type == 'file_result':
                            filename = result.get('filename')
                            status = result.get('status')
                            
                            if filename not in results_accumulator['files']:
                                results_accumulator['files'][filename] = {
                                    'status': None, 'reason': None, 'albums': [], 'tags': []
                                }
                            
                            results_accumulator['files'][filename]['status'] = status
                            results_accumulator['files'][filename]['reason'] = result.get('reason')
                            
                            # Update summary counts
                            if status == 'uploaded':
                                results_accumulator['summary']['uploaded'] += 1
                            elif status == 'server_duplicate':
                                results_accumulator['summary']['server_duplicate'] += 1
                            elif status == 'local_duplicate':
                                results_accumulator['summary']['local_duplicate'] += 1
                            elif status == 'server_better':
                                results_accumulator['summary']['server_better'] += 1
                            elif status == 'upgraded':
                                results_accumulator['summary']['upgraded'] += 1
                            elif status == 'error':
                                results_accumulator['summary']['errors'] += 1
                        
                        elif event_type == 'album':
                            filename = result.get('filename')
                            album = result.get('album', '')
                            if filename in results_accumulator['files']:
                                if album not in results_accumulator['files'][filename]['albums']:
                                    results_accumulator['files'][filename]['albums'].append(album)
                            results_accumulator['summary']['albums_updated'] += 1
                            albums_set.add(album)
                        
                        elif event_type == 'tag':
                            filename = result.get('filename')
                            tag = result.get('tag', '')
                            if filename in results_accumulator['files']:
                                if tag not in results_accumulator['files'][filename]['tags']:
                                    results_accumulator['files'][filename]['tags'].append(tag)
                            results_accumulator['summary']['tagged'] += 1
                            tags_set.add(tag)
                        
                        elif event_type == 'album_created':
                            results_accumulator['summary']['albums_created'] += 1
                            albums_set.add(result.get('album', ''))
                        
                        elif event_type == 'discovery':
                            if result.get('media_type') == 'image':
                                results_accumulator['summary']['discovered_images'] += 1
                            else:
                                results_accumulator['summary']['discovered_videos'] += 1
                        
                        elif event_type == 'stack':
                            results_accumulator['summary']['stacked'] += 1
                        
                        # Call the callback if provided
                        if result_callback:
                            try:
                                result_callback(result)
                            except Exception as e:
                                print(f"[WARNING] Callback error: {e}")
                
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"[WARNING] Error processing log line: {e}")
        
        # Store final albums and tags lists
        results_accumulator['summary']['albums'] = sorted(albums_set)
        results_accumulator['summary']['tags'] = sorted(tags_set)
    
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
    
    def _run_with_retry(
        self,
        cmd: list[str],
        log_file: Path,
        description: str,
        result_callback: Optional[Callable[[dict], None]] = None
    ) -> tuple[int, dict]:
        """Run command with retry logic and real-time log parsing. Returns (exit_code, parsed_results)."""
        last_exit_code = -1
        last_results = self._create_empty_results()
        
        for attempt in range(1, self.max_retries + 1):
            if attempt > 1:
                print(f"[INFO] Retry attempt {attempt}/{self.max_retries} for {description}")
                time.sleep(self.retry_delay)
                
                # Clear log file for fresh results
                if log_file.exists():
                    log_file.unlink()
            
            # Create fresh results accumulator for this attempt
            results_accumulator = self._create_empty_results()
            
            # Start log tailing thread
            stop_event = threading.Event()
            tail_thread = threading.Thread(
                target=self._tail_log_file,
                args=(log_file, stop_event, results_accumulator, result_callback),
                daemon=True
            )
            tail_thread.start()
            
            try:
                # Run the command
                result = subprocess.run(cmd, capture_output=False, text=True)
                last_exit_code = result.returncode
            finally:
                # Stop the tail thread and wait for it to finish processing
                time.sleep(0.2)  # Give time to process final log entries
                stop_event.set()
                tail_thread.join(timeout=2.0)
            
            # Use accumulated results from real-time parsing
            last_results = results_accumulator
            
            # Calculate duration if we have timestamps
            if last_results['summary']['start_time'] and last_results['summary']['end_time']:
                try:
                    start = datetime.fromisoformat(
                        last_results['summary']['start_time'].replace('Z', '+00:00')
                    )
                    end = datetime.fromisoformat(
                        last_results['summary']['end_time'].replace('Z', '+00:00')
                    )
                    last_results['summary']['duration_seconds'] = (end - start).total_seconds()
                except Exception:
                    pass
            
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
    
    def _create_empty_results(self) -> dict:
        """Create an empty results dictionary."""
        return {
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
                'albums': [],
                'tags': [],
            },
            'files': {}
        }
    
    def _mask_api_key(self, cmd: list[str]) -> str:
        """Create display version of command with masked API key."""
        return ' '.join(cmd).replace(self.api_key, '***API_KEY***')
    
    def get_google_photos_command(
        self,
        zip_files: list[Path],
        export_prefix: str,
        log_file: Path,
        extra_flags: Optional[list[str]] = None
    ) -> list[str]:
        """
        Build command for Google Photos upload.
        
        Returns: command_list
        """
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
        if zip_files:
            parent_dir = zip_files[0].parent
            glob_pattern = f"{parent_dir}/{export_prefix}-*.zip"
            cmd.append(glob_pattern)
        
        return cmd
    
    def get_folder_command(
        self,
        folder_path: Path,
        tag: str,
        log_file: Path,
        extra_flags: Optional[list[str]] = None
    ) -> list[str]:
        """
        Build command for folder upload.
        
        Returns: (command_list, command_display_string)
        """
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
        
        return cmd
    
    def upload_google_photos(
        self,
        metadata: ImportMetadata,
        extra_flags: Optional[list[str]] = None
    ) -> tuple[int, dict]:
        """
        Upload Google Photos takeout zips to Immich.
        
        Args:
            metadata: Metadata dict from create_running_metadata containing:
                - source_name (export_prefix)
                - zip_files (list of {name, size})
                - import_dir (directory containing zip files)
                - immich_go_log (relative path to log file)
            extra_flags: Additional flags for immich-go
        
        Returns: (exit_code, parsed_results)
        """
        export_prefix = metadata.source_name
        import_dir = metadata.import_dir
        # Get zip file paths from metadata instance
        zip_files = metadata.zip_files
        
        # Get log file path from metadata
        log_file = self.log_dir / Path(metadata.get('immich_go_log', '')).name
        if not log_file.name:
            log_file = self.log_dir / f"{export_prefix}.immich-go.log"
        
        cmd = self.get_google_photos_command(zip_files, export_prefix, log_file, extra_flags)
        cmd_display = self._mask_api_key(cmd)
        metadata['command'] = cmd_display
        metadata['log_file'] = str(log_file)
        metadata.save()
        total_size_gb = metadata.get('total_size', 0) / (1024**3)
        
        print(f"[INFO] Importing Google Photos: {export_prefix}")
        print(f"[INFO]   Parts: {len(zip_files)}, Size: {total_size_gb:.2f} GB")
        print(f"[INFO]   Log file: {log_file}")
        print(f"[INFO]   Command: {cmd_display}")
        
        # Create files list and callback for real-time manifest updates
        metadata_callback = create_metadata_callback(metadata)
        exit_code, results = self._run_with_retry(
            cmd, log_file, f"Google Photos import {export_prefix}", metadata_callback
        )
        
        
        return exit_code, results
    
    def upload_folder(
        self,
        metadata: dict,
        extra_flags: Optional[list[str]] = None
    ) -> tuple[int, dict]:
        """
        Upload a folder to Immich.
        
        Args:
            metadata: Metadata dict from create_running_metadata containing:
                - source_path (folder path)
                - tag (import tag)
                - immich_go_log (relative path to log file)
            extra_flags: Additional flags for immich-go
        
        Returns: (exit_code, parsed_results)
        """
        folder_path = metadata.import_path
        tag = metadata.get('tag', '')
        
        # Get log file path from metadata
        log_file = self.log_dir / Path(metadata.get('immich_go_log', '')).name
        if not log_file.name:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            log_file = self.log_dir / f"upload-{folder_path.name}-{timestamp}.log"
        
        cmd = self.get_folder_command(folder_path, tag, log_file, extra_flags)
        metadata['command'] = self._mask_api_key(cmd)
        metadata['log_file'] = str(log_file)
        metadata.save()

        print(f"[INFO] Importing folder: {folder_path}")
        print(f"[INFO]   Tag: {tag}")
        print(f"[INFO]   Log file: {log_file}")
        print(f"[INFO]   Command: {self._mask_api_key(cmd)}")
        
        # Create files list and callback for real-time manifest updates
        metadata_callback = create_metadata_callback(metadata)
        
        exit_code, results = self._run_with_retry(
            cmd, log_file, f"folder import {folder_path.name}", metadata_callback
        )
                
        return exit_code, results
    
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
