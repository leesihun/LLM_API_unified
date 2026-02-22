#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llama.cpp Setup Script
Downloads and extracts pre-built llama.cpp binaries from GitHub releases.
"""

import os
import sys
import json
import shutil
import zipfile
import tarfile
import platform
import argparse
import urllib.request
import urllib.error

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

INSTALL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llamacpp")
GITHUB_API_URL = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

# Maps (os, arch) to the list of available build variants
BUILD_VARIANTS = {
    ("Windows", "x86_64"): {
        "cpu":       "llama-{version}-bin-win-cpu-x64.zip",
        "cuda-12.4": "llama-{version}-bin-win-cuda-12.4-x64.zip",
        "cuda-13.1": "llama-{version}-bin-win-cuda-13.1-x64.zip",
        "vulkan":    "llama-{version}-bin-win-vulkan-x64.zip",
    },
    ("Windows", "aarch64"): {
        "cpu": "llama-{version}-bin-win-cpu-arm64.zip",
    },
    ("Linux", "x86_64"): {
        "cpu":    "llama-{version}-bin-ubuntu-x64.tar.gz",
        "vulkan": "llama-{version}-bin-ubuntu-vulkan-x64.tar.gz",
    },
    ("Darwin", "arm64"): {
        "cpu": "llama-{version}-bin-macos-arm64.tar.gz",
    },
    ("Darwin", "x86_64"): {
        "cpu": "llama-{version}-bin-macos-x64.tar.gz",
    },
}

CUDART_FILES = {
    "cuda-12.4": "cudart-llama-bin-win-cuda-12.4-x64.zip",
    "cuda-13.1": "cudart-llama-bin-win-cuda-13.1-x64.zip",
}


def get_platform_key():
    system = platform.system()
    machine = platform.machine().lower()
    arch_map = {
        "amd64": "x86_64", "x86_64": "x86_64", "x64": "x86_64",
        "arm64": "arm64", "aarch64": "aarch64",
    }
    arch = arch_map.get(machine, machine)
    if system == "Darwin" and arch == "aarch64":
        arch = "arm64"
    return (system, arch)


def fetch_latest_release():
    print("Fetching latest llama.cpp release info...")
    req = urllib.request.Request(GITHUB_API_URL, headers={"User-Agent": "llama-cpp-setup"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    version = data["tag_name"]
    asset_names = {a["name"]: a["browser_download_url"] for a in data["assets"]}
    print(f"Latest release: {version}")
    return version, asset_names


def download_file(url, dest_path):
    print(f"Downloading: {os.path.basename(dest_path)}")
    req = urllib.request.Request(url, headers={"User-Agent": "llama-cpp-setup"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded * 100 // total
                    mb_done = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    print(f"\r  {mb_done:.1f}/{mb_total:.1f} MB ({pct}%)", end="", flush=True)
        print()


def extract_archive(archive_path, dest_dir):
    print(f"Extracting: {os.path.basename(archive_path)}")
    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    elif archive_path.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(dest_dir)


def find_server_binary(search_dir):
    exe_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    for root, _dirs, files in os.walk(search_dir):
        if exe_name in files:
            return os.path.join(root, exe_name)
    return None


def setup(variant=None):
    platform_key = get_platform_key()
    variants = BUILD_VARIANTS.get(platform_key)
    if not variants:
        print(f"No pre-built binaries for {platform_key[0]} {platform_key[1]}.")
        print("You'll need to build llama.cpp from source: https://github.com/ggml-org/llama.cpp#build")
        sys.exit(1)

    version, asset_urls = fetch_latest_release()

    if variant is None:
        print(f"\nAvailable variants for {platform_key[0]} {platform_key[1]}:")
        variant_list = list(variants.keys())
        for i, v in enumerate(variant_list):
            filename = variants[v].format(version=version)
            size_note = " (CUDA runtime also downloaded)" if v.startswith("cuda") else ""
            print(f"  [{i + 1}] {v}{size_note}")

        while True:
            choice = input(f"\nSelect variant [1-{len(variant_list)}]: ").strip()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(variant_list):
                    variant = variant_list[idx]
                    break
            except ValueError:
                pass
            print("Invalid choice.")

    if variant not in variants:
        print(f"Unknown variant '{variant}'. Available: {', '.join(variants.keys())}")
        sys.exit(1)

    print(f"\nSelected variant: {variant}")

    if os.path.exists(INSTALL_DIR):
        existing_binary = find_server_binary(INSTALL_DIR)
        if existing_binary:
            print(f"Existing installation found at: {INSTALL_DIR}")
            answer = input("Overwrite? [y/N]: ").strip().lower()
            if answer != "y":
                print("Aborted.")
                return
        shutil.rmtree(INSTALL_DIR)

    os.makedirs(INSTALL_DIR, exist_ok=True)
    tmp_dir = os.path.join(INSTALL_DIR, "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        main_filename = variants[variant].format(version=version)
        main_url = asset_urls.get(main_filename)
        if not main_url:
            print(f"Asset '{main_filename}' not found in release {version}.")
            sys.exit(1)

        archive_path = os.path.join(tmp_dir, main_filename)
        download_file(main_url, archive_path)
        extract_archive(archive_path, INSTALL_DIR)

        if variant.startswith("cuda") and platform_key[0] == "Windows":
            cudart_filename = CUDART_FILES.get(variant)
            if cudart_filename:
                cudart_url = asset_urls.get(cudart_filename)
                if cudart_url:
                    cudart_path = os.path.join(tmp_dir, cudart_filename)
                    download_file(cudart_url, cudart_path)
                    extract_archive(cudart_path, INSTALL_DIR)
                else:
                    print(f"Warning: CUDA runtime '{cudart_filename}' not found, GPU may not work.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    binary = find_server_binary(INSTALL_DIR)
    if binary:
        if sys.platform != "win32":
            os.chmod(binary, 0o755)
        print(f"\nllama-server installed at: {binary}")
        print(f"Version: {version}, Variant: {variant}")
        print("\nSetup complete. Run the server with:")
        print(f"  python run_llamacpp.py -m <path_to_model.gguf>")
    else:
        print("Warning: llama-server binary not found after extraction.")
        print(f"Check contents of: {INSTALL_DIR}")


def main():
    parser = argparse.ArgumentParser(description="Download and set up llama.cpp")
    parser.add_argument(
        "--variant",
        choices=["cpu", "cuda-12.4", "cuda-13.1", "vulkan"],
        help="Build variant to download (interactive prompt if omitted)",
    )
    args = parser.parse_args()
    setup(variant=args.variant)


if __name__ == "__main__":
    main()
