"""GitHub integration tools for Rast-CLI.

Requires a GitHub Personal Access Token (classic or fine-grained) with
appropriate scopes. Set via /connect github or GITHUB_TOKEN env var.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import requests

from ..tools.registry import Tool, ToolRegistry, ToolResult

GITHUB_API = "https://api.github.com"


def _token() -> str:
    t = os.environ.get("GITHUB_TOKEN", "")
    if not t:
        raise PermissionError(
            "GITHUB_TOKEN is not set. Run /connect github to set it."
        )
    return t


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _api(method: str, path: str, **kwargs) -> requests.Response:
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    try:
        resp = requests.request(method, url, headers=_headers(), timeout=30, **kwargs)
    except requests.exceptions.ConnectionError:
        raise PermissionError("Could not connect to GitHub API. Check your network.")
    except requests.exceptions.Timeout:
        raise PermissionError("GitHub API request timed out.")
    return resp


def _ok(resp: requests.Response) -> ToolResult:
    try:
        data = resp.json()
    except Exception:
        data = resp.text
    if resp.ok:
        if isinstance(data, dict):
            summary = {k: v for k, v in data.items() if k in (
                "id", "name", "full_name", "html_url", "sha", "number",
                "title", "state", "message", "commit", "url", "login"
            )}
            return ToolResult(True, json.dumps(summary, indent=2) if summary else json.dumps(data, indent=2)[:2000])
        return ToolResult(True, str(data)[:2000])
    err = data.get("message", str(data)) if isinstance(data, dict) else str(data)
    return ToolResult(False, f"GitHub API error {resp.status_code}: {err}")


# --------------------------------------------------------------------------
# Git local helpers (run in workspace)
# --------------------------------------------------------------------------
def _git(args: List[str], cwd: str | None = None) -> ToolResult:
    cwd = cwd or str(Path.cwd())
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return ToolResult(False, "git is not installed or not in PATH.")
    except subprocess.TimeoutExpired:
        return ToolResult(False, "git command timed out.")
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    ok = proc.returncode == 0
    body = out or err or f"[exit {proc.returncode}]"
    return ToolResult(ok, body)


# --------------------------------------------------------------------------
# Tool handlers
# --------------------------------------------------------------------------
def _git_status(args: Dict[str, Any]) -> ToolResult:
    return _git(["status", "--short", "--branch"])


def _git_add(args: Dict[str, Any]) -> ToolResult:
    paths = args.get("paths", ["."])
    if isinstance(paths, str):
        paths = [paths]
    return _git(["add"] + paths)


def _git_commit(args: Dict[str, Any]) -> ToolResult:
    message = args["message"]
    r = _git(["add", "-A"])
    if not r.ok and "nothing to commit" not in r.output:
        return r
    return _git(["commit", "-m", message])


def _git_push(args: Dict[str, Any]) -> ToolResult:
    remote = args.get("remote", "origin")
    branch = args.get("branch", "")
    cmd = ["push", remote]
    if branch:
        cmd.append(branch)
    result = _git(cmd)
    if not result.ok and "set-upstream" in result.output:
        branch_r = _git(["rev-parse", "--abbrev-ref", "HEAD"])
        if branch_r.ok:
            result = _git(["push", "--set-upstream", remote, branch_r.output.strip()])
    return result


def _git_pull(args: Dict[str, Any]) -> ToolResult:
    remote = args.get("remote", "origin")
    branch = args.get("branch", "")
    cmd = ["pull", remote]
    if branch:
        cmd.append(branch)
    return _git(cmd)


def _git_log(args: Dict[str, Any]) -> ToolResult:
    n = int(args.get("count", 10))
    return _git(["log", f"--max-count={n}", "--oneline", "--decorate"])


def _git_diff(args: Dict[str, Any]) -> ToolResult:
    staged = args.get("staged", False)
    cmd = ["diff"]
    if staged:
        cmd.append("--cached")
    return _git(cmd)


def _git_checkout(args: Dict[str, Any]) -> ToolResult:
    branch = args["branch"]
    create = args.get("create", False)
    cmd = ["checkout", "-b", branch] if create else ["checkout", branch]
    return _git(cmd)


def _git_clone(args: Dict[str, Any]) -> ToolResult:
    url = args["url"]
    dest = args.get("destination", "")
    cmd = ["clone", url]
    if dest:
        cmd.append(dest)
    return _git(cmd, cwd=str(Path.cwd()))


# --------------------------------------------------------------------------
# GitHub REST API handlers
# --------------------------------------------------------------------------
def _gh_whoami(args: Dict[str, Any]) -> ToolResult:
    return _ok(_api("GET", "/user"))


def _gh_create_repo(args: Dict[str, Any]) -> ToolResult:
    name = args["name"]
    private = args.get("private", False)
    description = args.get("description", "")
    auto_init = args.get("auto_init", True)
    payload = {
        "name": name,
        "private": private,
        "description": description,
        "auto_init": auto_init,
    }
    return _ok(_api("POST", "/user/repos", json=payload))


def _gh_list_repos(args: Dict[str, Any]) -> ToolResult:
    sort = args.get("sort", "updated")
    per_page = min(int(args.get("count", 20)), 100)
    resp = _api("GET", f"/user/repos?sort={sort}&per_page={per_page}")
    if not resp.ok:
        return _ok(resp)
    repos = resp.json()
    lines = [f"{r['full_name']} ({'private' if r['private'] else 'public'}) - {r.get('description','')}" for r in repos]
    return ToolResult(True, "\n".join(lines) or "No repositories found.")


def _gh_delete_repo(args: Dict[str, Any]) -> ToolResult:
    owner = args["owner"]
    repo = args["repo"]
    resp = _api("DELETE", f"/repos/{owner}/{repo}")
    if resp.status_code == 204:
        return ToolResult(True, f"Repository {owner}/{repo} deleted.")
    return _ok(resp)


def _gh_create_pr(args: Dict[str, Any]) -> ToolResult:
    owner = args["owner"]
    repo = args["repo"]
    payload = {
        "title": args["title"],
        "head": args["head"],
        "base": args.get("base", "main"),
        "body": args.get("body", ""),
        "draft": args.get("draft", False),
    }
    return _ok(_api("POST", f"/repos/{owner}/{repo}/pulls", json=payload))


def _gh_list_issues(args: Dict[str, Any]) -> ToolResult:
    owner = args["owner"]
    repo = args["repo"]
    state = args.get("state", "open")
    resp = _api("GET", f"/repos/{owner}/{repo}/issues?state={state}&per_page=20")
    if not resp.ok:
        return _ok(resp)
    issues = [i for i in resp.json() if "pull_request" not in i]
    lines = [f"#{i['number']} [{i['state']}] {i['title']}" for i in issues]
    return ToolResult(True, "\n".join(lines) or "No issues found.")


def _gh_create_issue(args: Dict[str, Any]) -> ToolResult:
    owner = args["owner"]
    repo = args["repo"]
    payload = {
        "title": args["title"],
        "body": args.get("body", ""),
        "labels": args.get("labels", []),
    }
    return _ok(_api("POST", f"/repos/{owner}/{repo}/issues", json=payload))


def _gh_get_file(args: Dict[str, Any]) -> ToolResult:
    owner = args["owner"]
    repo = args["repo"]
    path = args["path"]
    ref = args.get("ref", "")
    url = f"/repos/{owner}/{repo}/contents/{path}"
    if ref:
        url += f"?ref={ref}"
    resp = _api("GET", url)
    if not resp.ok:
        return _ok(resp)
    data = resp.json()
    import base64
    content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
    return ToolResult(True, content[:10000])


def _gh_search_code(args: Dict[str, Any]) -> ToolResult:
    q = args["query"]
    resp = _api("GET", f"/search/code?q={requests.utils.quote(q)}&per_page=10")
    if not resp.ok:
        return _ok(resp)
    items = resp.json().get("items", [])
    lines = [f"{i['repository']['full_name']}/{i['path']}" for i in items]
    return ToolResult(True, "\n".join(lines) or "No results.")


def _gh_release(args: Dict[str, Any]) -> ToolResult:
    owner = args["owner"]
    repo = args["repo"]
    payload = {
        "tag_name": args["tag"],
        "name": args.get("name", args["tag"]),
        "body": args.get("body", ""),
        "draft": args.get("draft", False),
        "prerelease": args.get("prerelease", False),
    }
    return _ok(_api("POST", f"/repos/{owner}/{repo}/releases", json=payload))


# --------------------------------------------------------------------------
# Registry builder
# --------------------------------------------------------------------------
def register_github_tools(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="git_status",
        description="Show the working tree status (modified, staged, untracked files).",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_git_status,
    ))
    registry.register(Tool(
        name="git_add",
        description="Stage files for commit. Pass paths list or '.' for all.",
        parameters={
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
            "required": [],
        },
        handler=_git_add,
        requires_permission=True,
        previewer=lambda a: f"git add {' '.join(a.get('paths', ['.']))}",
    ))
    registry.register(Tool(
        name="git_commit",
        description="Stage all changes and create a git commit with the given message.",
        parameters={
            "type": "object",
            "properties": {"message": {"type": "string", "description": "Commit message."}},
            "required": ["message"],
        },
        handler=_git_commit,
        requires_permission=True,
        previewer=lambda a: f"git add -A && git commit -m \"{a.get('message','')}\"",
    ))
    registry.register(Tool(
        name="git_push",
        description="Push commits to the remote repository.",
        parameters={
            "type": "object",
            "properties": {
                "remote": {"type": "string", "description": "Remote name (default: origin)."},
                "branch": {"type": "string", "description": "Branch to push (default: current)."},
            },
            "required": [],
        },
        handler=_git_push,
        requires_permission=True,
        previewer=lambda a: f"git push {a.get('remote','origin')} {a.get('branch','')}".strip(),
    ))
    registry.register(Tool(
        name="git_pull",
        description="Pull latest changes from a remote branch.",
        parameters={
            "type": "object",
            "properties": {
                "remote": {"type": "string"},
                "branch": {"type": "string"},
            },
            "required": [],
        },
        handler=_git_pull,
        requires_permission=True,
        previewer=lambda a: f"git pull {a.get('remote','origin')} {a.get('branch','')}".strip(),
    ))
    registry.register(Tool(
        name="git_log",
        description="Show recent commit history.",
        parameters={
            "type": "object",
            "properties": {"count": {"type": "integer", "description": "Number of commits to show (default 10)."}},
            "required": [],
        },
        handler=_git_log,
    ))
    registry.register(Tool(
        name="git_diff",
        description="Show unstaged (or staged) changes as a diff.",
        parameters={
            "type": "object",
            "properties": {"staged": {"type": "boolean", "description": "Show staged changes instead of unstaged."}},
            "required": [],
        },
        handler=_git_diff,
    ))
    registry.register(Tool(
        name="git_checkout",
        description="Switch to a branch, or create and switch to a new branch.",
        parameters={
            "type": "object",
            "properties": {
                "branch": {"type": "string"},
                "create": {"type": "boolean", "description": "Create the branch if true."},
            },
            "required": ["branch"],
        },
        handler=_git_checkout,
        requires_permission=True,
        previewer=lambda a: f"git checkout {'-b ' if a.get('create') else ''}{a.get('branch','')}",
    ))
    registry.register(Tool(
        name="git_clone",
        description="Clone a git repository into the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Repository URL."},
                "destination": {"type": "string", "description": "Optional destination folder name."},
            },
            "required": ["url"],
        },
        handler=_git_clone,
        requires_permission=True,
        previewer=lambda a: f"git clone {a.get('url','')} {a.get('destination','')}".strip(),
    ))
    registry.register(Tool(
        name="github_whoami",
        description="Return the GitHub account info for the authenticated user.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_gh_whoami,
    ))
    registry.register(Tool(
        name="github_create_repo",
        description="Create a new GitHub repository under the authenticated user.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repository name."},
                "private": {"type": "boolean", "description": "Make the repo private (default false)."},
                "description": {"type": "string"},
                "auto_init": {"type": "boolean", "description": "Initialize with README (default true)."},
            },
            "required": ["name"],
        },
        handler=_gh_create_repo,
        requires_permission=True,
        previewer=lambda a: f"Create GitHub repo: {a.get('name','')} ({'private' if a.get('private') else 'public'})",
    ))
    registry.register(Tool(
        name="github_list_repos",
        description="List the authenticated user's GitHub repositories.",
        parameters={
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of repos to return (max 100)."},
                "sort": {"type": "string", "description": "Sort by: updated, created, pushed, full_name."},
            },
            "required": [],
        },
        handler=_gh_list_repos,
    ))
    registry.register(Tool(
        name="github_delete_repo",
        description="Delete a GitHub repository. This is irreversible.",
        parameters={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
            },
            "required": ["owner", "repo"],
        },
        handler=_gh_delete_repo,
        requires_permission=True,
        previewer=lambda a: f"PERMANENTLY DELETE GitHub repo: {a.get('owner','')}/{a.get('repo','')}",
    ))
    registry.register(Tool(
        name="github_create_pr",
        description="Open a pull request on a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "head": {"type": "string", "description": "Branch containing changes."},
                "base": {"type": "string", "description": "Target branch (default: main)."},
                "body": {"type": "string", "description": "PR description."},
                "draft": {"type": "boolean"},
            },
            "required": ["owner", "repo", "title", "head"],
        },
        handler=_gh_create_pr,
        requires_permission=True,
        previewer=lambda a: f"Create PR '{a.get('title','')}' on {a.get('owner','')}/{a.get('repo','')}",
    ))
    registry.register(Tool(
        name="github_list_issues",
        description="List issues on a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "state": {"type": "string", "description": "open, closed, or all."},
            },
            "required": ["owner", "repo"],
        },
        handler=_gh_list_issues,
    ))
    registry.register(Tool(
        name="github_create_issue",
        description="Create a new issue on a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["owner", "repo", "title"],
        },
        handler=_gh_create_issue,
        requires_permission=True,
        previewer=lambda a: f"Create issue '{a.get('title','')}' on {a.get('owner','')}/{a.get('repo','')}",
    ))
    registry.register(Tool(
        name="github_get_file",
        description="Read a file from a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string"},
                "ref": {"type": "string", "description": "Branch/tag/commit (default: default branch)."},
            },
            "required": ["owner", "repo", "path"],
        },
        handler=_gh_get_file,
    ))
    registry.register(Tool(
        name="github_search_code",
        description="Search code across GitHub repositories.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "GitHub code search query."}},
            "required": ["query"],
        },
        handler=_gh_search_code,
    ))
    registry.register(Tool(
        name="github_create_release",
        description="Create a GitHub release with a tag on a repository.",
        parameters={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "tag": {"type": "string", "description": "Tag name e.g. v1.0.0"},
                "name": {"type": "string", "description": "Release title (defaults to tag)."},
                "body": {"type": "string", "description": "Release notes."},
                "draft": {"type": "boolean"},
                "prerelease": {"type": "boolean"},
            },
            "required": ["owner", "repo", "tag"],
        },
        handler=_gh_release,
        requires_permission=True,
        previewer=lambda a: f"Create release {a.get('tag','')} on {a.get('owner','')}/{a.get('repo','')}",
    ))
