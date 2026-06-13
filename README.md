# Rast-CLI

An autonomous, agentic terminal AI coding assistant inspired by Claude Code. Rast-CLI
runs in your shell, talks to a local (**Ollama**) or cloud (**OpenRouter**) LLM, and
uses a tool-calling loop to read, write, search, and refactor files in your project —
always asking permission before it changes anything.

## Features

- **Dual providers** — local **Ollama** (`http://localhost:11434`) or **OpenRouter** cloud API.
- **Agentic tool loop** — Reasoning → Tool Selection → Execution → Observation → Next Step.
- **File tools** — read, full rewrite, targeted edits, create/delete/move, directory tree, regex search.
- **Optional shell tool** — run tests/build commands behind a permission gate.
- **Permission gatekeeping** — `[y/N]` confirmation before any file mutation or command.
- **Token & cost tracking** — per-turn and per-session usage (cost shown for OpenRouter).
- **Slash commands** — switch model, provider, reasoning depth, and toggle tools at runtime.
- **Persistent config** — `~/.config/rast-cli/config.json` plus `.env`/environment overrides.

## Install

```bash
cd RAST-CLI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional editable install to get the `rast` command:
pip install -e .
```

## Run

```bash
# from anywhere in the project you want the agent to operate on:
python -m rast_cli
# or, after `pip install -e .`:
rast
```

### Using Ollama (default, local)

```bash
ollama serve            # start the server
ollama pull llama3      # or qwen2.5-coder / deepseek-coder
python -m rast_cli
```

### Using OpenRouter (cloud)

```bash
export OPENROUTER_API_KEY="sk-or-..."   # or put it in a local .env file
python -m rast_cli
# then inside the prompt:
/settings provider openrouter
/settings model anthropic/claude-3.5-sonnet
```

## Slash commands

| Command | Description |
| --- | --- |
| `/help` | Show help |
| `/status` | Show current provider/model/settings |
| `/models` | List models from the active provider |
| `/clear` | Clear conversation history |
| `/settings model <name>` | Switch the active model |
| `/settings provider <ollama\|openrouter>` | Switch backend provider |
| `/settings thinking <low\|medium\|high>` | Reasoning depth (token budget vs. verbose CoT) |
| `/settings tools <on\|off>` | Allow/deny file operations |
| `/settings shell <on\|off>` | Allow/deny the shell command tool |
| `/exit` `/quit` | Quit |

## Configuration

Settings persist to `~/.config/rast-cli/config.json`. Environment variables (optionally
loaded from a `.env` in the working directory) override at startup:

- `OPENROUTER_API_KEY` — required for the OpenRouter provider (never written to disk).
- `OLLAMA_HOST` — override the Ollama base URL.
- `RAST_PROVIDER`, `RAST_MODEL` — default provider/model on startup.

See `.env.example`.

## Project layout

```
rast_cli/
  cli.py            # interactive loop + persistent prompt
  agent.py          # reasoning/tool-execution loop, token tracking
  config.py         # config manager (JSON + env/.env)
  commands.py       # slash-command dispatcher
  ui.py             # rich terminal UI helpers
  providers/        # ollama + openrouter clients (unified chat/tool API)
  tools/            # tool registry + built-in file/search/shell tools
```

## Safety

- All file paths are confined to the current workspace root.
- Every mutating action (write/edit/create/delete/move/shell) requires explicit `[y/N]` approval.
- The shell tool is **off by default**; enable with `/settings shell on`.
