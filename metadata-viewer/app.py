#!/usr/bin/env python3
"""
Metadata Viewer - Web UI for viewing Google Takeout import metadata
"""
import json
import os
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, jsonify, send_file, request, make_response

app = Flask(__name__)

METADATA_DIR = Path(os.getenv("METADATA_DIR", "/data/metadata"))


@app.after_request
def add_no_cache_headers(response):
    """Add no-cache headers to all responses to prevent stale data."""
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def format_size(size_bytes):
    """Format bytes to human readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def load_metadata_files():
    """Load all metadata JSON files."""
    metadata_files = []
    if not METADATA_DIR.exists():
        return metadata_files
    
    now = datetime.now()
    
    for f in METADATA_DIR.glob("*.metadata.json"):
        try:
            # Get file modification time from OS
            file_mtime = datetime.fromtimestamp(f.stat().st_mtime)
            
            with open(f) as mf:
                data = json.load(mf)
                data['_filename'] = f.name
                data['_path'] = str(f)
                data['_modified'] = file_mtime.strftime('%Y-%m-%d %H:%M:%S')
                data['_modified_iso'] = file_mtime.isoformat()
                
                # Check for timeout: if status is 'running' and update_time is older than 2 minutes
                # Also check if the associated log file is still being written to
                if data.get('status') == 'running' and 'update_time' in data:
                    try:
                        update_time = datetime.fromisoformat(data['update_time'].replace('Z', '+00:00'))
                        # Make now timezone-aware if update_time is
                        if update_time.tzinfo is not None:
                            from datetime import timezone
                            now_aware = datetime.now(timezone.utc)
                            age_seconds = (now_aware - update_time).total_seconds()
                        else:
                            age_seconds = (now - update_time).total_seconds()
                        
                        # Check if log file exists and was recently modified
                        log_file = data.get('immich_go_log')
                        log_active = False
                        if log_file and age_seconds > 60:  # Only check log if metadata is stale
                            log_path = METADATA_DIR / log_file
                            if log_path.exists():
                                log_mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
                                log_age = (now - log_mtime).total_seconds()
                                log_active = log_age < 120  # Log modified in last 2 minutes
                        
                        # Only mark as timeout if both metadata and log are stale
                        if age_seconds > 120 and not log_active:  # 2 minutes
                            data['status'] = 'timeout'
                            data['_timeout_age'] = int(age_seconds)
                    except (ValueError, TypeError):
                        pass
                
                # Handle both old zip_file and new zip_files format
                if 'zip_files' in data:
                    # New format: array of {name, size}
                    total_size = sum(z.get('size', 0) for z in data['zip_files'])
                    data['_zip_size_formatted'] = format_size(total_size)
                    data['_zip_names'] = ', '.join(z.get('name', '') for z in data['zip_files'])
                    data['_zip_count'] = len(data['zip_files'])
                elif 'zip_size' in data:
                    # Old format: single zip_file and zip_size
                    data['_zip_size_formatted'] = format_size(data['zip_size'])
                    data['_zip_names'] = data.get('zip_file', 'N/A')
                    data['_zip_count'] = 1
                elif 'total_size' in data:
                    # Folder import format
                    data['_zip_size_formatted'] = format_size(data['total_size'])
                    data['_zip_names'] = data.get('source_name', 'N/A')
                    data['_zip_count'] = 0
                
                metadata_files.append(data)
        except Exception as e:
            print(f"Error loading {f}: {e}")
    
    # Sort by file modification time descending (most recently modified first)
    metadata_files.sort(
        key=lambda m: m.get('_modified_iso') or '',
        reverse=True
    )
    
    return metadata_files


def get_log_files():
    """Get list of immich-go log files."""
    logs_dir = METADATA_DIR / "logs"
    if not logs_dir.exists():
        return []
    
    logs = []
    for f in logs_dir.glob("*.log"):
        stat = f.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime)
        logs.append({
            'name': f.name,
            'path': str(f),
            'size': format_size(stat.st_size),
            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'modified': mtime.strftime('%Y-%m-%d %H:%M:%S'),
            'modified_iso': mtime.isoformat()
        })
    
    # Sort by modification time descending (most recently modified first)
    logs.sort(key=lambda l: l['modified_iso'], reverse=True)
    return logs


def aggregate_stats(metadata_files):
    """Aggregate statistics across all imports."""
    stats = {
        'total_imports': len(metadata_files),
        'file_count': 0,
        'total_size': 0,
        'by_type': {'immich-go': 0, 'extract': 0},
        'by_source': {'google-photos': 0, 'google-takeout': 0, 'sd-card': 0, 'folder': 0},
        'uploaded': 0,
        'server_duplicate': 0,
        'local_duplicate': 0,
        'server_better': 0,
        'extracted': 0,
        'errors': 0
    }
    
    for m in metadata_files:
        stats['file_count'] += m.get('file_count', 0)
        
        # Handle both zip_files array and old zip_size format
        if 'zip_files' in m:
            stats['total_size'] += sum(z.get('size', 0) for z in m['zip_files'])
        elif 'zip_size' in m:
            stats['total_size'] += m.get('zip_size', 0)
        elif 'total_size' in m:
            stats['total_size'] += m.get('total_size', 0)
        
        import_type = m.get('import_type', 'unknown')
        if import_type in stats['by_type']:
            stats['by_type'][import_type] += 1
        
        source_type = m.get('source_type', 'unknown')
        if source_type in stats['by_source']:
            stats['by_source'][source_type] += 1
        
        summary = m.get('summary', {})
        stats['uploaded'] += summary.get('uploaded_success', 0)
        stats['server_duplicate'] += summary.get('server_duplicate', 0)
        stats['local_duplicate'] += summary.get('local_duplicate', 0)
        stats['server_better'] += summary.get('server_better', 0)
        stats['extracted'] += summary.get('extracted', 0)
        stats['errors'] += summary.get('errors', 0)
    
    stats['_total_size_formatted'] = format_size(stats['total_size'])
    return stats


@app.route('/')
def index():
    """Main dashboard."""
    metadata_files = load_metadata_files()
    stats = aggregate_stats(metadata_files)
    logs = get_log_files()
    return render_template('index.html', 
                         metadata_files=metadata_files, 
                         stats=stats,
                         logs=logs)


@app.route('/api/metadata')
def api_metadata():
    """API endpoint for metadata files."""
    return jsonify(load_metadata_files())


@app.route('/api/metadata/<filename>')
def api_metadata_detail(filename):
    """API endpoint for specific metadata file."""
    filepath = METADATA_DIR / filename
    if not filepath.exists():
        return jsonify({'error': 'Not found'}), 404
    
    try:
        with open(filepath) as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def api_stats():
    """API endpoint for aggregate statistics."""
    metadata_files = load_metadata_files()
    return jsonify(aggregate_stats(metadata_files))


@app.route('/api/logs')
def api_logs():
    """API endpoint for log files."""
    return jsonify(get_log_files())


@app.route('/api/logs/<filename>')
def api_log_content(filename):
    """API endpoint for log file content."""
    logs_dir = METADATA_DIR / "logs"
    filepath = logs_dir / filename
    
    if not filepath.exists():
        return jsonify({'error': 'Not found'}), 404
    
    # Parse JSON log entries
    entries = []
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        entries.append({'raw': line})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    # Get query params for filtering
    level = request.args.get('level')
    limit = request.args.get('limit', type=int)
    
    if level:
        entries = [e for e in entries if e.get('level', '').upper() == level.upper()]
    
    if limit:
        entries = entries[-limit:]
    
    return jsonify({
        'filename': filename,
        'total_entries': len(entries),
        'entries': entries
    })


@app.route('/view/<filename>')
def view_metadata(filename):
    """View detailed metadata for a specific import."""
    filepath = METADATA_DIR / filename
    if not filepath.exists():
        return "Not found", 404
    
    try:
        with open(filepath) as f:
            metadata = json.load(f)
        return render_template('detail.html', metadata=metadata, filename=filename)
    except Exception as e:
        return f"Error: {e}", 500


@app.route('/logs/<filename>')
def view_log(filename):
    """View log file content."""
    logs_dir = METADATA_DIR / "logs"
    filepath = logs_dir / filename
    
    if not filepath.exists():
        return "Not found", 404
    
    # Get file timestamps
    stat = filepath.stat()
    created = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
    modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template('log.html', filename=filename, created=created, modified=modified)


if __name__ == '__main__':
    print(f"Starting Metadata Viewer...")
    print(f"Metadata directory: {METADATA_DIR}")
    app.run(host='0.0.0.0', port=5000, debug=os.getenv('DEBUG', 'false').lower() == 'true')
