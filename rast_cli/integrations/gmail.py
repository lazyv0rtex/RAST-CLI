"""Gmail integration tools for Rast-CLI.

Uses Gmail REST API via OAuth2 access token.
Set GMAIL_ACCESS_TOKEN in your environment or via /connect gmail.

To get a token:
  1. Go to https://developers.google.com/oauthplayground
  2. Select Gmail API v1 scopes:
     https://mail.google.com/
  3. Authorize and exchange for an access token.
  4. Run:  /connect gmail <token>
"""

from __future__ import annotations

import base64
import email as _email
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List

import requests

from ..tools.registry import Tool, ToolRegistry, ToolResult

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


def _token() -> str:
    t = os.environ.get("GMAIL_ACCESS_TOKEN", "")
    if not t:
        raise PermissionError(
            "GMAIL_ACCESS_TOKEN is not set. Run /connect gmail <token> to set it. "
            "See 'rash /connect gmail' for instructions."
        )
    return t


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


def _api(method: str, path: str, **kwargs) -> requests.Response:
    url = path if path.startswith("http") else f"{GMAIL_API}{path}"
    try:
        resp = requests.request(method, url, headers=_headers(), timeout=30, **kwargs)
    except requests.exceptions.ConnectionError:
        raise PermissionError("Could not connect to Gmail API. Check your network.")
    except requests.exceptions.Timeout:
        raise PermissionError("Gmail API request timed out.")
    return resp


def _ok(resp: requests.Response, label: str = "") -> ToolResult:
    try:
        data = resp.json()
    except Exception:
        data = resp.text
    if resp.ok:
        if isinstance(data, dict):
            return ToolResult(True, json.dumps(data, indent=2)[:3000])
        return ToolResult(True, str(data)[:3000])
    err = data.get("error", {}).get("message", str(data)) if isinstance(data, dict) else str(data)
    return ToolResult(False, f"Gmail API error {resp.status_code}: {err}")


# --------------------------------------------------------------------------
# Tool handlers
# --------------------------------------------------------------------------
def _send_email(args: Dict[str, Any]) -> ToolResult:
    to = args["to"]
    subject = args.get("subject", "(no subject)")
    body = args.get("body", "")
    body_type = args.get("body_type", "plain")  # plain or html

    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, body_type))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    resp = _api("POST", "/users/me/messages/send", json={"raw": raw})
    if resp.ok:
        mid = resp.json().get("id", "?")
        return ToolResult(True, f"Email sent. Message ID: {mid}")
    return _ok(resp)


def _list_emails(args: Dict[str, Any]) -> ToolResult:
    q = args.get("query", "")
    max_results = min(int(args.get("count", 10)), 50)
    params = {"maxResults": max_results, "q": q}
    resp = _api("GET", "/users/me/messages", params=params)
    if not resp.ok:
        return _ok(resp)
    messages = resp.json().get("messages", [])
    if not messages:
        return ToolResult(True, "No messages found.")

    lines: List[str] = []
    for m in messages[:max_results]:
        mid = m["id"]
        detail = _api("GET", f"/users/me/messages/{mid}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date")
        if not detail.ok:
            continue
        headers = {h["name"]: h["value"] for h in detail.json().get("payload", {}).get("headers", [])}
        lines.append(
            f"[{mid}] {headers.get('Date','?')[:16]} | From: {headers.get('From','?')[:40]} | {headers.get('Subject','(no subject)')}"
        )
    return ToolResult(True, "\n".join(lines) or "No messages found.")


def _read_email(args: Dict[str, Any]) -> ToolResult:
    mid = args["message_id"]
    resp = _api("GET", f"/users/me/messages/{mid}?format=full")
    if not resp.ok:
        return _ok(resp)
    data = resp.json()
    payload = data.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

    def _extract_body(part: Dict) -> str:
        mime = part.get("mimeType", "")
        if mime in ("text/plain", "text/html"):
            raw = part.get("body", {}).get("data", "")
            if raw:
                return base64.urlsafe_b64decode(raw + "==").decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            result = _extract_body(sub)
            if result:
                return result
        return ""

    body = _extract_body(payload)
    out = (
        f"From: {headers.get('From','?')}\n"
        f"To: {headers.get('To','?')}\n"
        f"Date: {headers.get('Date','?')}\n"
        f"Subject: {headers.get('Subject','?')}\n"
        f"---\n{body[:5000]}"
    )
    return ToolResult(True, out)


