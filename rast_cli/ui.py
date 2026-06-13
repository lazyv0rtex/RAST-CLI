"""Rich-based terminal UI helpers for Rast-CLI."""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

console = Console()

BANNER = r"""
 ____            _        ____ _     ___
|  _ \ __ _ ___| |_     / ___| |   |_ _|
| |_) / _` / __| __|___| |   | |    | |
|  _ < (_| \__ \ ||___| |___| |___ | |
|_| \_\__,_|___/\__|    \____|_____|___|
"""


def print_banner(version: str) -> None:
    console.print(Text(BANNER, style="bold cyan"))
    console.print(
        Text(
            f"  Agentic terminal coding assistant  v{version}",
            style="dim",
        )
    )
    console.print(
        Text(
            "  Type a request, or /help for commands. Ctrl-C / /exit to quit.\n",
            style="dim",
        )
    )


def print_status(provider: str, model: str, thinking: str, tools_on: bool) -> None:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("provider", f"[cyan]{provider}[/cyan]")
    table.add_row("model", f"[green]{model}[/green]")
    table.add_row("thinking", f"[yellow]{thinking}[/yellow]")
    table.add_row("tools", "[green]on[/green]" if tools_on else "[red]off[/red]")
    console.print(Panel(table, title="rast-cli status", border_style="cyan", expand=False))


def print_assistant(content: str) -> None:
    if not content.strip():
        return
    console.print()
    console.print(Markdown(content))
    console.print()


def print_thinking(text: str) -> None:
    console.print(Panel(text.strip(), title="reasoning", border_style="magenta", expand=False))


def print_tool_call(name: str, args_summary: str) -> None:
    console.print(
        f"[bold blue]» tool[/bold blue] [cyan]{name}[/cyan] [dim]{args_summary}[/dim]"
    )


def print_tool_result(name: str, ok: bool, output: str) -> None:
    style = "green" if ok else "red"
    icon = "✓" if ok else "✗"
    preview = output if len(output) <= 1500 else output[:1500] + "\n... [truncated]"
    console.print(
        Panel(
            preview,
            title=f"[{style}]{icon} {name}[/{style}]",
            border_style=style,
            expand=False,
        )
    )


def print_permission_request(title: str, detail: str) -> None:
    body = detail
    if any(ch in detail for ch in ("\n", "{")):
        body = detail
    console.print(
        Panel(
            body,
            title=f"[bold yellow]permission required: {title}[/bold yellow]",
            border_style="yellow",
            expand=False,
        )
    )


def print_diff_preview(text: str) -> None:
    console.print(Syntax(text, "diff", theme="ansi_dark", word_wrap=True))


def print_error(msg: str) -> None:
    console.print(f"[bold red]error:[/bold red] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


def print_usage(
    turn_tokens: int,
    session_tokens: int,
    turn_cost: float,
    session_cost: float,
    provider: str,
) -> None:
    parts = [f"turn: {turn_tokens} tok", f"session: {session_tokens} tok"]
    if provider == "openrouter":
        parts.append(f"turn cost: ${turn_cost:.5f}")
        parts.append(f"session cost: ${session_cost:.5f}")
    console.print(f"[dim]· {'  |  '.join(parts)}[/dim]")
