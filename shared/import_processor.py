#!/usr/bin/env python3
"""
ImportProcessor - Unified import processor for Google Photos zips and folders.
Handles immich-go import + extraction of non-imported files + metadata creation.
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

# Import from shared modules - handle both package and direct import
try:
    from .immich_go_runner import ImmichGoRunner
    from .import_metadata import ImportMetadata
    from .takeout_utils import (
        get_zip_contents,
        get_folder_contents,
        apply_immich_results_to_manifest,
        extract_non_imported_from_zip,
        copy_remaining_from_folder,
        format_size,
        DEFAULT_METADATA_DIR,
        DEFAULT_EXTRACT_DIR,
        DEFAULT_COPY_FAILED_FILES,
    )
except ImportError:
    from immich_go_runner import ImmichGoRunner
    from import_metadata import ImportMetadata
    from takeout_utils import (
        get_zip_contents,
        get_folder_contents,
        apply_immich_results_to_manifest,
        extract_non_imported_from_zip,
        copy_remaining_from_folder,
        format_size,
        DEFAULT_METADATA_DIR,
        DEFAULT_EXTRACT_DIR,
        DEFAULT_COPY_FAILED_FILES,
    )


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
        metadata_dir: Optional[Path] = None,
        extract_base_dir: Optional[Path] = None,
        copy_failed_files: Optional[bool] = None
    ):
        self.runner = runner or ImmichGoRunner()
        self.metadata_dir = metadata_dir or DEFAULT_METADATA_DIR
        self.extract_base_dir = extract_base_dir or DEFAULT_EXTRACT_DIR
        self.copy_failed_files = copy_failed_files if copy_failed_files is not None else DEFAULT_COPY_FAILED_FILES
        self.log_config()
    
    def log_config(self):
        """Log current configuration."""
        print(f"[INFO] Immich server: {self.runner.server_url}")
        print(f"[INFO] Metadata dir: {self.metadata_dir}")
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
        1. Create 'running' metadata file
        2. Import to Immich via immich-go
        3. Extract non-Google-Photos content
        4. Update metadata with results
        5. Optionally delete zips (only if no errors)
        
        Returns: (success, immich_results)
        """
        # Create 'running' metadata before starting import
        # This generates source_name, log path, and calculates sizes from zip_files
        metadata = None
        try:
            metadata = ImportMetadata(
                import_type='immich-go',
                source_type='google-photos',
                metadata_dir=self.metadata_dir,
                zip_files=zip_files,
            )
            metadata.save()
        except Exception as e:
            print(f"[WARNING] Failed to create running metadata: {e}")
            # Fallback metadata for error handling
            zip_files_info = [{'name': z.name, 'size': z.stat().st_size if z.exists() else 0} for z in zip_files]
            import_dir = str(zip_files[0].parent) if zip_files else '.'
            metadata = {
                'source_name': export_prefix,
                'zip_files': zip_files_info,
                'import_dir': import_dir,
                'immich_go_log': f'logs/{export_prefix}.immich-go.log'
            }
        
        # Run immich-go import with metadata object
        try:
            exit_code, immich_results = self.runner.upload_google_photos(
                metadata=metadata
            )
        except Exception as e:
            # Update metadata with error status
            error_msg = str(e)
            print(f"[ERROR] immich-go failed with exception: {error_msg}")
            try:
                if isinstance(metadata, ImportMetadata):
                    metadata.update_status(
                        status='errored',
                        error_details=error_msg,
                    )
            except Exception as meta_err:
                print(f"[WARNING] Failed to update metadata with error: {meta_err}")
            return False, {'summary': {}, 'files': {}}
        
        has_errors = self.runner.has_errors(immich_results)
        is_success = self.runner.is_success(exit_code, immich_results)
        
        print(f"[INFO] Import results: {self.runner.get_summary_line(immich_results)}")
                
        # Apply immich-go results to manifest (dict keyed by path)
        apply_immich_results_to_manifest(metadata.file_manifest, immich_results)
        
        # Extract non-imported content
        extract_dir = self.extract_base_dir / f"{export_prefix}-extracted"
        extracted, failed = extract_non_imported_from_zip(
            zip_files=zip_files,
            extract_dir=extract_dir,
            immich_results=immich_results,
            file_manifest=metadata.file_manifest,
            skip_google_photos=True
        )
        
        # Determine final status
        if is_success and not has_errors:
            final_status = 'completed'
        elif has_errors:
            final_status = 'completed_with_errors'
        else:
            final_status = 'failed'
        
        # Update metadata with final status and results
        try:
            if isinstance(metadata, ImportMetadata):
                metadata.update_status(
                    status=final_status,
                    files=metadata.file_manifest,
                    immich_results=immich_results,
                    extra_fields={
                        'exit_code': exit_code,
                        'extracted_count': extracted,
                        'extract_failed_count': failed,
                    }
                )
        except Exception as e:
            print(f"[WARNING] Failed to update metadata: {e}")
        
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
        1. Create 'running' metadata file
        2. Import to Immich via immich-go
        3. Track which files were imported vs not imported
        4. Optionally copy non-imported files to extract dir for review
        5. Update metadata with results
        
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
        
        # Create import tag
        import_date = datetime.now().strftime('%Y-%m-%d')
        tag = f"{tag_prefix}/{import_date}"
        if device_label:
            tag = f"{tag_prefix}/{device_label}/{import_date}"
        
        # Create 'running' metadata before starting import
        # This generates source_name, log path, and calculates sizes from folder_path
        metadata = None
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            metadata = ImportMetadata(
                import_type='folder-import' if source_type == 'folder' else 'sd-import',
                source_type=source_type,
                metadata_dir=self.metadata_dir,
                folder_path=folder_path,
                extra_fields={
                    'tag': tag,
                    'device_label': device_label,
                }
            )
            metadata.save()
        except Exception as e:
            print(f"[WARNING] Failed to create running metadata: {e}")
            metadata = {
                'source_name': f"{folder_path.name}_{timestamp}",
                'source_path': str(folder_path),
                'tag': tag,
                'immich_go_log': f"logs/upload-{folder_path.name}-{timestamp}.log",
            }
        
        # Check if folder is empty (from metadata or direct check)
        if metadata.get('file_count', 0) == 0:
            print(f"[INFO] No files found in {folder_path}")
            return True, {'summary': {}, 'files': {}}
        
        print(f"[INFO] Found {metadata.get('file_count', 0)} files ({format_size(metadata.get('total_size', 0))}) in {folder_path}")
        
        # Run immich-go import with metadata object
        try:
            exit_code, immich_results = self.runner.upload_folder(metadata=metadata)
        except Exception as e:
            # Update metadata with error status
            error_msg = str(e)
            print(f"[ERROR] immich-go failed with exception: {error_msg}")
            try:
                if isinstance(metadata, ImportMetadata):
                    metadata.update_status(
                        status='errored',
                        error_details=error_msg,
                    )
            except Exception as meta_err:
                print(f"[WARNING] Failed to update metadata with error: {meta_err}")
            return False, {'summary': {}, 'files': {}}
        
        has_errors = self.runner.has_errors(immich_results)
        is_success = self.runner.is_success(exit_code, immich_results)
        
        print(f"[INFO] Results: {self.runner.get_summary_line(immich_results)}")
        
        if not is_success:
            print(f"[ERROR] Import failed (exit_code={exit_code}, has_errors={has_errors})")
        else:
            print(f"[INFO] Import completed successfully")
        
        # Apply immich-go results and track non-imported files (manifest is dict keyed by path)
        extract_dir = None
        if copy_failed_files:
            extract_dir = self.extract_base_dir / f"{folder_path.name}-{timestamp}-failed"
        
        imported_count, not_imported_count, copy_failed_count = copy_remaining_from_folder(
            source_folder=folder_path,
            extract_dir=extract_dir,
            immich_results=immich_results,
            file_manifest=metadata.file_manifest,
            copy_failed=copy_failed_files
        )
        
        # Determine final status
        if is_success and not has_errors:
            final_status = 'completed'
        elif has_errors:
            final_status = 'completed_with_errors'
        else:
            final_status = 'failed'
        
        # Update metadata with final status and results
        try:
            if isinstance(metadata, ImportMetadata):
                metadata.update_status(
                    status=final_status,
                    files=metadata.file_manifest,
                    immich_results=immich_results,
                    extra_fields={
                        'exit_code': exit_code,
                        'imported_count': imported_count,
                        'not_imported_count': not_imported_count,
                        'copy_failed_count': copy_failed_count if copy_failed_files else None,
                    }
                )
                print(f"[INFO] Updated metadata: {metadata.get('source_name')}")
        except Exception as e:
            print(f"[WARNING] Failed to update metadata: {e}")
        
        return is_success, immich_results
