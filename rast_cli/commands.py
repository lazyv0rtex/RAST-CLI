"""Slash-command handling for the interactive prompt."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from . import ui
from .config import PRESET_MODELS, VALID_PROVIDERS, VALID_THINKING

if TYPE_CHECKING:
    from .agent import Agent
    from .config import Config

HELP_TEXT = """\
[bold]Rast-CLI commands[/bold]

  [cyan]/help[/cyan]                             Show this help
  [cyan]/status[/cyan]                           Show current provider / model / settings
  [cyan]/models[/cyan]                           List + interactively pick a model from the provider
  [cyan]/presets[/cyan]                          Show curated model list for the active provider
  [cyan]/use <model>[/cyan]                      Quick model switch (shorthand for /settings model)
  [cyan]/history[/cyan]                          Show conversation turn count and token usage
  [cyan]/compact[/cyan]                          Summarise and compress the conversation context
  [cyan]/save [file][/cyan]                      Save conversation to a JSON file
  [cyan]/load <file>[/cyan]                      Load a previously saved conversation
  [cyan]/clear[/cyan]                            Clear conversation history
  [cyan]/key <openrouter-api-key>[/cyan]         Set the OpenRouter API key for this session
  [cyan]/credits[/cyan]                           Show OpenRouter account credit balance
  [cyan]/update[/cyan]                             Check for updates and apply them automatically
  [cyan]/integrations[/cyan]                       Show connected integrations (GitHub, Gmail)
  [cyan]/connect github <token>[/cyan]             Link your GitHub account
  [cyan]/connect gmail <token>[/cyan]              Link your Gmail account
  [cyan]/disconnect <service>[/cyan]               Remove an integration for this session
  [cyan]/exit[/cyan], [cyan]/quit[/cyan]                 Leave Rast-CLI

