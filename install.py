#!/usr/bin/env python3
"""Rast-CLI one-shot installer.

Run this once to set up everything:
    python install.py

What it does:
  1. Checks Python >= 3.9
  2. Creates a virtual environment in .venv/
  3. Installs all dependencies
  4. Installs 'rash' as a global command in /usr/local/bin
  5. Optionally sets up a .env file with your keys
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
BIN = VENV / ("Scripts" if platform.system() == "Windows" else "bin")
PYTHON = BIN / ("python.exe" if platform.system() == "Windows" else "python")
PIP = BIN / ("pip.exe" if platform.system() == "Windows" else "pip")
GLOBAL_BIN = Path("/usr/local/bin")

BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def say(msg: str, color: str = "") -> None:
    print(f"{color}{msg}{RESET}")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def check_python() -> None:
    say("\n[1/5] Checking Python version...", CYAN)
    major, minor = sys.version_info[:2]
    if major < 3 or (major == 3 and minor < 9):
        say(f"  ERROR: Python 3.9+ required, found {major}.{minor}.", RED)
        sys.exit(1)
    say(f"  OK: Python {major}.{minor}", GREEN)


def create_venv() -> None:
    say("\n[2/5] Setting up virtual environment...", CYAN)
    if VENV.exists():
        say("  .venv already exists, skipping creation.", YELLOW)
    else:
        run([sys.executable, "-m", "venv", str(VENV)])
        say("  Created .venv/", GREEN)


def install_deps() -> None:
    say("\n[3/5] Installing dependencies...", CYAN)
    run([str(PIP), "install", "--quiet", "--upgrade", "pip"])
    run([str(PIP), "install", "--quiet", "-e", str(HERE)])
    say("  Dependencies installed.", GREEN)


def install_command() -> None:
    say("\n[4/5] Installing 'rash' command...", CYAN)
    rash_src = BIN / "rash"
    if not rash_src.exists():
        say(f"  ERROR: {rash_src} not found. Did pip install succeed?", RED)
        sys.exit(1)

    if platform.system() == "Windows":
        say("  Windows detected: add this folder to PATH manually:", YELLOW)
        say(f"    {BIN}", YELLOW)
        say("  Or run directly: .venv\\Scripts\\rash.exe", YELLOW)
        return

    target = GLOBAL_BIN / "rash"
    try:
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(rash_src)
        say(f"  Linked {rash_src} → {target}", GREEN)
    except PermissionError:
        say("  Permission denied. Trying with sudo...", YELLOW)
        try:
            subprocess.run(
                ["sudo", "ln", "-sf", str(rash_src), str(target)],
                check=True,
            )
            say(f"  Linked (via sudo): {target}", GREEN)
        except subprocess.CalledProcessError:
            say("  Could not install globally. You can still run:", YELLOW)
            say(f"    source .venv/bin/activate && rash", YELLOW)


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

    say("\n  Optional: add your keys to .env now.", YELLOW)
    say("  (Press Enter to skip any key)", YELLOW)

    keys: dict[str, str] = {}

    try:
        val = input(f"\n  OpenRouter API key (for cloud models): ").strip()
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
        lines = []
        if env_file.exists():
            existing = env_file.read_text(encoding="utf-8")
            lines = existing.splitlines()

        for k, v in keys.items():
            line = f"{k}={v}"
            lines = [l for l in lines if not l.startswith(f"{k}=")]
            lines.append(line)

        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        say(f"  Saved {len(keys)} key(s) to .env", GREEN)


def print_summary() -> None:
    say(f"\n{BOLD}{'='*50}{RESET}")
    say(f"{BOLD}{GREEN}  Rast-CLI installed successfully!{RESET}")
    say(f"{BOLD}{'='*50}{RESET}\n")
    say("  Run from anywhere:    rash", CYAN)
    say("  With provider:        rash --provider openrouter", CYAN)
    say("  With model:           rash -p openrouter -m deepseek/deepseek-r1", CYAN)
    say("\n  First-time setup inside rash:", CYAN)
    say("    /connect github ghp_yourToken", CYAN)
    say("    /connect gmail ya29.yourToken", CYAN)
    say("    /key sk-or-v1-yourOpenRouterKey", CYAN)
    say("\n  Type /help for all commands.\n", CYAN)


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
