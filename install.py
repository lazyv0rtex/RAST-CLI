#!/usr/bin/env python3
"""Rast-CLI one-shot installer — works on macOS, Linux, and Windows.

Usage:
    python install.py

What it does:
  1. Checks Python >= 3.9
  2. Creates a virtual environment in .venv/
  3. Installs all dependencies
  4. Makes 'rast' available globally (no sudo needed)
  5. Optionally sets up a .env file with your API keys
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
VENV = HERE / ".venv"
IS_WINDOWS = platform.system() == "Windows"
BIN = VENV / ("Scripts" if IS_WINDOWS else "bin")
RAST_EXE = BIN / ("rast.exe" if IS_WINDOWS else "rast")
PIP = BIN / ("pip.exe" if IS_WINDOWS else "pip")

BOLD  = "" if IS_WINDOWS else "\033[1m"
CYAN  = "" if IS_WINDOWS else "\033[36m"
GREEN = "" if IS_WINDOWS else "\033[32m"
YELLOW= "" if IS_WINDOWS else "\033[33m"
RED   = "" if IS_WINDOWS else "\033[31m"
RESET = "" if IS_WINDOWS else "\033[0m"


def say(msg: str, color: str = "") -> None:
    print(f"{color}{msg}{RESET}", flush=True)


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


# ── Step 1 ────────────────────────────────────────────────────────────────────
def check_python() -> None:
    say("\n[1/5] Checking Python version...", CYAN)
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 9):
        say(f"  ERROR: Python 3.9+ required, found {major}.{minor}.", RED)
        sys.exit(1)
    say(f"  OK: Python {major}.{minor}", GREEN)


# ── Step 2 ────────────────────────────────────────────────────────────────────
def create_venv() -> None:
    say("\n[2/5] Setting up virtual environment...", CYAN)
    # If .venv exists but pip is missing, the venv is broken — rebuild it.
    if VENV.exists() and not PIP.exists():
        say("  Existing .venv is broken, removing...", YELLOW)
        shutil.rmtree(VENV)
    if VENV.exists():
        say("  .venv already exists, skipping creation.", YELLOW)
    else:
        run([sys.executable, "-m", "venv", str(VENV)])
        say("  Created .venv/", GREEN)


# ── Step 3 ────────────────────────────────────────────────────────────────────
def install_deps() -> None:
    say("\n[3/5] Installing dependencies...", CYAN)
    run([str(PIP), "install", "--quiet", "--upgrade", "pip"])
    run([str(PIP), "install", "--quiet", "-e", str(HERE)])
    say("  Dependencies installed.", GREEN)


# ── Step 4 ────────────────────────────────────────────────────────────────────
def install_command() -> None:
    say("\n[4/5] Installing 'rast' command...", CYAN)

    if not RAST_EXE.exists():
        say(f"  ERROR: {RAST_EXE} not found after install.", RED)
        sys.exit(1)

    if IS_WINDOWS:
        _install_windows()
    else:
        _install_unix()


def _install_unix() -> None:
    """Try three strategies in order: /usr/local/bin symlink, ~/.local/bin, PATH export."""
    # Strategy 1: /usr/local/bin (needs write permission or sudo)
    global_bin = Path("/usr/local/bin")
    target = global_bin / "rast"
    if global_bin.exists():
        try:
            if target.exists() or target.is_symlink():
                target.unlink()
            target.symlink_to(RAST_EXE)
            say(f"  Linked: {RAST_EXE} → {target}", GREEN)
            return
        except PermissionError:
            pass
        # Try with sudo silently
        r = subprocess.run(
            ["sudo", "-n", "ln", "-sf", str(RAST_EXE), str(target)],
            capture_output=True,
        )
        if r.returncode == 0:
            say(f"  Linked (sudo): {target}", GREEN)
            return

    # Strategy 2: ~/.local/bin (no permissions needed, standard on Linux)
    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    target2 = local_bin / "rast"
    try:
        if target2.exists() or target2.is_symlink():
            target2.unlink()
        target2.symlink_to(RAST_EXE)
        say(f"  Linked: {RAST_EXE} → {target2}", GREEN)
        _ensure_in_path(local_bin)
        return
    except OSError:
        pass

    # Strategy 3: Write a wrapper script to ~/bin and add to PATH
    home_bin = Path.home() / "bin"
    home_bin.mkdir(parents=True, exist_ok=True)
    wrapper = home_bin / "rast"
    wrapper.write_text(
        f'#!/bin/sh\nexec "{RAST_EXE}" "$@"\n', encoding="utf-8"
    )
    wrapper.chmod(0o755)
    say(f"  Installed wrapper: {wrapper}", GREEN)
    _ensure_in_path(home_bin)


def _ensure_in_path(bin_dir: Path) -> None:
    """Add bin_dir to PATH in the user's shell profile if not already there."""
    bin_str = str(bin_dir)
    current_path = os.environ.get("PATH", "")
    if bin_str in current_path.split(os.pathsep):
        return  # Already in PATH for this session

    export_line = f'\nexport PATH="{bin_str}:$PATH"  # added by rast installer\n'
    # Detect shell and pick the right profile file
    shell = os.environ.get("SHELL", "")
    candidates = []
    if "zsh" in shell:
        candidates = [Path.home() / ".zshrc", Path.home() / ".zprofile"]
    elif "bash" in shell:
        candidates = [
            Path.home() / ".bashrc",
            Path.home() / ".bash_profile",
            Path.home() / ".profile",
        ]
    else:
        candidates = [Path.home() / ".profile"]

    for profile in candidates:
        try:
            existing = profile.read_text(encoding="utf-8") if profile.exists() else ""
            if bin_str in existing:
                say(f"  PATH already set in {profile.name}", GREEN)
                return
            with open(profile, "a", encoding="utf-8") as f:
                f.write(export_line)
            say(f"  Added to PATH in {profile}", GREEN)
            say(f"  Run: source {profile}  (or open a new terminal)", YELLOW)
            return
        except OSError:
            continue

    say(f"  Could not update shell profile. Add this to your shell config:", YELLOW)
    say(f'    export PATH="{bin_str}:$PATH"', YELLOW)


