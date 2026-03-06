"""
AIBotMessenger - Windows One-Click Installer
=============================================
Bundled by build_installer.py via PyInstaller.
Launches as Administrator (self-elevates via UAC if needed).
"""

import sys
import os
import re
import shutil
import subprocess
import ctypes
import winreg
from pathlib import Path

# ---------------------------------------------------------------------------
# Resource path (works both frozen and unfrozen)
# ---------------------------------------------------------------------------

def _resource(relative):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


# ---------------------------------------------------------------------------
# Config reader
# ---------------------------------------------------------------------------

def load_config(path):
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


def cfg_bool(cfg, key, default=False):
    return cfg.get(key, str(default)).lower() in ("true", "1", "yes")


def cfg_int(cfg, key, default=0):
    try:
        return int(cfg.get(key, default))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# UAC self-elevation
# ---------------------------------------------------------------------------

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def elevate():
    params = " ".join('"' + a + '"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Low-level utilities
# ---------------------------------------------------------------------------

def run_cmd(cmd, cwd=None, shell=False, timeout=600):
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, shell=shell, capture_output=True,
            text=True, timeout=timeout, encoding="utf-8", errors="replace",
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timed out"
    except Exception as e:
        return -1, "", str(e)


def powershell(script, timeout=300):
    return run_cmd(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
    )


def refresh_path():
    """Pull the current machine+user PATH into this process."""
    try:
        new_path = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "[System.Environment]::GetEnvironmentVariable('PATH','Machine') + ';' + "
             "[System.Environment]::GetEnvironmentVariable('PATH','User')"],
            text=True, encoding="utf-8", errors="replace",
        ).strip()
        os.environ["PATH"] = new_path
    except Exception:
        pass


def winget_install(pkg_id, name, log):
    log("  Installing " + name + " via winget...")
    rc, out, err = run_cmd(
        ["winget", "install", "--id", pkg_id, "-e",
         "--accept-package-agreements", "--accept-source-agreements", "--silent"],
        timeout=300,
    )
    combined = (out + err).lower()
    if rc == 0 or "already installed" in combined or rc == -1879048149:
        log("  [ok] " + name + " installed")
        return True
    log("  [fail] winget failed (rc=" + str(rc) + "): " + (err or out).strip()[-200:])
    return False


# ---------------------------------------------------------------------------
# Installation steps  (all accept cfg, log for consistency)
# ---------------------------------------------------------------------------

def step_check_python(cfg, log):
    log("Checking Python...")
    for cmd in (["python", "--version"], ["py", "--version"]):
        rc, out, _ = run_cmd(cmd)
        if rc == 0:
            log("  [ok] Found: " + out.strip())
            return True
    log("  Python not found - installing via winget...")
    ok = winget_install("Python.Python.3.11", "Python 3.11", log)
    refresh_path()
    return ok


def step_check_node(cfg, log):
    log("Checking Node.js...")
    rc, out, _ = run_cmd("node --version", shell=True)
    if rc == 0:
        log("  [ok] Node.js: " + out.strip())
    else:
        log("  Node.js not found - installing via winget...")
        if not winget_install("OpenJS.NodeJS.LTS", "Node.js LTS", log):
            return False
        refresh_path()

    log("Checking npm...")
    rc2, out2, _ = run_cmd("npm --version", shell=True)
    if rc2 == 0:
        log("  [ok] npm: " + out2.strip())
        return True

    # npm not found even after Node install — try refreshing PATH once more
    refresh_path()
    rc3, out3, _ = run_cmd("npm --version", shell=True)
    if rc3 == 0:
        log("  [ok] npm: " + out3.strip())
        return True

    log("  npm not found - installing via winget...")
    ok = winget_install("OpenJS.NodeJS.LTS", "Node.js LTS (retry)", log)
    refresh_path()
    return ok


