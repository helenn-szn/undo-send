"""Decide whether a tool call is an outward-facing action worth holding.

Pure functions, no Hermes imports, so they are easy to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Tools Hermes or common plugins use to talk to the outside world.
KNOWN_OUTBOUND_TOOLS = {
    "send_message",
    "send_email",
    "email_send",
    "reply_email",
    "post_message",
    "text_to_speech_call",
}

# Verbs that, in a tool name, signal a write to someone else's system.
_WRITE_VERBS = (
    "send", "post", "reply", "publish", "tweet", "email", "message", "notify",
    "create", "delete", "remove", "update", "edit", "book", "schedule",
    "invite", "comment", "merge", "close", "archive", "transfer", "pay",
    "share", "upload", "submit", "cancel",
)
_READ_VERBS = (
    "get", "list", "search", "read", "fetch", "find", "query", "view",
    "describe", "status", "lookup", "show",
)

_TOKEN_SPLIT = re.compile(r"[_\-.:/]+|(?<=[a-z])(?=[A-Z])")

# Shell commands that publish something beyond this machine.
_PUBLISH_PATTERNS = [
    (re.compile(r"\bgit\s+push\b"), "git push"),
    (re.compile(r"\bgh\s+(pr|issue|release)\s+(create|merge|close|comment)\b"), "GitHub change"),
    (re.compile(r"\bgh\s+repo\s+delete\b"), "delete GitHub repo"),
    (re.compile(r"\bnpm\s+publish\b"), "npm publish"),
    (re.compile(r"\btwine\s+upload\b"), "PyPI upload"),
    (re.compile(r"\bcurl\b.*\s-X\s*(POST|PUT|PATCH|DELETE)\b", re.I), "HTTP write"),
]

TERMINAL_TOOLS = {"terminal", "shell_exec", "bash"}


@dataclass
class Rules:
    hold_mcp_writes: bool = True
    hold_terminal_publishes: bool = True
    always_hold: set[str] = field(default_factory=set)
    never_hold: set[str] = field(default_factory=set)


@dataclass
class Decision:
    hold: bool
    label: str = ""


def _tokens(name: str) -> list[str]:
    return [t.lower() for t in _TOKEN_SPLIT.split(name) if t]


def _action_part(tool_name: str) -> str:
    # MCP tools are named mcp__<server>__<tool>; judge the tool part.
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        return parts[-1] if len(parts) >= 3 else tool_name
    return tool_name


def classify(tool_name: str, args: dict | None, rules: Rules) -> Decision:
    args = args or {}
    if tool_name in rules.never_hold:
        return Decision(False)
    if tool_name in rules.always_hold:
        return Decision(True, tool_name)
    if tool_name in KNOWN_OUTBOUND_TOOLS:
        return Decision(True, tool_name)

    if tool_name in TERMINAL_TOOLS:
        if not rules.hold_terminal_publishes:
            return Decision(False)
        cmd = str(args.get("command") or args.get("cmd") or "")
        for pattern, label in _PUBLISH_PATTERNS:
            if pattern.search(cmd):
                return Decision(True, label)
        return Decision(False)

    if tool_name.startswith("mcp__") and rules.hold_mcp_writes:
        toks = _tokens(_action_part(tool_name))
        if toks and toks[0] in _READ_VERBS:
            return Decision(False)
        if any(t in _WRITE_VERBS for t in toks):
            return Decision(True, tool_name)

    return Decision(False)


_URL = re.compile(r"https?://(?:[^@/\s'\"]+@)?([^/\s'\"]+)[^\s'\"]*")
_DATA = re.compile(r"""(?:-d|--data(?:-raw|-binary)?|--json)\s+(?:'([^']*)'|"((?:[^"\\]|\\.)*)"|(\S+))""")
_MSG_KEYS = ("content", "text", "message", "body", "title", "summary")


def _redact(text: str) -> str:
    """Never show full URLs: webhook URLs and query strings carry secrets."""
    return _URL.sub(lambda m: m.group(1), text)


def _curl_summary(cmd: str) -> str | None:
    if "curl" not in cmd:
        return None
    method = re.search(r"-X\s*([A-Z]+)", cmd)
    host = _URL.search(cmd)
    if host:
        dest = host.group(1)
    else:
        # A URL kept in an env var, e.g. "$TEAM_DISCORD" or $env:TEAM_DISCORD
        var = re.search(r"\$(?:env:)?\{?([A-Za-z_][A-Za-z0-9_]*)\}?", cmd)
        if not var:
            return None
        dest = var.group(1).replace("_", " ").lower()
    head = f"{method.group(1) if method else 'POST'} to {dest}"
    data = _DATA.search(cmd)
    if not data:
        return head
    raw = next(g for g in data.groups() if g is not None)
    msg = raw
    try:
        import json
        obj = json.loads(raw.replace('\\"', '"') if raw.startswith("{") and '\\"' in raw else raw)
        if isinstance(obj, dict):
            msg = next((str(obj[k]) for k in _MSG_KEYS if obj.get(k)), raw)
    except Exception:
        pass
    return f"{head}: {msg}"


def summarize(tool_name: str, args: dict | None, label: str) -> str:
    """One short line for the countdown, e.g. 'send_message to #eng: Ship it'."""
    args = args or {}
    cmd = str(args.get("command") or args.get("cmd") or "")
    if cmd:
        nice = _curl_summary(cmd)
        if nice:
            nice = " ".join(_redact(nice).split())
            return nice if len(nice) <= 90 else nice[:87] + "..."
    target = next(
        (str(args[k]) for k in ("to", "recipient", "channel", "chat_id", "target", "email")
         if args.get(k)),
        "",
    )
    body = next(
        (str(args[k]) for k in ("text", "message", "body", "content", "subject", "title", "command")
         if args.get(k)),
        "",
    )
    body = " ".join(_redact(body).split())
    if len(body) > 80:
        body = body[:77] + "..."
    head = label or tool_name
    if target:
        head += f" to {target}"
    return f"{head}: {body}" if body else head
