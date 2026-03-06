"""
build_installer.py - AIBotMessenger Windows Installer Builder
=============================================================
Run this script (once, from within the repo root) to produce
a standalone Windows installer:

    python build_installer.py

Output:  dist/AIBotMessenger-Setup.exe

Requirements (installed automatically if missing):
    pip install pyinstaller

The resulting .exe:
  • Bundles the entire Hoonbot/ and Messenger/ source trees
  • Bundles installation_config.txt and settings.txt
  • On launch: self-elevates to Administrator, runs a console
    installer that installs Python/Node/SSH, copies files,
    configures port forwarding, and creates shortcuts.

Users can place a custom installation_config.txt next to
AIhoonbot-Setup.exe to override bundled defaults before running.
"""

import sys
import os
import subprocess
import shutil
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT   = Path(__file__).resolve().parent
INSTALLER_PY = REPO_ROOT / "installer.py"
CONFIG_TXT   = REPO_ROOT / "installation_config.txt"
SETTINGS_TXT = REPO_ROOT / "settings.txt"
DIST_DIR     = REPO_ROOT / "dist"
BUILD_DIR    = REPO_ROOT / "build"
SPEC_FILE    = REPO_ROOT / "AIBotMessenger-Setup.spec"

EXE_NAME = "AIBotMessenger-Setup"

# Directories to bundle (relative to REPO_ROOT)
# Excluded sub-paths are stripped before bundling.
BUNDLE_DIRS = ["Hoonbot", "Messenger"]

# Patterns to EXCLUDE when copying source for bundling
EXCLUDE_PATTERNS = [
    # Python
    r"__pycache__",
    r"\.pyc$",
    r"\.pyo$",
    # Node
    r"node_modules",
    r"\.next",
    # Build outputs
    r"dist-web",
    r"dist-electron",
    r"dist$",           # top-level dist/ inside a component
    r"\.cache",
    # Runtime data
    r"[/\\]data[/\\]",
    # Git
    r"\.git",
    # Misc
    r"\.env$",
    r"\.DS_Store",
]


def _matches_exclude(path: Path) -> bool:
    s = str(path)
    return any(re.search(pat, s) for pat in EXCLUDE_PATTERNS)


def _copy_filtered(src: Path, dst: Path):
    """
    Recursively copy src → dst, skipping excluded paths.
    Uses os.walk so we can prune excluded directories before descending
    into them (avoids broken symlinks / junction crashes inside node_modules).
    """
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    src_str = str(src)
    for dirpath, dirnames, filenames in os.walk(src_str, followlinks=False):
        rel_dir = Path(dirpath).relative_to(src)
        target_dir = dst / rel_dir

        # Prune excluded sub-directories in-place (prevents os.walk from descending)
        dirnames[:] = [
            d for d in dirnames
            if not _matches_exclude(Path(dirpath) / d)
        ]

        target_dir.mkdir(parents=True, exist_ok=True)

        for fname in filenames:
            src_file = Path(dirpath) / fname
            if _matches_exclude(src_file):
                continue
            try:
                shutil.copy2(src_file, target_dir / fname)
            except (OSError, shutil.Error) as e:
                print(f"  [skip] {src_file.relative_to(src)}: {e}")


# ---------------------------------------------------------------------------
# Ensure PyInstaller is available
# ---------------------------------------------------------------------------

def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        print("[ok] PyInstaller already installed")
    except ImportError:
        print("[..] Installing PyInstaller…")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller", "--quiet"]
        )
        print("[ok] PyInstaller installed")


# ---------------------------------------------------------------------------
# Prepare a staging directory with filtered source
# ---------------------------------------------------------------------------

def prepare_staging() -> Path:
    staging = REPO_ROOT / "_installer_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    for dirname in BUNDLE_DIRS:
        src = REPO_ROOT / dirname
        if not src.exists():
            print(f"[warn] {dirname}/ not found — skipping")
            continue
        print(f"[..] Staging {dirname}/…")
        _copy_filtered(src, staging / dirname)
        print(f"[ok] Staged {dirname}/")

    # Copy flat config files
    for src_file in (CONFIG_TXT, SETTINGS_TXT):
        if src_file.exists():
            shutil.copy2(src_file, staging / src_file.name)
            print(f"[ok] Staged {src_file.name}")

    return staging


# ---------------------------------------------------------------------------
# Build the --add-data arguments from staging
# ---------------------------------------------------------------------------

def build_add_data_args(staging: Path) -> list[str]:
    """
    Return a flat list of --add-data args, one per item in staging.
    Format: --add-data "src;dest"  (Windows uses semicolon)
    """
    args = []
    for item in sorted(staging.iterdir()):
        if item.is_dir():
            args += ["--add-data", f"{item};{item.name}"]
        elif item.is_file():
            args += ["--add-data", f"{item};."]
    return args


# ---------------------------------------------------------------------------
# Run PyInstaller
# ---------------------------------------------------------------------------

def run_pyinstaller(staging: Path):
    print("\n[..] Running PyInstaller…")

    add_data = build_add_data_args(staging)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",                     # keep console window visible
        "--name", EXE_NAME,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(REPO_ROOT),
        "--clean",
        # Hidden imports needed by the installer
        "--hidden-import", "winreg",
        "--hidden-import", "ctypes",
        # UAC manifest — request Administrator on launch
        "--uac-admin",
    ] + add_data + [str(INSTALLER_PY)]

    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print("\n[error] PyInstaller failed.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Post-build: copy installation_config.txt next to the .exe
# ---------------------------------------------------------------------------

def post_build():
    exe = DIST_DIR / f"{EXE_NAME}.exe"
    if not exe.exists():
        print(f"[error] Expected output not found: {exe}")
        sys.exit(1)

    # Place a user-editable config copy next to the .exe
    cfg_dst = DIST_DIR / "installation_config.txt"
    if CONFIG_TXT.exists():
        shutil.copy2(CONFIG_TXT, cfg_dst)
        print(f"[ok] Copied installation_config.txt → {cfg_dst}")

    size_mb = exe.stat().st_size / 1_048_576
    print(f"\n{'='*60}")
    print(f"  Build complete!")
    print(f"     {exe}  ({size_mb:.1f} MB)")
    print(f"")
    print(f"  Distribute the contents of:  dist/")
    print(f"    - AIBotMessenger-Setup.exe")
    print(f"    - installation_config.txt   (users edit this first)")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Cleanup staging
# ---------------------------------------------------------------------------

def cleanup(staging: Path):
    try:
        shutil.rmtree(staging)
    except Exception:
        pass
    spec = SPEC_FILE
    if spec.exists():
        try:
            spec.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 60)
    print("  AIBotMessenger - Installer Builder")
    print("=" * 60)

    # Pre-flight checks
    if not INSTALLER_PY.exists():
        print(f"[error] installer.py not found at {INSTALLER_PY}")
        sys.exit(1)
    if not CONFIG_TXT.exists():
        print(f"[error] installation_config.txt not found at {CONFIG_TXT}")
        sys.exit(1)

    ensure_pyinstaller()

    staging = prepare_staging()
    try:
        run_pyinstaller(staging)
        post_build()
    finally:
        cleanup(staging)


if __name__ == "__main__":
    main()