def step_install_ssh(cfg, log):
    if not cfg_bool(cfg, "INSTALL_SSH", True):
        log("Skipping SSH (INSTALL_SSH=false)")
        return True

    ssh_port = cfg_int(cfg, "SSH_PORT", 22)
    log("Checking OpenSSH Server...")

    rc, out, _ = powershell(
        "Get-WindowsCapability -Online -Name OpenSSH.Server* "
        "| Select-Object -ExpandProperty State"
    )
    if rc == 0 and "installed" in out.lower():
        log("  [ok] OpenSSH Server already installed")
    else:
        log("  Installing OpenSSH Server...")
        rc2, _, err2 = powershell(
            "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0",
            timeout=180,
        )
        if rc2 != 0:
            log("  Windows feature install failed: " + err2.strip()[-150:])
            log("  Falling back to winget...")
            winget_install("Microsoft.OpenSSH.Beta", "OpenSSH", log)

    powershell("Start-Service sshd -ErrorAction SilentlyContinue")
    powershell("Set-Service -Name sshd -StartupType Automatic")

    if ssh_port != 22:
        log("  Setting SSH port to " + str(ssh_port) + "...")
        cfg_path = r"C:\ProgramData\ssh\sshd_config"
        powershell(
            "(Get-Content '" + cfg_path + "') -replace '#?Port 22', 'Port " +
            str(ssh_port) + "' | Set-Content '" + cfg_path + "'"
        )
        powershell("Restart-Service sshd")

    log("  Adding firewall rule for SSH port " + str(ssh_port) + "...")
    powershell(
        "New-NetFirewallRule -Name 'AIBotMessenger-SSH' "
        "-DisplayName 'AIBotMessenger SSH' "
        "-Direction Inbound -Protocol TCP -LocalPort " + str(ssh_port) +
        " -Action Allow -ErrorAction SilentlyContinue"
    )
    log("  [ok] SSH configured")
    return True


def step_copy_files(cfg, log):
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIBotMessenger"))
    log("Installing to " + str(install_dir) + "...")
    install_dir.mkdir(parents=True, exist_ok=True)

    for component in ("Hoonbot", "Messenger"):
        src = Path(_resource(component))
        dst = install_dir / component
        if not src.exists():
            log("  [fail] Bundled source for " + component + " not found at " + str(src))
            return False
        log("  Copying " + component + "...")
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        log("  [ok] " + component + " copied")

    settings_src = Path(_resource("settings.txt"))
    settings_dst = install_dir / "settings.txt"
    if settings_src.exists() and not settings_dst.exists():
        shutil.copy2(settings_src, settings_dst)

    messenger_port = cfg_int(cfg, "MESSENGER_PORT", 10006)
    hoonbot_port = cfg_int(cfg, "HOONBOT_PORT", 3939)

    bat = install_dir / "start-all.bat"
    bat.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul 2>&1\r\n"
        "title AIBotMessenger\r\n"
        "echo Starting Messenger...\r\n"
        'start "Messenger" cmd /k "cd /d "%~dp0Messenger" && npm run dev:server"\r\n'
        "timeout /t 3 /nobreak >nul\r\n"
        "echo Starting Hoonbot...\r\n"
        'start "Hoonbot" cmd /k "cd /d "%~dp0Hoonbot" && python hoonbot.py"\r\n'
        "echo.\r\n"
        "echo All services started.\r\n"
        "echo   Messenger : http://localhost:" + str(messenger_port) + "\r\n"
        "echo   Hoonbot   : http://localhost:" + str(hoonbot_port) + "\r\n"
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

    log("  [ok] Files installed")
    return True


def step_write_settings(cfg, log):
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIBotMessenger"))
    settings_path = install_dir / "settings.txt"
    if not settings_path.exists():
        log("  settings.txt not found, skipping patch")
        return True

    log("Patching settings.txt...")
    text = settings_path.read_text(encoding="utf-8")

    patches = {
        "MESSENGER_PORT":       cfg.get("MESSENGER_PORT", "10006"),
        "HOONBOT_PORT":         cfg.get("HOONBOT_PORT", "3939"),
        "LLM_API_PORT":         cfg.get("LLM_API_PORT", "10007"),
        "HOONBOT_BOT_NAME":     cfg.get("BOT_NAME", "Bot"),
        "HOONBOT_HOME_ROOM_ID": cfg.get("HOME_ROOM_ID", "1"),
        "HOONBOT_LLM_USERNAME": cfg.get("LLM_USERNAME", "admin"),
        "HOONBOT_LLM_PASSWORD": cfg.get("LLM_PASSWORD", "administrator"),
    }
    for key, value in patches.items():
        text = re.sub(r'^(' + key + r')=.*$', key + '=' + value, text, flags=re.MULTILINE)

    llm_url = cfg.get("LLM_API_URL", "").strip()
    if llm_url:
        if "LLM_API_URL=" in text:
            text = re.sub(r'^#?\s*LLM_API_URL=.*$', 'LLM_API_URL=' + llm_url,
                          text, flags=re.MULTILINE)
        else:
            text += '\nLLM_API_URL=' + llm_url + '\n'

    settings_path.write_text(text, encoding="utf-8")
    log("  [ok] settings.txt patched")
    return True