[bold]Settings[/bold]

  [cyan]/settings model <name>[/cyan]            Switch the active model
  [cyan]/settings provider <ollama|openrouter>[/cyan]
  [cyan]/settings thinking <low|medium|high>[/cyan]
  [cyan]/settings tools <on|off>[/cyan]          Allow/deny file operations
  [cyan]/settings shell <on|off>[/cyan]          Allow/deny shell command tool
  [cyan]/settings ollama_host <url>[/cyan]       Override Ollama base URL
  [cyan]/settings proxy <url>[/cyan]             Set proxy for OpenRouter (e.g. socks5://127.0.0.1:1080)
  [cyan]/settings proxy off[/cyan]               Disable proxy

Anything else is sent to the agent as a request.
"""


class CommandResult:
    """Lightweight signal returned by the command dispatcher."""

    def __init__(self, handled: bool, should_exit: bool = False) -> None:
        self.handled = handled
        self.should_exit = should_exit


def handle_command(
    text: str, config: "Config", agent: "Agent", session=None
) -> CommandResult:
    """Process a slash command. Returns whether it was handled / should exit."""
    if not text.startswith("/"):
        return CommandResult(handled=False)

    parts = text[1:].split()
    if not parts:
        return CommandResult(handled=True)

    cmd, args = parts[0].lower(), parts[1:]

    if cmd in ("exit", "quit"):
        return CommandResult(handled=True, should_exit=True)

    if cmd == "help":
        ui.console.print(HELP_TEXT)
        return CommandResult(handled=True)

    if cmd == "status":
        _print_full_status(config, agent)
        return CommandResult(handled=True)

    if cmd == "clear":
        agent.clear()
        ui.print_info("Conversation history cleared.")
        return CommandResult(handled=True)

    if cmd == "models":
        _list_models_interactive(agent, config, session)
        return CommandResult(handled=True)

    if cmd == "presets":
        _show_presets(config, session, agent)
        return CommandResult(handled=True)

    if cmd == "use":
        if not args:
            ui.print_error("Usage: /use <model-name>")
        else:
            _switch_model(args[0], config, agent)
        return CommandResult(handled=True)

    if cmd == "history":
        _show_history(agent)
        return CommandResult(handled=True)

    if cmd == "compact":
        _compact_context(agent)
        return CommandResult(handled=True)

    if cmd == "save":
        _save_conversation(agent, args[0] if args else None)
        return CommandResult(handled=True)

    if cmd == "load":
        if not args:
            ui.print_error("Usage: /load <file>")
        else:
            _load_conversation(agent, args[0])
        return CommandResult(handled=True)

    if cmd == "key":
        if not args:
            ui.print_error("Usage: /key <your-openrouter-api-key>")
        else:
            _set_key(args[0], config, agent)
        return CommandResult(handled=True)

    if cmd == "credits":
        _show_credits(agent, config)
        return CommandResult(handled=True)

    if cmd == "update":
        _do_update()
        return CommandResult(handled=True)

    if cmd == "integrations":
        _show_integrations(config, agent)
        return CommandResult(handled=True)

    if cmd == "connect":
        if len(args) < 2:
            _show_connect_help(args[0] if args else None)
        else:
            _connect_integration(args[0].lower(), args[1], config, agent)
        return CommandResult(handled=True)

    if cmd == "disconnect":
        if not args:
            ui.print_error("Usage: /disconnect <github|gmail>")
        else:
            _disconnect_integration(args[0].lower(), config, agent)
        return CommandResult(handled=True)

    if cmd == "settings":
        _handle_settings(args, config, agent, session=session)
        return CommandResult(handled=True)

    ui.print_error(f"Unknown command '/{cmd}'. Type /help.")
    return CommandResult(handled=True)


def _print_full_status(config: "Config", agent: "Agent") -> None:
    from rich.table import Table
    from rich.panel import Panel
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("provider", f"[cyan]{config.provider}[/cyan]")
    table.add_row("model", f"[green]{config.model}[/green]")
    table.add_row("thinking", f"[yellow]{config.thinking}[/yellow]")
    table.add_row("tools", "[green]on[/green]" if config.tools_enabled else "[red]off[/red]")
    table.add_row("shell", "[green]on[/green]" if config.allow_shell else "[red]off[/red]")
    table.add_row("ollama_host", f"[dim]{config.ollama_host}[/dim]")
    key_status = "[green]set[/green]" if config.openrouter_api_key else "[red]not set[/red]"
    table.add_row("openrouter key", key_status)
    if config.proxy_url:
        table.add_row("proxy", f"[cyan]{config.proxy_url}[/cyan]")
    table.add_row("turns", str(agent.conversation_turns()))
    table.add_row("session tokens", str(agent.session_tokens))
    if config.provider == "openrouter":
        table.add_row("session cost", f"${agent.session_cost:.5f}")
    ui.console.print(Panel(table, title="rast-cli status", border_style="cyan", expand=False))


def _list_models_interactive(agent: "Agent", config: "Config", session) -> None:
    ui.print_info("Querying provider for available models...")
    models = agent.provider.list_models()
    if not models:
        ui.print_error("No models returned (provider unreachable or none installed).")
        ui.print_info("Tip: try /presets to see curated models for this provider.")
        return
    ui.console.print(f"[bold]Available models ({config.provider}):[/bold]")
    for i, m in enumerate(models[:60], 1):
        marker = " [bold cyan]◀ active[/bold cyan]" if m == config.model else ""
        ui.console.print(f"  [dim]{i:>3}.[/dim] [green]{m}[/green]{marker}")
    if session:
        try:
            from prompt_toolkit.formatted_text import HTML
            answer = session.prompt(
                HTML("<ansiyellow>Enter number to switch, or press Enter to keep current: </ansiyellow>")
            ).strip()
            if answer.isdigit():
                idx = int(answer) - 1
                if 0 <= idx < len(models):
                    _switch_model(models[idx], config, agent)
                else:
                    ui.print_error("Number out of range.")
        except (EOFError, KeyboardInterrupt):
            pass


def _show_presets(config: "Config", session, agent: "Agent") -> None:
    presets = PRESET_MODELS.get(config.provider, [])
    if not presets:
        ui.print_error(f"No presets defined for provider '{config.provider}'.")
        return
    ui.console.print(f"[bold]Preset models ({config.provider}):[/bold]")
    for i, m in enumerate(presets, 1):
        marker = " [bold cyan]◀ active[/bold cyan]" if m == config.model else ""
        ui.console.print(f"  [dim]{i:>3}.[/dim] [green]{m}[/green]{marker}")
    if session:
        try:
            from prompt_toolkit.formatted_text import HTML
            answer = session.prompt(
                HTML("<ansiyellow>Enter number to switch, or press Enter to keep current: </ansiyellow>")
            ).strip()
            if answer.isdigit():
                idx = int(answer) - 1
                if 0 <= idx < len(presets):
                    _switch_model(presets[idx], config, agent)
                else:
                    ui.print_error("Number out of range.")
        except (EOFError, KeyboardInterrupt):
            pass


def _switch_model(model: str, config: "Config", agent: "Agent") -> None:
    config.set_model(model)
    agent.refresh()
    ui.print_info(f"Switched to model '[green]{config.model}[/green]'.")


def _show_history(agent: "Agent") -> None:
    from rich.table import Table
    from rich.panel import Panel
    user_turns = agent.conversation_turns()
    total_msgs = len(agent.messages)
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("user turns", str(user_turns))
    table.add_row("total messages", str(total_msgs))
    table.add_row("session tokens", str(agent.session_tokens))
    table.add_row("session cost", f"${agent.session_cost:.5f}")
    ui.console.print(Panel(table, title="conversation history", border_style="blue", expand=False))


def _compact_context(agent: "Agent") -> None:
    from .providers import ProviderError
    turns = agent.conversation_turns()
    if turns == 0:
        ui.print_info("Nothing to compact — conversation is empty.")
        return
    ui.print_info(f"Compacting {turns} turn(s) via LLM summary...")
    try:
        summary_response = agent.provider.chat(
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {
                    "role": "user",
                    "content": (
                        "Summarise the following conversation in a concise paragraph so it can be "
                        "used as context going forward. Preserve all key facts, decisions, file "
                        "names, and code that was written.\n\n"
                        + "\n".join(
                            f"[{m['role']}]: {str(m.get('content',''))[:500]}"
                            for m in agent.messages
                            if m.get("role") in ("user", "assistant")
                        )
                    ),
                },
            ],
            tools=None,
        )
        summary = summary_response.content.strip() or "(no summary generated)"
        agent.compact(summary)
        ui.print_info(f"Context compacted. Summary:\n{summary[:400]}")
    except ProviderError as exc:
        ui.print_error(f"Could not compact: {exc}")


def _save_conversation(agent: "Agent", path_arg) -> None:
    if path_arg:
        path = Path(path_arg)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(f"rast_conversation_{ts}.json")
    try:
        path.write_text(agent.to_json(), encoding="utf-8")
        ui.print_info(f"Conversation saved to [green]{path}[/green].")
    except OSError as exc:
        ui.print_error(f"Could not save: {exc}")


def _load_conversation(agent: "Agent", path_arg: str) -> None:
    path = Path(path_arg)
    if not path.is_file():
        ui.print_error(f"File not found: {path}")
        return
    try:
        agent.load_json(path.read_text(encoding="utf-8"))
        ui.print_info(f"Loaded conversation from [green]{path}[/green] ({agent.conversation_turns()} turns).")
    except (OSError, ValueError) as exc:
        ui.print_error(f"Could not load: {exc}")


def _show_credits(agent: "Agent", config: "Config") -> None:
    from rich.table import Table
    from rich.panel import Panel
    if config.provider != "openrouter":
        ui.print_info("Credits are only available for the [cyan]openrouter[/cyan] provider.")
        return
    if not config.openrouter_api_key:
        ui.print_error("No OpenRouter API key set. Use [cyan]/key <api-key>[/cyan] first.")
        return
    ui.print_info("Fetching account credits from OpenRouter...")
    data = agent.provider.get_credits()
    if data is None:
        ui.print_error("Could not fetch credits (network error or invalid key).")
        return
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    # OpenRouter credits endpoint returns { "data": { "total_credits": ..., "usage": ... } }
    inner = data.get("data") or data
    total = inner.get("total_credits", inner.get("credits", "?"))
    usage = inner.get("usage", "?")
    try:
        remaining = round(float(total) - float(usage), 6) if total != "?" and usage != "?" else "?"
    except (TypeError, ValueError):
        remaining = "?"
    table.add_row("total credits", f"[green]${total}[/green]")
    table.add_row("used", f"[yellow]${usage}[/yellow]")
    table.add_row("remaining", f"[cyan]${remaining}[/cyan]")
    ui.console.print(Panel(table, title="openrouter credits", border_style="cyan", expand=False))


def _set_key(key: str, config: "Config", agent: "Agent") -> None:
    config.set_openrouter_key(key)
    agent.refresh()
    masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    ui.print_info(f"OpenRouter API key set ([dim]{masked}[/dim]). Switch provider with [cyan]/settings provider openrouter[/cyan].")
    # Auto-switch to openrouter if Ollama isn't the user's intent
    if config.provider != "openrouter":
        ui.print_info("Run [cyan]/settings provider openrouter[/cyan] to start using it.")


CONNECT_HELP = {
    "github": (
        "[bold]GitHub Setup[/bold]\n\n"
        "  1. Go to [link=https://github.com/settings/tokens]https://github.com/settings/tokens[/link]\n"
        "  2. Click [bold]Generate new token (classic)[/bold]\n"
        "  3. Select scopes: [cyan]repo[/cyan], [cyan]workflow[/cyan], [cyan]delete_repo[/cyan] (optional)\n"
        "  4. Copy the token and run:\n\n"
        "     [cyan]/connect github ghp_yourTokenHere[/cyan]\n"
    ),
    "gmail": (
        "[bold]Gmail Setup[/bold]\n\n"
        "  1. Go to [link=https://developers.google.com/oauthplayground]https://developers.google.com/oauthplayground[/link]\n"
        "  2. In the left panel, find [bold]Gmail API v1[/bold]\n"
        "  3. Select: [cyan]https://mail.google.com/[/cyan]\n"
        "  4. Click [bold]Authorize APIs[/bold] → sign in → [bold]Exchange authorization code for tokens[/bold]\n"
        "  5. Copy the [bold]Access token[/bold] and run:\n\n"
        "     [cyan]/connect gmail ya29.yourTokenHere[/cyan]\n\n"
        "  Note: OAuth tokens expire after ~1 hour. For persistent access, set\n"
        "  [cyan]GMAIL_ACCESS_TOKEN[/cyan] in your [cyan].env[/cyan] file.\n"
    ),
}


def _show_connect_help(service) -> None:
    if service and service in CONNECT_HELP:
        ui.console.print(CONNECT_HELP[service])
    else:
        ui.console.print("[bold]Available integrations:[/bold]\n")
        ui.console.print("  [cyan]/connect github <token>[/cyan]   — Link GitHub (git + GitHub API)")
        ui.console.print("  [cyan]/connect gmail <token>[/cyan]    — Link Gmail (send, read, search)")
        ui.console.print("\nRun [cyan]/connect github[/cyan] or [cyan]/connect gmail[/cyan] for setup instructions.")


def _show_integrations(config: "Config", agent: "Agent") -> None:
    from rich.table import Table
    from rich.panel import Panel
    import os
    table = Table(show_header=True, box=None, padding=(0, 2))
    table.add_column("Service", style="bold")
    table.add_column("Status")
    table.add_column("Token")
    table.add_column("Tools loaded")

    gh_token = os.environ.get("GITHUB_TOKEN", "")
    gm_token = os.environ.get("GMAIL_ACCESS_TOKEN", "")

    gh_tools = [t for t in agent.registry.names() if t.startswith("git")]
    gm_tools = [t for t in agent.registry.names() if t.startswith("gmail")]

    table.add_row(
        "GitHub",
        "[green]connected[/green]" if config.github_enabled else "[dim]not connected[/dim]",
        (gh_token[:8] + "..." if gh_token else "[dim]not set[/dim]"),
        str(len(gh_tools)),
    )
    table.add_row(
        "Gmail",
        "[green]connected[/green]" if config.gmail_enabled else "[dim]not connected[/dim]",
        (gm_token[:8] + "..." if gm_token else "[dim]not set[/dim]"),
        str(len(gm_tools)),
    )
    ui.console.print(Panel(table, title="integrations", border_style="cyan", expand=False))
    if not config.github_enabled and not config.gmail_enabled:
        ui.console.print("  Run [cyan]/connect github[/cyan] or [cyan]/connect gmail[/cyan] to get started.")


def _connect_integration(service: str, token: str, config: "Config", agent: "Agent") -> None:
    try:
        config.set_integration_token(service, token)
    except ValueError as exc:
        ui.print_error(str(exc))
        return
    agent.refresh()
    masked = token[:8] + "..." + token[-4:] if len(token) > 12 else "***"
    tool_names = [t for t in agent.registry.names() if t.startswith(service) or (service == "github" and t.startswith("git"))]
    ui.print_info(
        f"[green]{service.capitalize()}[/green] connected ([dim]{masked}[/dim]). "
        f"{len(tool_names)} tools now available."
    )
    ui.print_info(f"Try: [cyan]commit all my changes with message 'initial commit'[/cyan]")


def _disconnect_integration(service: str, config: "Config", agent: "Agent") -> None:
    import os
    env_map = {"github": "GITHUB_TOKEN", "gmail": "GMAIL_ACCESS_TOKEN"}
    if service not in env_map:
        ui.print_error(f"Unknown integration '{service}'. Choose: github, gmail")
        return
    os.environ.pop(env_map[service], None)
    if service == "github":
        config.github_enabled = False
    elif service == "gmail":
        config.gmail_enabled = False
    config.save()
    agent.refresh()
    ui.print_info(f"[yellow]{service.capitalize()}[/yellow] disconnected.")


def _do_update() -> None:
    import subprocess
    import sys
    from pathlib import Path

    # Locate the project root (the directory containing pyproject.toml).
    here = Path(__file__).parent.parent.resolve()
    pyproject = here / "pyproject.toml"
    if not pyproject.is_file():
        ui.print_error("Cannot locate project root (pyproject.toml not found).")
        return

    ui.print_info("Checking for updates...")

    # ── 1. Try git pull if this is a git repo ────────────────────────────
    git_dir = here / ".git"
    if git_dir.is_dir():
        # Check for a configured remote.
        remote_check = subprocess.run(
            ["git", "remote"],
            cwd=str(here), capture_output=True, text=True,
        )
        remotes = remote_check.stdout.strip().splitlines()

        if not remotes:
            ui.print_info("No git remote configured — nothing to pull.")
        else:
            ui.print_info("Fetching latest changes from remote...")
            fetch = subprocess.run(
                ["git", "fetch", "--all"],
                cwd=str(here), capture_output=True, text=True,
            )
            if fetch.returncode != 0:
                ui.print_error(f"git fetch failed: {fetch.stderr.strip()}")
                return

            # Check if we are behind the remote.
            status = subprocess.run(
                ["git", "status", "-uno"],
                cwd=str(here), capture_output=True, text=True,
            )
            if "Your branch is up to date" in status.stdout:
                ui.print_info("[green]Already up to date.[/green] No changes found.")
                _reinstall(here, sys.executable)
                return

            pull = subprocess.run(
                ["git", "pull", "--rebase"],
                cwd=str(here), capture_output=True, text=True,
            )
            if pull.returncode != 0:
                ui.print_error(f"git pull failed:\n{pull.stderr.strip()}")
                return
            ui.print_info(f"[green]Pulled latest changes.[/green]\n{pull.stdout.strip()}")

    else:
        # ── 2. No git — show manual instructions ─────────────────────────
        ui.console.print(
            "[yellow]This project is not a git repository.[/yellow]\n\n"
            "To enable automatic updates, initialise git and push to GitHub:\n\n"
            "  [cyan]git init\n"
            "  git remote add origin https://github.com/YOUR_USER/RAST-CLI.git\n"
            "  git add -A && git commit -m 'initial commit'\n"
            "  git push -u origin main[/cyan]\n\n"
            "After that, [cyan]/update[/cyan] will pull and reinstall automatically."
        )
        return

    # ── 3. Reinstall package so the 'rast' script picks up changes ────────
    _reinstall(here, sys.executable)


def _reinstall(project_dir, python_exe: str) -> None:
    import subprocess
    import sys
    from pathlib import Path

    ui.print_info("Reinstalling package...")
    pip = str(Path(python_exe).parent / "pip")
    result = subprocess.run(
        [pip, "install", "-e", str(project_dir), "-q"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        ui.print_error(f"pip install failed:\n{result.stderr.strip()}")
        return

    # Re-read version from the freshly installed package.
    try:
        import importlib.metadata as _meta
        new_version = _meta.version("rast-cli")
    except Exception:
        new_version = "unknown"

    ui.print_info(
        f"[green]Update complete.[/green] Version: [bold]{new_version}[/bold]\n"
        "Restart [cyan]rast[/cyan] to load the new code."
    )


def _handle_settings(args, config: "Config", agent: "Agent", session=None) -> None:
    if not args:
        ui.print_error("Usage: /settings <model|provider|thinking|tools|shell|ollama_host|proxy> <value>")
        return
    key = args[0].lower()
    # /settings model with no value → show picker
    if key == "model" and len(args) < 2:
        _show_presets(config, session, agent)
        return
    if len(args) < 2:
        ui.print_error(f"Usage: /settings {key} <value>")
        return
    value = args[1].lower()

    try:
        if key == "model":
            _switch_model(args[1], config, agent)
        elif key == "provider":
            if value not in VALID_PROVIDERS:
                ui.print_error(f"Provider must be one of {VALID_PROVIDERS}.")
                return
            config.set_provider(value)
            if value == "openrouter" and not config.openrouter_api_key:
                ui.print_error(
                    "OPENROUTER_API_KEY is not set. Use [cyan]/key <api-key>[/cyan] to set it now."
                )
            agent.refresh()
            ui.print_info(f"Provider set to '[cyan]{config.provider}[/cyan]' (model: [green]{config.model}[/green]).")
        elif key == "thinking":
            if value not in VALID_THINKING:
                ui.print_error(f"Thinking must be one of {VALID_THINKING}.")
                return
            config.set_thinking(value)
            agent.refresh()
            ui.print_info(f"Thinking depth set to '[yellow]{value}[/yellow]'.")
        elif key == "tools":
            enabled = value in ("on", "true", "yes", "1")
            config.set_tools(enabled)
            agent.refresh()
            ui.print_info(f"Tools {'[green]enabled[/green]' if enabled else '[red]disabled[/red]'}.")
        elif key == "shell":
            allow = value in ("on", "true", "yes", "1")
            config.allow_shell = allow
            config.save()
            agent.refresh()
            ui.print_info(f"Shell tool {'[green]enabled[/green]' if allow else '[red]disabled[/red]'}.")
        elif key == "ollama_host":
            config.set_ollama_host(args[1])
            agent.refresh()
            ui.print_info(f"Ollama host set to '[dim]{config.ollama_host}[/dim]'.")
        elif key == "proxy":
            url = "" if value in ("off", "none", "disable", "clear") else args[1]
            config.set_proxy(url)
            if url:
                ui.print_info(f"Proxy set to [cyan]{url}[/cyan]. All OpenRouter requests will route through it.")
            else:
                ui.print_info("Proxy disabled.")
            agent.refresh()
        else:
            ui.print_error(f"Unknown setting '[bold]{key}[/bold]'. Valid: model, provider, thinking, tools, shell, ollama_host, proxy.")
    except ValueError as exc:
        ui.print_error(str(exc))
