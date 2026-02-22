#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llama.cpp Server Launcher
Starts llama-server with settings matching the LLM API project config.

Usage:
    python run_llamacpp.py -m <path_to_model.gguf>
    python run_llamacpp.py -m model.gguf --ctx-size 8192 --gpu-layers 999
    python run_llamacpp.py --hf-repo unsloth/phi-4-GGUF:q4_k_m
"""

import os
import sys
import signal
import argparse
import subprocess

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LLAMACPP_DIR = os.path.join(SCRIPT_DIR, "llamacpp")


def find_server_binary():
    exe_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"

    for root, _dirs, files in os.walk(LLAMACPP_DIR):
        if exe_name in files:
            return os.path.join(root, exe_name)

    return None


def parse_port_from_config():
    """Extract port number from LLAMACPP_HOST in config.py"""
    try:
        sys.path.insert(0, SCRIPT_DIR)
        import config
        host = config.LLAMACPP_HOST
        from urllib.parse import urlparse
        parsed = urlparse(host)
        if parsed.port:
            return parsed.port
    except Exception:
        pass
    return 5904


def build_command(args):
    binary = find_server_binary()
    if not binary:
        print("llama-server binary not found.")
        print(f"Expected location: {LLAMACPP_DIR}")
        print("Run setup first:  python setup_llamacpp.py")
        sys.exit(1)

    port = parse_port_from_config()

    cmd = [binary]

    # Model source (exactly one required)
    if args.model:
        cmd += ["--model", args.model]
    elif args.hf_repo:
        cmd += ["--hf-repo", args.hf_repo]
    else:
        print("Error: specify a model with -m <path.gguf> or --hf-repo <repo:quant>")
        sys.exit(1)

    # Server network settings
    cmd += ["--host", args.host]
    cmd += ["--port", str(args.port or port)]

    # Model alias (shows up in /v1/models response)
    if args.alias:
        cmd += ["--alias", args.alias]

    # Context and GPU
    cmd += ["--ctx-size", str(args.ctx_size)]
    cmd += ["--gpu-layers", str(args.gpu_layers)]

    # Parallel request handling
    cmd += ["--parallel", str(args.parallel)]

    # Flash attention
    if args.flash_attn:
        cmd += ["--flash-attn", args.flash_attn]

    # Chat template override
    if args.chat_template:
        cmd += ["--chat-template", args.chat_template]

    # Reasoning format
    if args.reasoning_format:
        cmd += ["--reasoning-format", args.reasoning_format]

    # Extra args passed through directly
    if args.extra:
        cmd += args.extra

    return cmd


def main():
    parser = argparse.ArgumentParser(
        description="Launch llama-server for the LLM API project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    model_group = parser.add_argument_group("model")
    model_group.add_argument("-m", "--model", help="Path to GGUF model file")
    model_group.add_argument("--hf-repo", help="HuggingFace repo (e.g. unsloth/phi-4-GGUF:q4_k_m)")

    server_group = parser.add_argument_group("server")
    server_group.add_argument("--host", default="0.0.0.0", help="Listen address (default: 0.0.0.0)")
    server_group.add_argument("--port", type=int, default=None, help="Listen port (default: from config.py, 5904)")
    server_group.add_argument("-a", "--alias", default=None, help="Model alias for /v1/models endpoint")

    perf_group = parser.add_argument_group("performance")
    perf_group.add_argument("-c", "--ctx-size", type=int, default=0, help="Context size (default: 0 = from model)")
    perf_group.add_argument("-ngl", "--gpu-layers", default="auto", help="GPU layers (default: auto)")
    perf_group.add_argument("-np", "--parallel", type=int, default=4, help="Parallel slots (default: 4)")
    perf_group.add_argument("-fa", "--flash-attn", default=None, help="Flash attention (on/off/auto)")

    template_group = parser.add_argument_group("chat")
    template_group.add_argument("--chat-template", default=None, help="Chat template name (e.g. chatml, llama3, gpt-oss)")
    template_group.add_argument("--reasoning-format", default=None, help="Reasoning format (none/deepseek/auto)")

    parser.add_argument("extra", nargs=argparse.REMAINDER, help="Additional llama-server arguments")

    args = parser.parse_args()
    cmd = build_command(args)

    print("=" * 70)
    print("llama.cpp Server")
    print("=" * 70)
    print()
    print("Command:")
    print(f"  {' '.join(cmd)}")
    print()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    process = None
    try:
        process = subprocess.Popen(cmd, env=env)
        process.wait()
    except KeyboardInterrupt:
        print("\nShutting down llama-server...")
    finally:
        if process and process.poll() is None:
            if sys.platform == "win32":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        print("llama-server stopped.")


if __name__ == "__main__":
    main()