def step_pip_install(cfg, log):
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIBotMessenger"))
    req = install_dir / "Hoonbot" / "requirements.txt"
    if not req.exists():
        log("  requirements.txt not found, skipping")
        return True
    log("Installing Python dependencies...")
    for py_cmd in ("python", "py"):
        rc, out, err = run_cmd(
            [py_cmd, "-m", "pip", "install", "-r", str(req), "--quiet"],
            timeout=300,
        )
        if rc == 0:
            log("  [ok] Python dependencies installed")
            return True
        if "not recognized" not in err.lower() and "not found" not in err.lower():
            log("  [fail] pip error: " + (err or out).strip()[-300:])
            return False
    log("  [fail] python executable not found after install")
    return False


def _npm_configure_ssl(log):
    """
    Configure npm SSL.  On networks with corporate TLS inspection the default
    strict-ssl setting causes install failures.  We try the corporate cert
    first; if that is not present we fall back to disabling strict-ssl.
    """
    corp_cert = r"C:\DigitalCity.crt"
    if os.path.exists(corp_cert):
        log("  Configuring npm to use corporate CA cert (" + corp_cert + ")...")
        run_cmd('npm config set cafile "' + corp_cert + '"', shell=True)
    else:
        log("  Disabling npm strict-ssl (corporate proxy detected)...")
        run_cmd("npm config set strict-ssl false", shell=True)


def step_npm_install(cfg, log):
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIBotMessenger"))
    messenger_dir = str(install_dir / "Messenger")
    refresh_path()
    _npm_configure_ssl(log)
    log("Running npm install...")
    # npm is a .cmd file on Windows — must use shell=True
    rc, out, err = run_cmd("npm install", cwd=messenger_dir, shell=True, timeout=300)
    if rc != 0:
        log("  [fail] npm install: " + (err or out).strip()[-300:])
        return False
    log("  [ok] npm install complete")
    log("Building Messenger web client...")
    rc2, out2, err2 = run_cmd("npm run build:web", cwd=messenger_dir, shell=True, timeout=300)
    if rc2 != 0:
        log("  [warn] build:web failed (non-fatal): " + (err2 or out2).strip()[-200:])
    else:
        log("  [ok] Web client built")
    return True


def step_port_forwarding(cfg, log):
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

    log("Configuring port forwarding (listen on " + listen_addr + ")...")
    powershell("Set-Service -Name iphlpsvc -StartupType Automatic; Start-Service iphlpsvc")

    for ext_port, int_ip, int_port, label in rules:
        log("  " + label + ": " + listen_addr + ":" + str(ext_port) +
            " -> " + int_ip + ":" + str(int_port))
        run_cmd(["netsh", "interface", "portproxy", "delete", "v4tov4",
                 "listenaddress=" + listen_addr, "listenport=" + str(ext_port)])
        rc, out, err = run_cmd(
            ["netsh", "interface", "portproxy", "add", "v4tov4",
             "listenaddress=" + listen_addr, "listenport=" + str(ext_port),
             "connectaddress=" + int_ip, "connectport=" + str(int_port)],
        )
        if rc != 0:
            log("    [fail] netsh: " + (err or out).strip())
            return False

        fw_name = "AIBotMessenger-" + label.replace(" ", "") + "-" + str(ext_port)
        powershell(
            "Remove-NetFirewallRule -Name '" + fw_name + "' -ErrorAction SilentlyContinue; "
            "New-NetFirewallRule -Name '" + fw_name + "' "
            "-DisplayName 'AIBotMessenger " + label + " (port " + str(ext_port) + ")' "
            "-Direction Inbound -Protocol TCP -LocalPort " + str(ext_port) + " -Action Allow"
        )
        log("    [ok] Firewall rule added for port " + str(ext_port))

    log("  [ok] Port forwarding configured")
    return True