def _search_emails(args: Dict[str, Any]) -> ToolResult:
    return _list_emails({"query": args["query"], "count": args.get("count", 10)})


def _reply_email(args: Dict[str, Any]) -> ToolResult:
    thread_id = args["thread_id"]
    to = args["to"]
    subject = args.get("subject", "Re: ")
    body = args.get("body", "")

    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    resp = _api("POST", "/users/me/messages/send", json={"raw": raw, "threadId": thread_id})
    if resp.ok:
        mid = resp.json().get("id", "?")
        return ToolResult(True, f"Reply sent. Message ID: {mid}")
    return _ok(resp)


def _label_email(args: Dict[str, Any]) -> ToolResult:
    mid = args["message_id"]
    add = args.get("add_labels", [])
    remove = args.get("remove_labels", [])
    resp = _api("POST", f"/users/me/messages/{mid}/modify", json={"addLabelIds": add, "removeLabelIds": remove})
    return _ok(resp)


def _trash_email(args: Dict[str, Any]) -> ToolResult:
    mid = args["message_id"]
    resp = _api("POST", f"/users/me/messages/{mid}/trash")
    if resp.ok:
        return ToolResult(True, f"Message {mid} moved to trash.")
    return _ok(resp)


def _get_profile(args: Dict[str, Any]) -> ToolResult:
    resp = _api("GET", "/users/me/profile")
    return _ok(resp)


# --------------------------------------------------------------------------
# Registry builder
# --------------------------------------------------------------------------
def register_gmail_tools(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="gmail_profile",
        description="Get the authenticated Gmail account profile (email address, message count, etc.).",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_get_profile,
    ))
    registry.register(Tool(
        name="gmail_send",
        description="Send an email via Gmail.",
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Email body text."},
                "body_type": {"type": "string", "description": "plain or html (default: plain)."},
            },
            "required": ["to", "body"],
        },
        handler=_send_email,
        requires_permission=True,
        previewer=lambda a: f"Send email to {a.get('to','?')}\nSubject: {a.get('subject','(no subject)')}\n{a.get('body','')[:200]}",
    ))
    registry.register(Tool(
        name="gmail_list",
        description="List recent emails, optionally filtered by a Gmail search query.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query e.g. 'from:boss@example.com is:unread'."},
                "count": {"type": "integer", "description": "Max emails to return (default 10, max 50)."},
            },
            "required": [],
        },
        handler=_list_emails,
    ))
    registry.register(Tool(
        name="gmail_read",
        description="Read the full content of a specific email by its message ID.",
        parameters={
            "type": "object",
            "properties": {"message_id": {"type": "string", "description": "Gmail message ID from gmail_list."}},
            "required": ["message_id"],
        },
        handler=_read_email,
    ))
    registry.register(Tool(
        name="gmail_search",
        description="Search Gmail messages using Gmail search syntax.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query."},
                "count": {"type": "integer"},
            },
            "required": ["query"],
        },
        handler=_search_emails,
    ))
    registry.register(Tool(
        name="gmail_reply",
        description="Reply to an email thread.",
        parameters={
            "type": "object",
            "properties": {
                "thread_id": {"type": "string"},
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["thread_id", "to", "body"],
        },
        handler=_reply_email,
        requires_permission=True,
        previewer=lambda a: f"Reply to thread {a.get('thread_id','?')}\n{a.get('body','')[:200]}",
    ))
    registry.register(Tool(
        name="gmail_trash",
        description="Move an email to trash.",
        parameters={
            "type": "object",
            "properties": {"message_id": {"type": "string"}},
            "required": ["message_id"],
        },
        handler=_trash_email,
        requires_permission=True,
        previewer=lambda a: f"Move message {a.get('message_id','?')} to trash.",
    ))
