"""Built-in file, search, and shell tools for the agent."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from .registry import Tool, ToolRegistry, ToolResult

MAX_READ_BYTES = 200_000
MAX_OUTPUT_CHARS = 20_000


def _workspace_root() -> Path:
    return Path.cwd().resolve()


def _resolve(path: str) -> Path:
    """Resolve a user-supplied path, confining it to the workspace root."""
    root = _workspace_root()
    p = (root / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            f"Path '{path}' is outside the workspace root ({root})."
        ) from exc
    return p


def _truncate(text: str) -> str:
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(text)} chars total]"
    return text


# --------------------------------------------------------------------------
# File reading
# --------------------------------------------------------------------------
def _read_file(args: Dict[str, Any]) -> ToolResult:
    path = _resolve(args["path"])
    if not path.is_file():
        return ToolResult(False, f"File not found: {args['path']}")
    data = path.read_bytes()[:MAX_READ_BYTES]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ToolResult(False, f"File '{args['path']}' is not valid UTF-8 text.")
    numbered = "\n".join(
        f"{i + 1:>6}\t{line}" for i, line in enumerate(text.splitlines())
    )
    return ToolResult(True, _truncate(numbered or "(empty file)"))


# --------------------------------------------------------------------------
# File writing (full rewrite / create)
# --------------------------------------------------------------------------
def _write_file(args: Dict[str, Any]) -> ToolResult:
    path = _resolve(args["path"])
    content = args.get("content", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.is_file()
    path.write_text(content, encoding="utf-8")
    verb = "Overwrote" if existed else "Created"
    return ToolResult(True, f"{verb} {args['path']} ({len(content)} bytes).")


def _write_preview(args: Dict[str, Any]) -> str:
    content = args.get("content", "")
    lines = content.splitlines()
    head = "\n".join(lines[:40])
    more = "" if len(lines) <= 40 else f"\n... (+{len(lines) - 40} more lines)"
    return f"Write {len(content)} bytes to {args['path']}:\n{head}{more}"


# --------------------------------------------------------------------------
# Targeted edit (string replacement)
# --------------------------------------------------------------------------
def _edit_file(args: Dict[str, Any]) -> ToolResult:
    path = _resolve(args["path"])
    if not path.is_file():
        return ToolResult(False, f"File not found: {args['path']}")
    old = args["old_string"]
    new = args["new_string"]
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return ToolResult(False, "old_string not found in file; no changes made.")
    if count > 1 and not args.get("replace_all", False):
        return ToolResult(
            False,
            f"old_string appears {count} times. Provide more context to make it "
            "unique, or set replace_all=true.",
        )
    text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    return ToolResult(True, f"Edited {args['path']} ({count} replacement(s)).")


def _edit_preview(args: Dict[str, Any]) -> str:
    return (
        f"Edit {args['path']}:\n"
        f"--- remove ---\n{args.get('old_string', '')}\n"
        f"+++ add +++\n{args.get('new_string', '')}"
    )


# --------------------------------------------------------------------------
# File management: create dir, delete, move/rename
# --------------------------------------------------------------------------
def _make_dir(args: Dict[str, Any]) -> ToolResult:
    path = _resolve(args["path"])
    path.mkdir(parents=True, exist_ok=True)
    return ToolResult(True, f"Created directory {args['path']}.")


def _delete_path(args: Dict[str, Any]) -> ToolResult:
    path = _resolve(args["path"])
    if not path.exists():
        return ToolResult(False, f"Path not found: {args['path']}")
    if path.is_dir():
        shutil.rmtree(path)
        return ToolResult(True, f"Deleted directory {args['path']}.")
    path.unlink()
    return ToolResult(True, f"Deleted file {args['path']}.")


def _delete_preview(args: Dict[str, Any]) -> str:
    return f"Permanently delete: {args['path']}"


def _move_path(args: Dict[str, Any]) -> ToolResult:
    src = _resolve(args["source"])
    dst = _resolve(args["destination"])
    if not src.exists():
        return ToolResult(False, f"Source not found: {args['source']}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return ToolResult(True, f"Moved {args['source']} -> {args['destination']}.")


def _move_preview(args: Dict[str, Any]) -> str:
    return f"Move/rename: {args['source']} -> {args['destination']}"


# --------------------------------------------------------------------------
# Directory listing / tree
# --------------------------------------------------------------------------
IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}


def _list_dir(args: Dict[str, Any]) -> ToolResult:
    path = _resolve(args.get("path", "."))
    if not path.is_dir():
        return ToolResult(False, f"Not a directory: {args.get('path', '.')}")
    max_depth = int(args.get("max_depth", 2))
    root = path
    lines: List[str] = []

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(
                d.iterdir(), key=lambda e: (e.is_file(), e.name.lower())
            )
        except PermissionError:
            return
        for e in entries:
            if e.name in IGNORED_DIRS or e.name.startswith("."):
                if e.name not in (".env",):
                    continue
            rel = e.relative_to(root)
            indent = "  " * (len(rel.parts) - 1)
            suffix = "/" if e.is_dir() else ""
            lines.append(f"{indent}{e.name}{suffix}")
            if e.is_dir():
                walk(e, depth + 1)

    walk(root, 1)
    body = "\n".join(lines) or "(empty)"
    return ToolResult(True, _truncate(f"{args.get('path', '.')}/\n{body}"))


# --------------------------------------------------------------------------
# Search (grep-like)
# --------------------------------------------------------------------------
def _search(args: Dict[str, Any]) -> ToolResult:
    pattern = args["pattern"]
    root = _resolve(args.get("path", "."))
    glob = args.get("include", "*")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return ToolResult(False, f"Invalid regex: {exc}")

    matches: List[str] = []
    files = root.rglob(glob) if root.is_dir() else [root]
    for f in files:
        if not f.is_file():
            continue
        if any(part in IGNORED_DIRS for part in f.parts):
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if regex.search(line):
                    rel = f.relative_to(_workspace_root())
                    matches.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(matches) >= 200:
                        break
        except (UnicodeDecodeError, OSError):
            continue
        if len(matches) >= 200:
            break

    if not matches:
        return ToolResult(True, f"No matches for '{pattern}'.")
    return ToolResult(True, _truncate("\n".join(matches)))


# --------------------------------------------------------------------------
# Shell command execution
# --------------------------------------------------------------------------
def _run_command(args: Dict[str, Any]) -> ToolResult:
    command = args["command"]
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(_workspace_root()),
            capture_output=True,
            text=True,
            timeout=int(args.get("timeout", 120)),
        )
    except subprocess.TimeoutExpired:
        return ToolResult(False, "Command timed out.")
    out = proc.stdout or ""
    err = proc.stderr or ""
    body = f"$ {command}\n[exit {proc.returncode}]\n"
    if out:
        body += f"--- stdout ---\n{out}\n"
    if err:
        body += f"--- stderr ---\n{err}\n"
    return ToolResult(proc.returncode == 0, _truncate(body))


def _command_preview(args: Dict[str, Any]) -> str:
    return f"Run shell command:\n  $ {args['command']}"


# --------------------------------------------------------------------------
# Registry assembly
# --------------------------------------------------------------------------
def build_default_registry(allow_shell: bool = False) -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(
        Tool(
            name="read_file",
            description="Read a UTF-8 text file and return its contents with line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file."}
                },
                "required": ["path"],
            },
            handler=_read_file,
        )
    )

    reg.register(
        Tool(
            name="write_file",
            description="Create a new file or completely overwrite an existing file with the given content.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=_write_file,
            requires_permission=True,
            previewer=_write_preview,
        )
    )

    reg.register(
        Tool(
            name="edit_file",
            description=(
                "Apply a targeted edit by replacing an exact old_string with new_string. "
                "old_string must be unique unless replace_all is true."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_string", "new_string"],
            },
            handler=_edit_file,
            requires_permission=True,
            previewer=_edit_preview,
        )
    )

    reg.register(
        Tool(
            name="make_dir",
            description="Create a directory (including parents).",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_make_dir,
            requires_permission=True,
            previewer=lambda a: f"Create directory: {a['path']}",
        )
    )

    reg.register(
        Tool(
            name="delete_path",
            description="Delete a file or directory (recursive for directories).",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_delete_path,
            requires_permission=True,
            previewer=_delete_preview,
        )
    )

    reg.register(
        Tool(
            name="move_path",
            description="Move or rename a file or directory.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["source", "destination"],
            },
            handler=_move_path,
            requires_permission=True,
            previewer=_move_preview,
        )
    )

    reg.register(
        Tool(
            name="list_dir",
            description="List a directory tree up to max_depth levels (default 2).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_depth": {"type": "integer"},
                },
                "required": [],
            },
            handler=_list_dir,
        )
    )

    reg.register(
        Tool(
            name="search",
            description="Search files for a regex pattern (grep-like). Optionally filter by a glob 'include'.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "include": {"type": "string", "description": "Glob like '*.py'."},
                },
                "required": ["pattern"],
            },
            handler=_search,
        )
    )

    if allow_shell:
        reg.register(
            Tool(
                name="run_command",
                description="Run a restricted shell command in the workspace (e.g. tests/build). Requires user permission.",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["command"],
                },
                handler=_run_command,
                requires_permission=True,
                previewer=_command_preview,
            )
        )

    return reg
