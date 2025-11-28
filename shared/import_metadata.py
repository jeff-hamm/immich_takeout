#!/usr/bin/env python3
"""
ImportMetadata class for tracking import status and results.
The metadata object itself, not a builder pattern.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ImportMetadata(dict):
    """
    Metadata dictionary for an import operation.
    Inherits from dict so it can be used directly as a dictionary.
    Knows its own file path and can save itself.
    """
    
    def __init__(
        self,
        import_type: str,
        source_type: str,
        zip_files: Optional[list[Path]] = None,
        folder_path: Optional[Path] = None,
        extract_dir: Optional[Path] = None,
        metadata_dir: Optional[Path] = None,
        extra_fields: Optional[dict] = None,
    ):
        """
        Create a new ImportMetadata with 'running' status (or 'completed' for extract-only).
        
        Must provide either:
        - zip_files (for Google Photos imports)
        - folder_path (for folder imports)
        - zip_files + extract_dir (for extraction-only, sets import_type='extract')
        
        Args:
            import_type: Type of import ('immich-go', 'folder-import', 'sd-import', 'extract')
            source_type: Type of source ('google-photos', 'google-takeout', 'folder', 'sd-card', etc.)
            zip_files: List of zip file paths (for zip imports or extraction)
            folder_path: Path to folder (for folder imports)
            extract_dir: Directory where files are extracted (for extract-only, requires zip_files)
            metadata_dir: Directory to save metadata files (defaults to /data/metadata)
            extra_fields: Additional fields to include (tag, device_label, etc.)
        """
        super().__init__()
        
        # Handle both package and direct import
        try:
            from . import DEFAULT_METADATA_DIR
        except ImportError:
            from takeout_utils import DEFAULT_METADATA_DIR
        self._metadata_dir = metadata_dir or DEFAULT_METADATA_DIR
        self._metadata_dir.mkdir(parents=True, exist_ok=True)
        
        # Set the file path with timestamp suffix for uniqueness
        
        self.update({
            "status": "running",
            "import_type": import_type,
            "source_type": source_type,
            "start_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        extra_fields = extra_fields or {}
        if zip_files:
            self.zip_files = zip_files
            self.source_name = self._init_zip_files(zip_files)
            if extract_dir:
                self.extract_path = extract_dir     
                self._init_from_extraction(import_type, source_type, extract_dir)
            else:
                self['immich_go_log'] = f"logs/{self.source_name}.immich-go.{timestamp}.log"
        elif folder_path:
            self.import_path = folder_path
            self.source_name = self._init_from_folder(import_type, source_type, folder_path)
        else:
            raise ValueError("Must provide either zip_files, folder_path, or zip_files + extract_dir")
        
        # Add extra fields (tag, device_label, etc.)
        if extra_fields:
            self.update(extra_fields)
        
        self._file_path = self._metadata_dir / f"{self.source_name}.{timestamp}.metadata.json"

    
    def _init_zip_files(self, zip_files: list[Path]) -> None:
        """
        Parse zip files and initialize common metadata fields.
        Sets source_name, zip_files, total_size, import_dir.
        """
        try:
            from .takeout_utils import get_zip_contents
        except ImportError:
            from takeout_utils import get_zip_contents
        
        # Derive source_name from first zip file (export prefix)
        first_zip = zip_files[0].name
        # Extract prefix like "takeout-20240427T195310Z" from "takeout-20240427T195310Z-001.zip"
        match = re.match(r'(.+)-\d{3}\.zip$', first_zip)
        if match:
            source_name = match.group(1)
        else:
            source_name = zip_files[0].stem
        # Build zip_files info and calculate total size
        zip_files_info = []
        total_size = 0
        file_count = 0
        self.file_manifest = {}
        for zip_path in zip_files:
            size = zip_path.stat().st_size if zip_path.exists() else 0
            total_size += size
            zip_files_info.append({
                'name': zip_path.name,
                'size': size
            })
            contents = get_zip_contents(zip_path)
            for path, f in contents.items():
                f['zip_file'] = zip_path.name
                f['disposition'] = 'pending'
                self.file_manifest[path] = f
                file_count+=1

        
        # Get import directory from first zip file
        self.import_dir = zip_files[0].parent
        self.files = []
        self.update({
            "source_name": source_name,
            "zip_files": zip_files_info,
            "file_count": file_count,
            "files": self.files,
            "total_size": total_size,
            "import_dir": str(self.import_dir),
            "export_prefix": source_name,
        })
        return source_name
    
    
    def _init_from_folder(self, import_type: str, source_type: str, folder_path: Path) -> None:
        """Initialize metadata from a folder."""
        try:
            from .takeout_utils import get_folder_contents
        except ImportError:
            from takeout_utils import get_folder_contents
        # Generate unique source_name from folder name + timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        source_name = f"{folder_path.name}_{timestamp}"
        
        # Build file manifest (dict keyed by path)
        self.file_manifest = get_folder_contents(folder_path)
        for path, f in self.file_manifest.items():
            f['disposition'] = 'pending'
        
        # Calculate file count and total size from manifest
        file_count = len(self.file_manifest)
        total_size = sum(f['size'] for f in self.file_manifest.values())
        
        self.update({
            "source_path": str(folder_path),
            "total_size": total_size,
            "file_count": file_count,
            "immich_go_log": f"logs/upload-{folder_path.name}.immich-go.{timestamp}.log",
        })
        return source_name
    
    def _init_from_extraction(self, import_type: str, source_type: str, extract_dir: Path) -> None:
        """Initialize metadata for extraction-only operations (no Immich import)."""
        try:
            from .takeout_utils import get_zip_contents
        except ImportError:
            from takeout_utils import get_zip_contents
        # Gather all file info from all zip parts (dict keyed by path)
        self.file_manifest = {}
        for zip_path in self.zip_files:
            contents = get_zip_contents(zip_path)
            for path, f in contents.items():
                f['zip_file'] = zip_path.name
                f['disposition'] = 'extracted'
                self.file_manifest[path] = f
        
        # Calculate relative extract path (just the directory name)
        try:
            relative_extract_path = str(extract_dir.name)
        except Exception:
            relative_extract_path = str(extract_dir)
        
        # Calculate summary from file_manifest
        manifest_values = list(self.file_manifest.values())
        summary = {
            "total": len(manifest_values),
            "media_files": sum(1 for f in manifest_values if f.get('is_media', False)),
            "json_files": sum(1 for f in manifest_values if f.get('is_json', False)),
            "extracted": sum(1 for f in manifest_values if f.get('disposition') == 'extracted'),
        }
        
        
        self.update({
            "file_count": len(self.file_manifest),
            "files": list(self.file_manifest.values()),
            "extract_destination": str(extract_dir),
            "relative_extract_path": relative_extract_path,
            "summary": summary,
        })
    
    @property
    def file_path(self) -> Path:
        """Get the path to the metadata file."""
        return self._file_path
    
    @property
    def metadata_dir(self) -> Path:
        """Get the metadata directory."""
        return self._metadata_dir
    
    @classmethod
    def load(cls, file_path: Path) -> 'ImportMetadata':
        """Load an existing metadata file."""
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Create instance without calling __init__
        instance = cls.__new__(cls)
        dict.__init__(instance, data)
        instance._file_path = file_path
        instance._metadata_dir = file_path.parent
        return instance
    
    def save(self) -> Path:
        """Save metadata to JSON file."""
        try:
            self['update_time'] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            with open(self._file_path, 'w') as f:
                json.dump(dict(self), f, indent=2)
#            print(f"[INFO] Saved metadata: {self._file_path.name}")
            return self._file_path
        except Exception as e:
            print(f"[ERROR] Failed to save metadata: {e}")
            raise
    
    def update_status(
        self,
        status: str,
        files: Optional[dict[str, dict]] = None,
        immich_results: Optional[dict] = None,
        error_details: Optional[str] = None,
        extra_fields: Optional[dict] = None
    ) -> Path:
        """
        Update metadata with new status and results, then save.
        
        Args:
            status: New status ('completed', 'errored', etc.)
            files: File manifest dict keyed by path
            immich_results: Results from immich-go
            error_details: Error message if status is 'errored'
            extra_fields: Additional fields to add/update
        
        Returns: Path to saved metadata file
        """
        # Update status and timing
        self['status'] = status
        self['end_time'] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Calculate duration if we have start_time
        if 'start_time' in self:
            try:
                start = datetime.fromisoformat(self['start_time'].replace('Z', '+00:00'))
                end = datetime.fromisoformat(self['end_time'].replace('Z', '+00:00'))
                self['duration_seconds'] = (end - start).total_seconds()
            except Exception:
                pass
        
        # Add files dict if provided - save as list of values for JSON
        if files is not None:
            self['files'] = list(files.values())
            self['file_count'] = len(files)
        
        # Add immich results if provided
        if immich_results:
            self['immich_go_results'] = immich_results.get('summary')
        
        # Add error details if provided
        if error_details:
            self['error_details'] = error_details
        
        # Add extra fields
        if extra_fields:
            self.update(extra_fields)
        
        # Recalculate summary if we have files
        if files:
            self['summary'] = self._calculate_summary(files)
        
        # Save and return path
        self.save()
        print(f"[INFO] Updated metadata: {self._file_path.name} (status={status})")
        return self._file_path
    
    def _calculate_summary(self, files: dict[str, dict]) -> dict:
        """Calculate summary statistics from file manifest dict."""
        import_type = self.get('import_type', 'immich-go')
        file_values = list(files.values())
        
        summary = {
            "total": len(file_values),
            "media_files": sum(1 for f in file_values if f.get('is_media', False)),
            "json_files": sum(1 for f in file_values if f.get('is_json', False)),
        }
        
        if import_type in ('immich-go', 'sd-import', 'folder-import'):
            summary.update({
                "uploaded_success": sum(1 for f in file_values if f.get('immich_status') == 'uploaded'),
                "server_duplicate": sum(1 for f in file_values if f.get('immich_status') == 'server_duplicate'),
                "local_duplicate": sum(1 for f in file_values if f.get('immich_status') == 'local_duplicate'),
                "server_better": sum(1 for f in file_values if f.get('immich_status') == 'server_better'),
                "upgraded": sum(1 for f in file_values if f.get('immich_status') == 'upgraded'),
                "errors": sum(1 for f in file_values if f.get('immich_status') == 'error'),
            })
        elif import_type == 'extract':
            summary.update({
                "extracted": sum(1 for f in file_values if f.get('disposition') == 'extracted'),
            })
        
        return summary
