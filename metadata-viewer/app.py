#!/usr/bin/env python3
"""
Metadata Viewer - Web UI for viewing Google Takeout import metadata
"""
import json
import os
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, jsonify, send_file, request

app = Flask(__name__)

METADATA_DIR = Path(os.getenv("METADATA_DIR", "/data/metadata"))


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
            with open(f) as mf:
                data = json.load(mf)
                data['_filename'] = f.name
                data['_path'] = str(f)
                
                # Check for timeout: if status is 'running' and update_time is older than 5 minutes
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
                        
                        if age_seconds > 300:  # 5 minutes
                            data['status'] = 'timeout'
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
    
    # Sort by start_time descending (newest first), falling back to extraction_date or empty string
    metadata_files.sort(
        key=lambda m: m.get('start_time') or m.get('extraction_date') or '',
        reverse=True
    )
    
    return metadata_files


def get_log_files():
    """Get list of immich-go log files."""
    logs_dir = METADATA_DIR / "logs"
    if not logs_dir.exists():
        return []
    
    logs = []
    for f in sorted(logs_dir.glob("*.log"), reverse=True):
        stat = f.stat()
        logs.append({
            'name': f.name,
            'path': str(f),
            'size': format_size(stat.st_size),
            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    return logs


def aggregate_stats(metadata_files):
    """Aggregate statistics across all imports."""
    stats = {
        'total_imports': len(metadata_files),
        'total_files': 0,
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
        stats['total_files'] += m.get('total_files', 0)
        
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