def _install_windows() -> None:
    """Add the venv Scripts dir to the user's PATH via the Windows registry."""
    bin_str = str(BIN)
    # Try adding to user PATH via registry (no admin needed)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
        try:
            current, _ = winreg.QueryValueEx(key, "PATH")
        except FileNotFoundError:
            current = ""
        if bin_str not in current.split(";"):
            new_path = f"{current};{bin_str}" if current else bin_str
            winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
            say(f"  Added to user PATH: {bin_str}", GREEN)
            say("  Open a new terminal for PATH to take effect.", YELLOW)
        else:
            say(f"  Already in PATH: {bin_str}", GREEN)
        winreg.CloseKey(key)
        # Broadcast WM_SETTINGCHANGE so Explorer picks up new PATH without reboot
        try:
            import ctypes
            ctypes.windll.user32.SendMessageTimeoutW(
                0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None
            )
        except Exception:
            pass
    except Exception as exc:
        say(f"  Could not update registry: {exc}", YELLOW)
        say(f"  Manually add to PATH: {bin_str}", YELLOW)
        say(f"  Or run directly: {RAST_EXE}", YELLOW)


# ── Step 5 ────────────────────────────────────────────────────────────────────
def setup_env() -> None:
    say("\n[5/5] Environment setup...", CYAN)
    env_file = HERE / ".env"
    example = HERE / ".env.example"

    if env_file.exists():
        say("  .env already exists, skipping.", YELLOW)
        return

    if example.exists():
        shutil.copy(example, env_file)
        say("  Created .env from .env.example", GREEN)

    say("\n  Optional: add your API keys now.", YELLOW)
    say("  (Press Enter to skip any key)", YELLOW)

    keys: dict = {}
    try:
        val = input("\n  OpenRouter API key (for cloud models): ").strip()
        if val:
            keys["OPENROUTER_API_KEY"] = val
        val = input("  GitHub Personal Access Token: ").strip()
        if val:
            keys["GITHUB_TOKEN"] = val
        val = input("  Gmail Access Token (optional, expires hourly): ").strip()
        if val:
            keys["GMAIL_ACCESS_TOKEN"] = val
    except (EOFError, KeyboardInterrupt):
        say("\n  Skipping key setup.", YELLOW)

    if keys:
        lines: list = []
        if env_file.exists():
            lines = env_file.read_text(encoding="utf-8").splitlines()
        for k, v in keys.items():
            lines = [l for l in lines if not l.startswith(f"{k}=")]
            lines.append(f"{k}={v}")
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        say(f"  Saved {len(keys)} key(s) to .env", GREEN)


# ── Summary ───────────────────────────────────────────────────────────────────
def print_summary() -> None:
    say(f"\n{BOLD}{'='*50}{RESET}")
    say(f"{BOLD}{GREEN}  Rast-CLI installed successfully!{RESET}")
    say(f"{BOLD}{'='*50}{RESET}\n")
    say("  Run from anywhere:    rast", CYAN)
    say("  With provider:        rast --provider openrouter", CYAN)
    say("  With model:           rast -p openrouter -m deepseek/deepseek-r1", CYAN)
    say("\n  First-time setup inside rast:", CYAN)
    say("    /connect github ghp_yourToken", CYAN)
    say("    /connect gmail ya29.yourToken", CYAN)
    say("    /key sk-or-v1-yourOpenRouterKey", CYAN)
    say("\n  Type /help for all commands.\n", CYAN)
    if IS_WINDOWS:
        say("  NOTE: Open a new terminal window for 'rast' to be available.", YELLOW)


def main() -> None:
    say(f"\n{BOLD}Rast-CLI Installer{RESET}")
    say("=" * 40)
    check_python()
    create_venv()
    install_deps()
    install_command()
    setup_env()
    print_summary()


if __name__ == "__main__":
    main()
