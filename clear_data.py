#!/usr/bin/env python3
"""
Clear script for LLM_API development data.
Clears: prompts.log, scratch directory, sessions directory
"""

import shutil
from pathlib import Path


def clear_file(filepath: Path, name: str) -> None:
    """Clear a file's contents (truncate to empty)."""
    if filepath.exists():
        filepath.write_text("")
        print(f"[OK] Cleared {name}")
    else:
        print(f"[--] {name} not found (skipped)")


def clear_directory(dirpath: Path, name: str) -> None:
    """Remove all contents of a directory, keeping the directory itself."""
    if dirpath.exists():
        for item in dirpath.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print(f"[OK] Cleared {name}")
    else:
        dirpath.mkdir(parents=True, exist_ok=True)
        print(f"[--] {name} created (was missing)")


def main():
    script_dir = Path(__file__).parent
    data_dir = script_dir / "data"

    print("=== LLM_API Data Cleanup ===")
    print()

    # Clear prompts.log
    clear_file(data_dir / "logs" / "prompts.log", "prompts.log")

    # Clear scratch directory
    clear_directory(data_dir / "scratch", "scratch directory")

    # Clear sessions directory
    clear_directory(data_dir / "sessions", "sessions directory")

    print()
    print("=== Cleanup Complete ===")


if __name__ == "__main__":
    main()
