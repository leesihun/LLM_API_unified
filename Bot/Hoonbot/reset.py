#!/usr/bin/env python3
"""
Hoonbot Reset Utility

Reset persistent data (memory and conversation history).
Run while Hoonbot is STOPPED to avoid file conflicts.

All data is stored as plain files under data/:
  - data/memory.md          — persistent memory (auto-injected into every LLM call)

Usage:
    python reset.py --all              # Reset everything
    python reset.py --memory           # Reset only persistent memory
    python reset.py --view-memory      # View memory.md content (read-only)
"""
import argparse
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MEMORY_FILE = os.path.join(DATA_DIR, "memory.md")


def view_memory():
    if not os.path.exists(MEMORY_FILE):
        print("No memory file found.")
        return
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    print("\n=== Memory.md ===\n")
    print(content)
    print("\n=== End Memory ===\n")


def reset_memory():
    if os.path.exists(MEMORY_FILE):
        os.remove(MEMORY_FILE)
    # Recreate with default template
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write("# Hoonbot Memory\n\nThis file stores persistent information about the user, projects, and preferences.\n\n")
    print("Memory reset to default template.")


def reset_all():
    reset_memory()
    print("\nAll Hoonbot data has been reset.")


def main():
    parser = argparse.ArgumentParser(
        description="Hoonbot Reset Utility - manage persistent data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  python reset.py --all              Reset everything
  python reset.py --memory           Clear memory
  python reset.py --view-memory      View memory content

Data directory: {DATA_DIR}
        """,
    )
    parser.add_argument("--all", action="store_true", help="Reset everything")
    parser.add_argument("--memory", action="store_true", help="Reset memory")
    parser.add_argument("--view-memory", action="store_true", help="View memory content")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()

    if not any([args.all, args.memory, args.view_memory]):
        parser.print_help()
        sys.exit(0)

    # Read-only operation
    if args.view_memory:
        view_memory()
        return

    # Destructive operations - confirm first
    actions = []
    if args.all:
        actions.append("ALL data (memory)")
    else:
        if args.memory:
            actions.append("memory")

    if actions:
        if not args.yes:
            print(f"\nThis will DELETE: {', '.join(actions)}")
            confirm = input("Are you sure? [y/N] ").strip().lower()
            if confirm != "y":
                print("Cancelled.")
                return

        if args.all:
            reset_all()
        else:
            if args.memory:
                reset_memory()


if __name__ == "__main__":
    main()
