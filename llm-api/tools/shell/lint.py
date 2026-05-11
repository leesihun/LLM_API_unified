"""ShellLintTool: static analysis for .ps1 (PSScriptAnalyzer) and .sh (shellcheck/bash -n)."""
import json
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict


_MAX_FINDINGS = 50
_TIMEOUT = 30


class ShellLintTool:
    """Run PSScriptAnalyzer (Windows) or shellcheck/bash -n (Unix) on a shell script."""

    def lint(self, path: str) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            return {"success": False, "error": f"File not found: {path}"}

        ext = p.suffix.lower()
        is_windows = platform.system() == "Windows"

        if ext == ".ps1":
            return self._lint_ps1(p, is_windows)
        elif ext in (".sh", ".bash"):
            return self._lint_sh(p, is_windows)
        else:
            # Generic: try bash -n on unix; PSParser on windows
            if is_windows:
                return self._lint_ps1(p, is_windows)
            return self._lint_sh(p, is_windows)

    # ------------------------------------------------------------------ #
    # PowerShell linting
    # ------------------------------------------------------------------ #

    def _lint_ps1(self, path: Path, is_windows: bool) -> Dict[str, Any]:
        # Prefer PSScriptAnalyzer (gives rule names + severity)
        psa_result = self._try_psscriptanalyzer(path, is_windows)
        if psa_result is not None:
            return psa_result

        # Fallback: PSParser syntax-only check (always available if pwsh/powershell exists)
        return self._try_psparser(path, is_windows)

    def _try_psscriptanalyzer(self, path: Path, is_windows: bool) -> Dict[str, Any]:
        shell_exe = "powershell.exe" if is_windows else "pwsh"
        ps_code = (
            f"$results = Invoke-ScriptAnalyzer -Path '{path}' -Severity Error,Warning 2>$null; "
            f"$results | ForEach-Object {{ "
            f"\"$($_.ScriptName):$($_.Line):$($_.Severity):$($_.RuleName):$($_.Message)\" }}"
        )
        try:
            proc = subprocess.run(
                [shell_exe, "-NoProfile", "-NonInteractive", "-Command", ps_code],
                capture_output=True, text=True, timeout=_TIMEOUT,
            )
            # If PSScriptAnalyzer is not installed, stdout is empty and no crash
            if proc.returncode not in (0, 1):
                return None
            lines = [l for l in proc.stdout.splitlines() if l.strip()]
            if not lines and proc.returncode != 0:
                return None
            return self._format_result(path, lines, "PSScriptAnalyzer")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _try_psparser(self, path: Path, is_windows: bool) -> Dict[str, Any]:
        shell_exe = "powershell.exe" if is_windows else "pwsh"
        ps_code = (
            f"$errors = $null; "
            f"[void][System.Management.Automation.PSParser]::Tokenize("
            f"(Get-Content -Raw '{path}'), [ref]$errors); "
            f"$errors | ForEach-Object {{ "
            f"'{path}:' + $_.Token.StartLine + ':Error:Syntax:' + $_.Message }}"
        )
        try:
            proc = subprocess.run(
                [shell_exe, "-NoProfile", "-NonInteractive", "-Command", ps_code],
                capture_output=True, text=True, timeout=_TIMEOUT,
            )
            lines = [l for l in proc.stdout.splitlines() if l.strip()]
            return self._format_result(path, lines, "PSParser")
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"success": False, "error": f"No PowerShell linter available: {e}"}

    # ------------------------------------------------------------------ #
    # Bash / sh linting
    # ------------------------------------------------------------------ #

    def _lint_sh(self, path: Path, is_windows: bool) -> Dict[str, Any]:
        # Prefer shellcheck — richer output
        sc_result = self._try_shellcheck(path)
        if sc_result is not None:
            return sc_result
        # Fallback: bash -n (syntax only)
        return self._try_bash_n(path)

    def _try_shellcheck(self, path: Path) -> Dict[str, Any]:
        try:
            proc = subprocess.run(
                ["shellcheck", "-f", "json", str(path)],
                capture_output=True, text=True, timeout=_TIMEOUT,
            )
            data = json.loads(proc.stdout or "[]")
            lines = []
            for item in data[:_MAX_FINDINGS]:
                severity = item.get("level", "warning").capitalize()
                rule = item.get("code", "")
                msg = item.get("message", "")
                line_no = item.get("line", 0)
                lines.append(f"{path}:{line_no}:{severity}:SC{rule}:{msg}")
            return self._format_result(path, lines, "shellcheck")
        except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
            return None

    def _try_bash_n(self, path: Path) -> Dict[str, Any]:
        try:
            proc = subprocess.run(
                ["bash", "-n", str(path)],
                capture_output=True, text=True, timeout=_TIMEOUT,
            )
            lines = [l for l in proc.stderr.splitlines() if l.strip()]
            return self._format_result(path, lines, "bash -n")
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {"success": False, "error": f"No shell linter available: {e}"}

    # ------------------------------------------------------------------ #
    # Format helper
    # ------------------------------------------------------------------ #

    def _format_result(self, path: Path, findings: list, linter: str) -> Dict[str, Any]:
        capped = findings[:_MAX_FINDINGS]
        if not capped:
            return {
                "success": True,
                "clean": True,
                "linter": linter,
                "message": f"No issues found in {path.name}",
                "findings": [],
            }
        return {
            "success": True,
            "clean": False,
            "linter": linter,
            "findings_count": len(findings),
            "findings": capped,
            "message": (
                f"{len(findings)} issue(s) found. Fix all, then run shell_lint again "
                f"to confirm clean before shell_exec."
            ),
        }
