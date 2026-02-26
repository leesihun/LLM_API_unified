"""
AIhoonbot.com — Windows One-Click Installer
============================================
Bundled by build_installer.py via PyInstaller.
Run as Administrator (the script self-elevates if needed).
"""

import sys
import os
import re
import shutil
import subprocess
import threading
import ctypes
import winreg
import urllib.request
import time
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# ---------------------------------------------------------------------------
# Helpers — resource path (works both frozen and unfrozen)
# ---------------------------------------------------------------------------

def _resource(relative: str) -> str:
    """Return absolute path to a bundled resource."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


# ---------------------------------------------------------------------------
# Config reader
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    cfg = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
                if m:
                    k = m.group(1)
                    v = m.group(2).strip().strip('"').strip("'")
                    cfg[k] = v
    except FileNotFoundError:
        pass
    return cfg


def cfg_bool(cfg: dict, key: str, default: bool = False) -> bool:
    return cfg.get(key, str(default)).lower() in ("true", "1", "yes")


def cfg_int(cfg: dict, key: str, default: int = 0) -> int:
    try:
        return int(cfg.get(key, default))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# UAC self-elevation
# ---------------------------------------------------------------------------

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def elevate():
    """Re-launch this process as Administrator."""
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# Low-level utilities
# ---------------------------------------------------------------------------

def run(cmd: list[str] | str, cwd: str | None = None,
        shell: bool = False, timeout: int = 600) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, shell=shell, capture_output=True,
            text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timed out"
    except Exception as e:
        return -1, "", str(e)


def powershell(script: str, timeout: int = 300) -> tuple[int, str, str]:
    return run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
    )


def winget_install(pkg_id: str, name: str, log) -> bool:
    log(f"Installing {name} via winget…")
    rc, out, err = run(
        ["winget", "install", "--id", pkg_id, "-e",
         "--accept-package-agreements", "--accept-source-agreements",
         "--silent"],
        timeout=300,
    )
    if rc == 0:
        log(f"  ✓ {name} installed")
        return True
    # Exit code 0x8A15002B means "already installed"
    if rc == -1879048149 or "already installed" in out.lower() + err.lower():
        log(f"  ✓ {name} already present")
        return True
    log(f"  ✗ winget failed (rc={rc}): {err.strip() or out.strip()}")
    return False


# ---------------------------------------------------------------------------
# Individual installation steps
# ---------------------------------------------------------------------------

def step_check_python(log) -> bool:
    log("Checking Python…")
    for cmd in (["python", "--version"], ["py", "--version"]):
        rc, out, _ = run(cmd)
        if rc == 0:
            log(f"  ✓ Found: {out.strip()}")
            return True
    log("  Python not found — installing via winget…")
    ok = winget_install("Python.Python.3.11", "Python 3.11", log)
    # Refresh PATH in this process
    try:
        env = os.environ.copy()
        env["PATH"] = (
            subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "[System.Environment]::GetEnvironmentVariable('PATH','Machine') + ';' + "
                 "[System.Environment]::GetEnvironmentVariable('PATH','User')"],
                text=True,
            ).strip()
        )
        os.environ["PATH"] = env["PATH"]
    except Exception:
        pass
    return ok


def step_check_node(log) -> bool:
    log("Checking Node.js…")
    rc, out, _ = run(["node", "--version"])
    if rc == 0:
        log(f"  ✓ Found: {out.strip()}")
        return True
    log("  Node.js not found — installing via winget…")
    ok = winget_install("OpenJS.NodeJS.LTS", "Node.js LTS", log)
    # Refresh PATH
    try:
        new_path = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "[System.Environment]::GetEnvironmentVariable('PATH','Machine') + ';' + "
             "[System.Environment]::GetEnvironmentVariable('PATH','User')"],
            text=True,
        ).strip()
        os.environ["PATH"] = new_path
    except Exception:
        pass
    return ok


def step_install_ssh(cfg: dict, log) -> bool:
    if not cfg_bool(cfg, "INSTALL_SSH", True):
        log("Skipping SSH installation (INSTALL_SSH=false)")
        return True

    ssh_port = cfg_int(cfg, "SSH_PORT", 22)
    log("Checking OpenSSH Server…")

    rc, out, _ = powershell(
        "Get-WindowsCapability -Online -Name OpenSSH.Server* | Select-Object -ExpandProperty State"
    )
    if rc == 0 and "installed" in out.lower():
        log("  ✓ OpenSSH Server already installed")
    else:
        log("  Installing OpenSSH Server via Windows optional features…")
        rc2, out2, err2 = powershell(
            "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0",
            timeout=180,
        )
        if rc2 != 0:
            log(f"  ! Windows feature install failed: {err2.strip()}")
            log("  Falling back to winget…")
            winget_install("Microsoft.OpenSSH.Beta", "OpenSSH", log)

    log("  Starting OpenSSH service…")
    powershell("Start-Service sshd -ErrorAction SilentlyContinue")
    powershell("Set-Service -Name sshd -StartupType Automatic")

    if ssh_port != 22:
        log(f"  Setting SSH port to {ssh_port}…")
        config_path = r"C:\ProgramData\ssh\sshd_config"
        powershell(
            f"(Get-Content '{config_path}') -replace '#?Port 22', 'Port {ssh_port}' | "
            f"Set-Content '{config_path}'"
        )
        powershell("Restart-Service sshd")

    log(f"  Adding firewall rule for SSH port {ssh_port}…")
    powershell(
        f"New-NetFirewallRule -Name 'AIhoonbot-SSH' -DisplayName 'AIhoonbot SSH' "
        f"-Direction Inbound -Protocol TCP -LocalPort {ssh_port} "
        f"-Action Allow -ErrorAction SilentlyContinue"
    )
    log("  ✓ SSH configured")
    return True


def step_copy_files(cfg: dict, log) -> bool:
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIhoonbot"))
    log(f"Installing to {install_dir}…")

    install_dir.mkdir(parents=True, exist_ok=True)

    for component in ("Hoonbot", "Messenger"):
        src = Path(_resource(component))
        dst = install_dir / component
        if not src.exists():
            log(f"  ✗ Bundled source for {component} not found at {src}")
            return False
        log(f"  Copying {component}…")
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        log(f"  ✓ {component} copied")

    # Copy settings.txt template
    settings_src = Path(_resource("settings.txt"))
    settings_dst = install_dir / "settings.txt"
    if settings_src.exists() and not settings_dst.exists():
        shutil.copy2(settings_src, settings_dst)

    # Write a Windows-native start-all.bat (always fresh)
    messenger_port = cfg_int(cfg, "MESSENGER_PORT", 10006)
    hoonbot_port = cfg_int(cfg, "HOONBOT_PORT", 3939)
    bat = install_dir / "start-all.bat"
    bat.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul 2>&1\r\n"
        "title AIhoonbot.com\r\n"
        "echo Starting Messenger...\r\n"
        f'start "Messenger" cmd /k "cd /d "%~dp0Messenger" && npm run dev:server"\r\n'
        "timeout /t 3 /nobreak >nul\r\n"
        "echo Starting Hoonbot...\r\n"
        f'start "Hoonbot" cmd /k "cd /d "%~dp0Hoonbot" && python hoonbot.py"\r\n'
        "echo.\r\n"
        "echo All services started.\r\n"
        f"echo   Messenger : http://localhost:{messenger_port}\r\n"
        f"echo   Hoonbot   : http://localhost:{hoonbot_port}\r\n"
        "echo.\r\n"
        "timeout /t 8\r\n",
        encoding="utf-8",
    )

    stop_bat = install_dir / "stop-all.bat"
    stop_bat.write_text(
        "@echo off\r\n"
        "echo Stopping services...\r\n"
        'taskkill /F /FI "WINDOWTITLE eq Messenger*" >nul 2>&1\r\n'
        'taskkill /F /FI "WINDOWTITLE eq Hoonbot*" >nul 2>&1\r\n'
        "echo Done.\r\n"
        "timeout /t 3\r\n",
        encoding="utf-8",
    )

    log(f"  ✓ Files installed to {install_dir}")
    return True


def step_write_settings(cfg: dict, log) -> bool:
    """Patch settings.txt in the installation directory with config values."""
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIhoonbot"))
    settings_path = install_dir / "settings.txt"

    if not settings_path.exists():
        log("  ! settings.txt not found, skipping settings patch")
        return True

    log("Patching settings.txt with installation values…")
    text = settings_path.read_text(encoding="utf-8")

    patches = {
        "MESSENGER_PORT": cfg.get("MESSENGER_PORT", "10006"),
        "HOONBOT_PORT":   cfg.get("HOONBOT_PORT", "3939"),
        "LLM_API_PORT":   cfg.get("LLM_API_PORT", "10007"),
        "HOONBOT_BOT_NAME":   cfg.get("BOT_NAME", "Bot"),
        "HOONBOT_HOME_ROOM_ID": cfg.get("HOME_ROOM_ID", "1"),
        "HOONBOT_LLM_USERNAME": cfg.get("LLM_USERNAME", "admin"),
        "HOONBOT_LLM_PASSWORD": cfg.get("LLM_PASSWORD", "administrator"),
    }

    for key, value in patches.items():
        # Replace existing KEY=... line (comment-aware)
        text = re.sub(
            rf'^({key})=.*$',
            f'{key}={value}',
            text,
            flags=re.MULTILINE,
        )

    # Write the LLM_API_URL if set
    llm_url = cfg.get("LLM_API_URL", "").strip()
    if llm_url:
        if "LLM_API_URL=" in text:
            text = re.sub(r'^#?\s*LLM_API_URL=.*$', f'LLM_API_URL={llm_url}',
                          text, flags=re.MULTILINE)
        else:
            text += f'\nLLM_API_URL={llm_url}\n'

    settings_path.write_text(text, encoding="utf-8")
    log("  ✓ settings.txt patched")
    return True


def step_pip_install(cfg: dict, log) -> bool:
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIhoonbot"))
    req = install_dir / "Hoonbot" / "requirements.txt"
    if not req.exists():
        log("  ! requirements.txt not found, skipping pip install")
        return True
    log("Installing Python dependencies (pip)…")
    for py_cmd in ("python", "py"):
        rc, out, err = run(
            [py_cmd, "-m", "pip", "install", "-r", str(req), "--quiet"],
            timeout=300,
        )
        if rc == 0:
            log("  ✓ Python dependencies installed")
            return True
        if "not recognized" not in err:
            log(f"  ✗ pip install failed: {err.strip()[-300:]}")
            return False
    log("  ✗ python executable not found")
    return False


def step_npm_install(cfg: dict, log) -> bool:
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIhoonbot"))
    messenger_dir = str(install_dir / "Messenger")
    log("Installing Node.js dependencies (npm install)…")
    rc, out, err = run(["npm", "install"], cwd=messenger_dir, timeout=300)
    if rc != 0:
        log(f"  ✗ npm install failed: {err.strip()[-300:]}")
        return False
    log("  ✓ npm install complete")
    log("Building Messenger web client…")
    rc2, out2, err2 = run(
        ["npm", "run", "build:web"], cwd=messenger_dir, timeout=300
    )
    if rc2 != 0:
        log(f"  ! build:web failed (non-fatal): {err2.strip()[-200:]}")
    else:
        log("  ✓ Web client built")
    return True


def step_port_forwarding(cfg: dict, log) -> bool:
    if not cfg_bool(cfg, "ENABLE_PORT_FORWARDING", True):
        log("Skipping port forwarding (ENABLE_PORT_FORWARDING=false)")
        return True

    listen_addr = cfg.get("FORWARD_LISTEN_ADDRESS", "0.0.0.0")

    rules = []
    if cfg_bool(cfg, "FORWARD_MESSENGER", True):
        rules.append((
            cfg_int(cfg, "FORWARD_MESSENGER_EXT_PORT", 10006),
            cfg.get("FORWARD_MESSENGER_INT_IP", "127.0.0.1"),
            cfg_int(cfg, "FORWARD_MESSENGER_INT_PORT", 10006),
            "Messenger",
        ))
    if cfg_bool(cfg, "FORWARD_HOONBOT", True):
        rules.append((
            cfg_int(cfg, "FORWARD_HOONBOT_EXT_PORT", 3939),
            cfg.get("FORWARD_HOONBOT_INT_IP", "127.0.0.1"),
            cfg_int(cfg, "FORWARD_HOONBOT_INT_PORT", 3939),
            "Hoonbot",
        ))
    if cfg_bool(cfg, "FORWARD_LLM", False):
        rules.append((
            cfg_int(cfg, "FORWARD_LLM_EXT_PORT", 10007),
            cfg.get("FORWARD_LLM_INT_IP", "127.0.0.1"),
            cfg_int(cfg, "FORWARD_LLM_INT_PORT", 10007),
            "LLM API",
        ))

    if not rules:
        log("No port-forwarding rules enabled.")
        return True

    log(f"Configuring port forwarding (listen on {listen_addr})…")

    # Enable IP Helper service (required for portproxy)
    powershell("Set-Service -Name iphlpsvc -StartupType Automatic; Start-Service iphlpsvc")

    for ext_port, int_ip, int_port, label in rules:
        log(f"  {label}: {listen_addr}:{ext_port} → {int_ip}:{int_port}")
        # Delete existing rule first (idempotent)
        run(
            ["netsh", "interface", "portproxy", "delete", "v4tov4",
             f"listenaddress={listen_addr}", f"listenport={ext_port}"],
            shell=False,
        )
        rc, out, err = run(
            ["netsh", "interface", "portproxy", "add", "v4tov4",
             f"listenaddress={listen_addr}", f"listenport={ext_port}",
             f"connectaddress={int_ip}", f"connectport={int_port}"],
            shell=False,
        )
        if rc != 0:
            log(f"    ✗ netsh portproxy failed: {err.strip()}")
            return False

        # Firewall rule for inbound on the external port
        fw_name = f"AIhoonbot-{label.replace(' ', '')}-{ext_port}"
        powershell(
            f"Remove-NetFirewallRule -Name '{fw_name}' -ErrorAction SilentlyContinue; "
            f"New-NetFirewallRule -Name '{fw_name}' "
            f"-DisplayName 'AIhoonbot {label} (port {ext_port})' "
            f"-Direction Inbound -Protocol TCP -LocalPort {ext_port} -Action Allow"
        )
        log(f"    ✓ Firewall rule added for port {ext_port}")

    log("  ✓ Port forwarding configured")
    return True


def _create_shortcut(target: str, shortcut_path: str, description: str, icon: str = ""):
    """Create a Windows .lnk shortcut via PowerShell."""
    icon_line = f'$sc.IconLocation = "{icon}"' if icon else ""
    powershell(
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$sc = $ws.CreateShortcut("{shortcut_path}"); '
        f'$sc.TargetPath = "{target}"; '
        f'$sc.Description = "{description}"; '
        f'{icon_line} '
        f'$sc.Save()'
    )


def step_shortcuts(cfg: dict, log) -> bool:
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIhoonbot"))
    bat = str(install_dir / "start-all.bat")

    if cfg_bool(cfg, "CREATE_DESKTOP_SHORTCUT", True):
        desktop = Path(os.path.expanduser("~")) / "Desktop"
        lnk = str(desktop / "AIhoonbot.lnk")
        log(f"Creating desktop shortcut → {lnk}")
        _create_shortcut(bat, lnk, "Launch AIhoonbot services")
        log("  ✓ Desktop shortcut created")

    if cfg_bool(cfg, "CREATE_STARTMENU_SHORTCUT", True):
        sm = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "AIhoonbot"
        sm.mkdir(parents=True, exist_ok=True)
        lnk = str(sm / "AIhoonbot.lnk")
        log(f"Creating Start Menu shortcut → {lnk}")
        _create_shortcut(bat, lnk, "Launch AIhoonbot services")
        log("  ✓ Start Menu shortcut created")

    if cfg_bool(cfg, "ADD_TO_WINDOWS_STARTUP", False):
        log("Adding to Windows Startup…")
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, "AIhoonbot", 0, winreg.REG_SZ,
                              f'cmd /c "{bat}"')
            winreg.CloseKey(key)
            log("  ✓ Added to startup")
        except Exception as e:
            log(f"  ! Startup registry write failed: {e}")

    return True


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

STEPS = [
    ("Check / Install Python",     step_check_python),
    ("Check / Install Node.js",    step_check_node),
    ("Install OpenSSH",            step_install_ssh),
    ("Copy application files",     step_copy_files),
    ("Patch settings.txt",         step_write_settings),
    ("pip install (Hoonbot)",      step_pip_install),
    ("npm install (Messenger)",    step_npm_install),
    ("Configure port forwarding",  step_port_forwarding),
    ("Create shortcuts",           step_shortcuts),
]


class InstallerApp(tk.Tk):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.title("AIhoonbot.com — Installer")
        self.resizable(False, False)
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._running = False

    # ---- UI construction ----

    def _build_ui(self):
        BG = "#1a1a2e"
        ACCENT = "#e94560"
        FG = "#eaeaea"
        LOG_BG = "#0f0f1a"

        self.configure(bg=BG)

        # Header
        hdr = tk.Frame(self, bg=ACCENT, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="AIhoonbot.com", font=("Segoe UI", 20, "bold"),
                 bg=ACCENT, fg="white").pack()
        tk.Label(hdr, text="One-Click Installer",
                 font=("Segoe UI", 11), bg=ACCENT, fg="white").pack()

        # Install path display
        path_frame = tk.Frame(self, bg=BG, padx=20, pady=8)
        path_frame.pack(fill="x")
        tk.Label(path_frame, text="Install directory:", bg=BG, fg=FG,
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Label(path_frame, text=self.cfg.get("INSTALL_DIR", r"C:\AIhoonbot"),
                 bg=BG, fg=ACCENT, font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)

        # Step checklist
        steps_frame = tk.LabelFrame(self, text=" Installation Steps ",
                                    bg=BG, fg=FG, font=("Segoe UI", 9),
                                    bd=1, relief="groove", padx=16, pady=8)
        steps_frame.pack(fill="x", padx=20, pady=(4, 0))

        self._step_vars = []
        self._step_labels = []
        for label, _ in STEPS:
            var = tk.StringVar(value="○")
            row = tk.Frame(steps_frame, bg=BG)
            row.pack(fill="x", pady=1)
            icon_lbl = tk.Label(row, textvariable=var, bg=BG, fg="#888",
                                font=("Segoe UI", 10), width=2)
            icon_lbl.pack(side="left")
            text_lbl = tk.Label(row, text=label, bg=BG, fg="#aaa",
                                font=("Segoe UI", 9), anchor="w")
            text_lbl.pack(side="left")
            self._step_vars.append(var)
            self._step_labels.append((icon_lbl, text_lbl))

        # Progress bar
        prog_frame = tk.Frame(self, bg=BG, padx=20, pady=8)
        prog_frame.pack(fill="x")
        self._progress = ttk.Progressbar(prog_frame, length=460,
                                         mode="determinate", maximum=len(STEPS))
        self._progress.pack(fill="x")

        # Log output
        log_frame = tk.LabelFrame(self, text=" Log ", bg=BG, fg=FG,
                                  font=("Segoe UI", 9), bd=1, relief="groove",
                                  padx=10, pady=6)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(4, 8))
        self._log = scrolledtext.ScrolledText(
            log_frame, width=64, height=10, bg=LOG_BG, fg="#ccc",
            font=("Consolas", 8), state="disabled", bd=0,
        )
        self._log.pack(fill="both", expand=True)

        # Status label
        self._status_var = tk.StringVar(value="Ready to install.")
        tk.Label(self, textvariable=self._status_var, bg=BG, fg=FG,
                 font=("Segoe UI", 9)).pack(pady=(0, 4))

        # Buttons
        btn_frame = tk.Frame(self, bg=BG, pady=10)
        btn_frame.pack()
        self._install_btn = tk.Button(
            btn_frame, text="  Install  ", font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg="white", activebackground="#c73050",
            activeforeground="white", relief="flat", padx=20, pady=6,
            cursor="hand2", command=self._start_install,
        )
        self._install_btn.pack(side="left", padx=8)
        self._close_btn = tk.Button(
            btn_frame, text="  Close  ", font=("Segoe UI", 11),
            bg="#333", fg=FG, activebackground="#555",
            relief="flat", padx=20, pady=6,
            cursor="hand2", command=self._on_close,
        )
        self._close_btn.pack(side="left", padx=8)

        self.update_idletasks()
        # Centre on screen
        w, h = 520, 620
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ---- Helpers ----

    def _log_append(self, text: str):
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_step_state(self, index: int, state: str):
        """state: 'running' | 'ok' | 'fail' | 'skip'"""
        icons   = {"running": "▶", "ok": "✓", "fail": "✗", "skip": "–"}
        colours = {"running": "#f0c040", "ok": "#50e090", "fail": "#e05050", "skip": "#888"}
        var, (icon_lbl, text_lbl) = self._step_vars[index], self._step_labels[index]
        var.set(icons.get(state, "○"))
        icon_lbl.configure(fg=colours.get(state, "#888"))
        text_lbl.configure(fg="#eaeaea" if state in ("running", "ok") else "#888")

    # ---- Installation thread ----

    def _start_install(self):
        if self._running:
            return
        self._running = True
        self._install_btn.configure(state="disabled")
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _install_thread(self):
        def log(msg: str):
            self.after(0, self._log_append, msg)

        def set_step(i: int, state: str):
            self.after(0, self._set_step_state, i, state)

        def set_status(msg: str):
            self.after(0, self._status_var.set, msg)

        def advance_progress():
            self.after(0, lambda: self._progress.step(1))

        cfg = self.cfg
        all_ok = True

        for i, (label, fn) in enumerate(STEPS):
            set_step(i, "running")
            set_status(f"Step {i+1}/{len(STEPS)}: {label}…")
            log(f"\n[{i+1}/{len(STEPS)}] {label}")

            try:
                # Steps that need cfg pass it; steps that don't accept just log
                import inspect
                sig = inspect.signature(fn)
                if len(sig.parameters) == 2:
                    ok = fn(cfg, log)
                else:
                    ok = fn(log)
            except Exception as exc:
                log(f"  ✗ Unexpected error: {exc}")
                ok = False

            if ok:
                set_step(i, "ok")
            else:
                set_step(i, "fail")
                all_ok = False
                self.after(0, lambda lbl=label: messagebox.showerror(
                    "Installation failed",
                    f'Step "{lbl}" failed.\nCheck the log for details.'
                ))
                break

            advance_progress()

        if all_ok:
            set_status("Installation complete! ✓")
            log("\n✓ Installation finished successfully.")
            log(f"  Launch: {cfg.get('INSTALL_DIR', r'C:\\AIhoonbot')}\\start-all.bat")
            self.after(0, lambda: messagebox.showinfo(
                "Done",
                "AIhoonbot installed successfully!\n\n"
                f"Run start-all.bat in:\n{cfg.get('INSTALL_DIR', r'C:\\AIhoonbot')}"
            ))
        else:
            set_status("Installation failed — check the log.")

        self._running = False
        self.after(0, lambda: self._install_btn.configure(state="normal"))

    def _on_close(self):
        if self._running:
            if not messagebox.askyesno("Cancel?",
                                       "Installation is running. Abort anyway?"):
                return
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Must run as admin
    if not is_admin():
        elevate()
        return  # unreachable after elevate()

    # Locate installation_config.txt:
    # 1. Next to the .exe / script
    # 2. Bundled resource (fallback)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    config_candidates = [
        os.path.join(exe_dir, "installation_config.txt"),
        _resource("installation_config.txt"),
    ]
    cfg_path = next((p for p in config_candidates if os.path.exists(p)), None)

    cfg = {}
    if cfg_path:
        cfg = load_config(cfg_path)
    else:
        messagebox.showwarning(
            "Config not found",
            "installation_config.txt not found next to the installer.\n"
            "Proceeding with default values."
        )

    app = InstallerApp(cfg)
    app.mainloop()


if __name__ == "__main__":
    main()
