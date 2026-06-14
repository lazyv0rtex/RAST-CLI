"""Main interactive loop for Rast-CLI."""

from __future__ import annotations

import argparse
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.completion import WordCompleter

from . import __version__, ui
from .agent import Agent
from .commands import handle_command
from .config import Config, VALID_PROVIDERS
from .providers import ProviderError

SLASH_COMMANDS = [
    "/help",
    "/status",
    "/models",
    "/presets",
    "/use ",
    "/history",
    "/compact",
    "/save",
    "/load ",
    "/clear",
    "/key ",
    "/exit",
    "/quit",
    "/settings model ",
    "/settings provider ollama",
    "/settings provider openrouter",
    "/settings thinking low",
    "/settings thinking medium",
    "/settings thinking high",
    "/settings tools on",
    "/settings tools off",
    "/settings shell on",
    "/settings shell off",
    "/settings ollama_host ",
    "/settings proxy ",
    "/settings proxy off",
    "/credits",
    "/update",
    "/autocommit on",
    "/autocommit off",
    "/integrations",
    "/connect github ",
    "/connect gmail ",
    "/disconnect github",
    "/disconnect gmail",
]


def _make_permission_cb(session: PromptSession):
    def permission_cb(tool_name: str, preview: str) -> bool:
        ui.print_permission_request(tool_name, preview)
        try:
            answer = session.prompt(HTML("<ansiyellow>Approve? [y/N] </ansiyellow>"))
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() in ("y", "yes")

    return permission_cb


def _prompt_text(config: Config) -> HTML:
    return HTML(
        f"<ansicyan><b>rast-cli</b></ansicyan> "
        f"<ansigreen>({config.provider}:{config.model})</ansigreen> "
        f"<ansiblue>&gt;</ansiblue> "
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="rast",
        description="Rast-CLI: agentic terminal AI coding assistant.",
    )
    p.add_argument("-p", "--provider", choices=VALID_PROVIDERS, help="LLM provider to use.")
    p.add_argument("-m", "--model", help="Model name to use.")
    p.add_argument("-k", "--key", help="OpenRouter API key (overrides env/config).")
    p.add_argument(
        "--proxy",
        help="Proxy URL for OpenRouter (e.g. socks5://127.0.0.1:1080 or http://user:pass@host:port).",
    )
    p.add_argument("--version", action="version", version=f"rast-cli {__version__}")
    return p.parse_args()


def _prompt_for_key(session: PromptSession) -> str:
    """Interactively ask the user to paste their OpenRouter API key."""
    ui.console.print(
        "[yellow]OpenRouter provider selected but no API key found.[/yellow]\n"
        "  Get a free key at [link=https://openrouter.ai/keys]https://openrouter.ai/keys[/link]\n"
        "  Or press Enter to switch back to Ollama."
    )
    try:
        key = session.prompt(HTML("<ansiyellow>OpenRouter API key: </ansiyellow>")).strip()
    except (EOFError, KeyboardInterrupt):
        key = ""
    return key


def run() -> int:
    args = _parse_args()
    config = Config.load()

    # CLI flag overrides.
    if args.provider:
        config.set_provider(args.provider)
    if args.model:
        config.set_model(args.model)
    if args.key:
        config.set_openrouter_key(args.key)
    if args.proxy:
        config.set_proxy(args.proxy)

    ui.print_banner(__version__)
    ui.print_status(config.provider, config.model, config.thinking, config.tools_enabled)

    # Build the session early so we can use it for the key prompt.
    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        completer=WordCompleter(SLASH_COMMANDS, sentence=True, ignore_case=True),
    )

    if config.provider == "openrouter" and not config.openrouter_api_key:
        key = _prompt_for_key(session)
        if key:
            config.set_openrouter_key(key)
            masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
            ui.print_info(f"Key accepted ([dim]{masked}[/dim]).")
        else:
            config.set_provider("ollama")
            ui.print_info("No key provided — switched back to [cyan]ollama[/cyan].")

    agent = Agent(
        config=config,
        permission_cb=_make_permission_cb(session),
        on_tool_call=ui.print_tool_call,
        on_tool_result=ui.print_tool_result,
        on_assistant_text=ui.print_assistant,
        on_thinking=ui.print_thinking,
    )

    while True:
        try:
            user_input = session.prompt(_prompt_text(config)).strip()
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            result = handle_command(user_input, config, agent, session=session)
            if result.should_exit:
                break
            continue

        try:
            agent.run_turn(user_input)
        except ProviderError as exc:
            ui.print_error(str(exc))
            continue
        except KeyboardInterrupt:
            ui.print_info("\nInterrupted. Returning to prompt.")
            continue

        ui.print_usage(
            agent.last_turn_tokens,
            agent.session_tokens,
            agent.last_turn_cost,
            agent.session_cost,
            config.provider,
        )

    ui.print_info("\nGoodbye.")
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
