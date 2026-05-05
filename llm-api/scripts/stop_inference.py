#!/usr/bin/env python3
"""
Stop inference control script.

Usage:
  python stop_inference.py          # Create stop file (halts all running inference)
  python stop_inference.py clear    # Remove stop file (allows inference to resume)
  python stop_inference.py status   # Show current stop signal status
"""
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

import config
from backend.utils.stop_signal import request_stop, clear_stop, is_stop_requested


def main():
    command = sys.argv[1].lower() if len(sys.argv) > 1 else "stop"

    if command in ("stop", "on", "create"):
        request_stop()
        print(f"Stop file: {config.STOP_FILE}")

    elif command in ("clear", "off", "remove", "delete"):
        if is_stop_requested():
            clear_stop()
            print(f"Stop file removed: {config.STOP_FILE}")
        else:
            print("No stop file found — inference is already running normally.")

    elif command == "status":
        active = is_stop_requested()
        if active:
            print(f"STOP ACTIVE — inference is halted ({config.STOP_FILE})")
        else:
            print("Stop signal inactive — inference running normally.")

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