def _create_shortcut(target, shortcut_path, description):
    powershell(
        "$ws = New-Object -ComObject WScript.Shell; "
        "$sc = $ws.CreateShortcut('" + shortcut_path + "'); "
        "$sc.TargetPath = '" + target + "'; "
        "$sc.Description = '" + description + "'; "
        "$sc.Save()"
    )


def step_shortcuts(cfg, log):
    install_dir = Path(cfg.get("INSTALL_DIR", r"C:\AIBotMessenger"))
    bat = str(install_dir / "start-all.bat")

    if cfg_bool(cfg, "CREATE_DESKTOP_SHORTCUT", True):
        desktop = Path(os.path.expanduser("~")) / "Desktop"
        lnk = str(desktop / "AIBotMessenger.lnk")
        log("Creating desktop shortcut...")
        _create_shortcut(bat, lnk, "Launch AIBotMessenger services")
        log("  [ok] Desktop shortcut: " + lnk)

    if cfg_bool(cfg, "CREATE_STARTMENU_SHORTCUT", True):
        sm = (Path(os.environ.get("APPDATA", "")) /
              "Microsoft" / "Windows" / "Start Menu" / "Programs" / "AIBotMessenger")
        sm.mkdir(parents=True, exist_ok=True)
        lnk = str(sm / "AIBotMessenger.lnk")
        log("Creating Start Menu shortcut...")
        _create_shortcut(bat, lnk, "Launch AIBotMessenger services")
        log("  [ok] Start Menu shortcut created")

    if cfg_bool(cfg, "ADD_TO_WINDOWS_STARTUP", False):
        log("Adding to Windows Startup...")
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, "AIBotMessenger", 0, winreg.REG_SZ, 'cmd /c "' + bat + '"')
            winreg.CloseKey(key)
            log("  [ok] Added to startup")
        except Exception as e:
            log("  [warn] Startup registry write failed: " + str(e))

    return True


# ---------------------------------------------------------------------------
# Step registry
# ---------------------------------------------------------------------------

STEPS = [
    ("Check / Install Python",    step_check_python),
    ("Check / Install Node.js",   step_check_node),
    ("Install OpenSSH",           step_install_ssh),
    ("Copy application files",    step_copy_files),
    ("Patch settings.txt",        step_write_settings),
    ("pip install (Hoonbot)",     step_pip_install),
    ("npm install (Messenger)",   step_npm_install),
    ("Configure port forwarding", step_port_forwarding),
    ("Create shortcuts",          step_shortcuts),
]


# ---------------------------------------------------------------------------
# Console runner
# ---------------------------------------------------------------------------

def run_console(cfg):
    install_dir = cfg.get("INSTALL_DIR", r"C:\AIBotMessenger")
    total = len(STEPS)

    print("=" * 60)
    print("  AIBotMessenger - One-Click Installer")
    print("  Install directory: " + install_dir)
    print("=" * 60)
    print()

    def log(msg):
        print(msg)

    for i, (label, fn) in enumerate(STEPS):
        print("[" + str(i + 1) + "/" + str(total) + "] " + label + " ...")
        try:
            ok = fn(cfg, log)
        except Exception as exc:
            import traceback
            print("  [fail] Unexpected error: " + str(exc))
            traceback.print_exc()
            ok = False

        if not ok:
            print()
            print("=" * 60)
            print("  INSTALLATION FAILED at step: " + label)
            print("  Check the output above for details.")
            print("=" * 60)
            input("\nPress Enter to close...")
            sys.exit(1)

        print()

    print("=" * 60)
    print("  Installation complete!")
    print("  Run start-all.bat in: " + install_dir)
    print("=" * 60)
    input("\nPress Enter to close...")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not is_admin():
        elevate()
        return

    exe_dir = os.path.dirname(
        os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)
    )
    config_candidates = [
        os.path.join(exe_dir, "installation_config.txt"),
        _resource("installation_config.txt"),
    ]
    cfg_path = next((p for p in config_candidates if os.path.exists(p)), None)
    cfg = load_config(cfg_path) if cfg_path else {}

    if not cfg_path:
        print("WARNING: installation_config.txt not found. Using default values.")
        print()

    run_console(cfg)


if __name__ == "__main__":
    main()
