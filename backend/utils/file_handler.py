"""
File handling utilities for uploads
"""
import shutil
import json
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import UploadFile

import config


def save_uploaded_files(
    files: List[UploadFile],
    username: str,
    session_id: str
) -> List[str]:
    """
    Save uploaded files to both persistent and scratch directories

    Args:
        files: List of uploaded files
        username: Username for persistent storage
        session_id: Session ID for scratch storage

    Returns:
        List of file paths in scratch directory
    """
    print("\n" + "=" * 80)
    print("[FILE_HANDLER] save_uploaded_files() called")
    print("=" * 80)
    print(f"Username: {username}")
    print(f"Session ID: {session_id}")
    print(f"Number of files: {len(files) if files else 0}")

    scratch_paths = []

    # Create directories
    user_upload_dir = config.UPLOAD_DIR / username
    session_scratch_dir = config.SCRATCH_DIR / session_id

    print(f"\n[FILE_HANDLER] Creating directories:")
    print(f"  User upload dir: {user_upload_dir.absolute()}")
    print(f"  Session scratch dir: {session_scratch_dir.absolute()}")

    user_upload_dir.mkdir(parents=True, exist_ok=True)
    session_scratch_dir.mkdir(parents=True, exist_ok=True)

    print(f"  ✓ Directories created")

    for i, file in enumerate(files):
        print(f"\n[FILE_HANDLER] Processing file {i+1}/{len(files)}:")
        print(f"  Filename: {file.filename}")
        print(f"  Content type: {file.content_type}")

        if file.filename:
            try:
                # Save to user's persistent upload directory
                user_file_path = user_upload_dir / file.filename
                print(f"  Saving to user dir: {user_file_path.absolute()}")
                with open(user_file_path, 'wb') as f:
                    shutil.copyfileobj(file.file, f)
                user_size = user_file_path.stat().st_size
                print(f"  ✓ Saved to user dir ({user_size} bytes)")

                # Also copy to session scratch directory
                file.file.seek(0)  # Reset file pointer
                scratch_file_path = session_scratch_dir / file.filename
                print(f"  Saving to scratch dir: {scratch_file_path.absolute()}")
                with open(scratch_file_path, 'wb') as f:
                    shutil.copyfileobj(file.file, f)
                scratch_size = scratch_file_path.stat().st_size
                print(f"  ✓ Saved to scratch dir ({scratch_size} bytes)")

                scratch_paths.append(str(scratch_file_path))
            except Exception as e:
                print(f"  ✗ ERROR saving file: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"  ✗ Skipped (no filename)")

    print(f"\n[FILE_HANDLER] Completed: {len(scratch_paths)} files saved")
    print(f"[FILE_HANDLER] Scratch paths:")
    for path in scratch_paths:
        print(f"  - {path}")
    print("=" * 80)

    return scratch_paths


def read_file_content(file_path: str) -> str:
    """
    Read file content as text (for adding to LLM context)

    Args:
        file_path: Path to the file

    Returns:
        File content as string
    """
    try:
        path = Path(file_path)

        # Handle text files
        if path.suffix in ['.txt', '.md', '.json', '.csv', '.py', '.js', '.html', '.xml']:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()

        # Handle Excel files
        elif path.suffix in ['.xlsx', '.xls']:
            import pandas as pd
            df = pd.read_excel(path)
            return df.to_string()

        # Handle other file types
        else:
            return f"[Binary file: {path.name}]"

    except Exception as e:
        return f"[Error reading file {file_path}: {str(e)}]"


def cleanup_session_files(session_id: str):
    """
    Clean up scratch files for a session

    Args:
        session_id: Session ID to clean up
    """
    session_scratch_dir = config.SCRATCH_DIR / session_id
    if session_scratch_dir.exists():
        shutil.rmtree(session_scratch_dir)


def extract_file_metadata(file_path: str) -> Dict[str, Any]:
    """
    Extract rich metadata from files based on type

    Args:
        file_path: Path to the file

    Returns:
        Dictionary with file-type-specific metadata
    """
    path = Path(file_path)
    metadata = {}

    try:
        file_type = path.suffix.lstrip('.').lower()

        # JSON files
        if file_type == 'json':
            metadata.update(_extract_json_metadata(path))

        # CSV files
        elif file_type == 'csv':
            metadata.update(_extract_csv_metadata(path))

        # Excel files
        elif file_type in ['xlsx', 'xls']:
            metadata.update(_extract_excel_metadata(path))

        # Text/Code files
        elif file_type in ['txt', 'md', 'py', 'js', 'java', 'cpp', 'c', 'h', 'go', 'rs', 'ts', 'jsx', 'tsx', 'html', 'css', 'xml']:
            metadata.update(_extract_text_metadata(path))

    except Exception as e:
        metadata['metadata_error'] = str(e)

    return metadata


def _extract_json_metadata(path: Path) -> Dict[str, Any]:
    """Extract metadata from JSON files"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        metadata = {}

        # Determine structure type
        if isinstance(data, dict):
            metadata['structure'] = 'object'
            metadata['keys'] = list(data.keys())
            metadata['key_count'] = len(data.keys())

            # Sample values for first few keys
            sample = {}
            for key in list(data.keys())[:5]:
                value = data[key]
                if isinstance(value, (dict, list)):
                    sample[key] = f"<{type(value).__name__} with {len(value)} items>"
                else:
                    sample[key] = value
            metadata['sample'] = sample

        elif isinstance(data, list):
            metadata['structure'] = 'array'
            metadata['length'] = len(data)
            if len(data) > 0:
                metadata['first_item_type'] = type(data[0]).__name__
                # Show first 2 items as sample
                metadata['sample'] = data[:2]
        else:
            metadata['structure'] = 'primitive'
            metadata['value_type'] = type(data).__name__

        return metadata

    except json.JSONDecodeError as e:
        return {'parse_error': f'Invalid JSON: {str(e)}'}
    except Exception as e:
        return {'error': str(e)}


def _extract_csv_metadata(path: Path) -> Dict[str, Any]:
    """Extract metadata from CSV files"""
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            # Detect delimiter
            sample = f.read(1024)
            f.seek(0)
            sniffer = csv.Sniffer()
            delimiter = sniffer.sniff(sample).delimiter

            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)

        metadata = {
            'rows': len(rows),
            'delimiter': delimiter
        }

        if len(rows) > 0:
            metadata['columns'] = len(rows[0])
            metadata['headers'] = rows[0]

            # Sample rows (first 3 data rows after header)
            if len(rows) > 1:
                metadata['sample_rows'] = rows[1:min(4, len(rows))]

        return metadata

    except Exception as e:
        return {'error': str(e)}


def _extract_excel_metadata(path: Path) -> Dict[str, Any]:
    """Extract metadata from Excel files"""
    try:
        import pandas as pd

        # Read all sheets
        excel_file = pd.ExcelFile(path)
        sheet_names = excel_file.sheet_names

        metadata = {
            'sheet_count': len(sheet_names),
            'sheet_names': sheet_names,
            'sheets': {}
        }

        # Get info for each sheet
        for sheet_name in sheet_names[:5]:  # Limit to first 5 sheets
            df = pd.read_excel(path, sheet_name=sheet_name)

            sheet_info = {
                'rows': len(df),
                'columns': len(df.columns),
                'column_names': df.columns.tolist(),
                'sample_rows': df.head(3).to_dict('records')  # First 3 rows
            }

            metadata['sheets'][sheet_name] = sheet_info

        return metadata

    except ImportError:
        return {'error': 'pandas not available for Excel parsing'}
    except Exception as e:
        return {'error': str(e)}


def _extract_text_metadata(path: Path) -> Dict[str, Any]:
    """Extract metadata from text/code files"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        metadata = {
            'lines': len(lines),
            'chars': sum(len(line) for line in lines),
            'preview': ''.join(lines[:10])  # First 10 lines
        }

        # For code files, try to detect structure
        file_type = path.suffix.lstrip('.').lower()
        if file_type in ['py', 'js', 'java', 'cpp', 'c', 'go', 'rs', 'ts']:
            # Simple detection of functions/classes
            imports = []
            definitions = []

            for line in lines[:100]:  # Check first 100 lines
                line_stripped = line.strip()

                # Python
                if file_type == 'py':
                    if line_stripped.startswith('import ') or line_stripped.startswith('from '):
                        imports.append(line_stripped)
                    elif line_stripped.startswith('def ') or line_stripped.startswith('class '):
                        definitions.append(line_stripped.split('(')[0].split(':')[0])

                # JavaScript/TypeScript
                elif file_type in ['js', 'ts', 'jsx', 'tsx']:
                    if 'import ' in line_stripped:
                        imports.append(line_stripped)
                    if 'function ' in line_stripped or 'class ' in line_stripped:
                        definitions.append(line_stripped.split('{')[0].strip())

            if imports:
                metadata['imports'] = imports[:10]  # First 10 imports
            if definitions:
                metadata['definitions'] = definitions[:15]  # First 15 definitions

        return metadata

    except Exception as e:
        return {'error': str(e)}
