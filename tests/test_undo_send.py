"""Offline tests: simulate Hermes calling the middleware. No Hermes needed.

Run from inside this tests/ folder (it has its own pytest.ini):
    cd tests && python -m pytest -q
"""

import json
import threading
import time

import pytest

import undo_send as pkg
from undo_send import commands
from undo_send.classify import Rules, classify  # noqa: E402
from undo_send.hold import Holder  # noqa: E402
from undo_send.store import Store  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store(tmp_path / "p.db")
    clock = FakeClock()
    monkeypatch.setattr("undo_send.store.time.time", clock.now)
    s.clock = clock
    return s


def make_holder(store, window=20, on_tick=None):
    clock = store.clock

    def sleep(sec):
        clock.sleep(sec)
        if on_tick:
            on_tick(clock.t)

    return Holder(store, lambda: Rules(), lambda: window, sleep=sleep, clock=clock.now)


def call(holder, tool, args):
    ran = []

    def next_call(a):
        ran.append(a)
        return json.dumps({"ok": True})

    out = holder(tool_name=tool, args=args, original_args=args, next_call=next_call)
    return out, ran


# --- classification ---------------------------------------------------------

@pytest.mark.parametrize("tool,args,hold", [
    ("send_message", {"to": "boss", "text": "hi"}, True),
    ("read_file", {"path": "a.txt"}, False),
    ("web_search", {"query": "x"}, False),
    ("mcp__slack__post_message", {}, True),
    ("mcp__linear__create_issue", {}, True),
    ("mcp__linear__list_issues", {}, False),
    ("mcp__gcal__get_event", {}, False),
    ("mcp__gcal__deleteEvent", {}, True),
    ("terminal", {"command": "git push origin main"}, True),
    ("terminal", {"command": "git status"}, False),
    ("terminal", {"command": "gh pr create --fill"}, True),
    ("terminal", {"command": "curl -X POST https://api.x.com/v1"}, True),
])
def test_classify(tool, args, hold):
    assert classify(tool, args, Rules()).hold is hold


def test_never_hold_wins():
    assert not classify("send_message", {}, Rules(never_hold={"send_message"})).hold


# --- the grace window ---------------------------------------------------------

def test_read_only_runs_immediately(store):
    out, ran = call(make_holder(store), "read_file", {"path": "x"})
    assert ran and json.loads(out)["ok"]
    assert store.recent() == []


def test_outbound_waits_then_sends(store):
    start = store.clock.t
    out, ran = call(make_holder(store, window=20), "send_message", {"to": "boss", "text": "hi"})
    assert ran == [{"to": "boss", "text": "hi"}]
    assert store.clock.t - start >= 20
    assert store.recent()[0]["status"] == "sent"


def test_undo_cancels_before_send(store):
    def on_tick(t):
        p = store.latest_pending()
        if p and t > 1005:
            assert "Undone" in commands.undo(store, "")

    out, ran = call(make_holder(store, window=20, on_tick=on_tick),
                    "send_message", {"to": "boss", "text": "embarrassing"})
    assert ran == []
    assert json.loads(out)["status"] == "cancelled_by_user"
    assert store.recent()[0]["status"] == "cancelled"


def test_send_now_skips_wait(store):
    start = store.clock.t

    def on_tick(t):
        p = store.latest_pending()
        if p:
            commands.send_now(store, p["id"])

    out, ran = call(make_holder(store, window=60, on_tick=on_tick), "send_message", {"text": "x"})
    assert ran and store.clock.t - start < 2


def test_undo_after_send_is_too_late(store):
    call(make_holder(store, window=1), "send_message", {"text": "x"})
    aid = store.recent()[0]["id"]
    assert "Too late" in commands.undo(store, aid)


def test_failed_tool_is_recorded_and_raised(store):
    h = make_holder(store, window=1)

    def boom(a):
        raise RuntimeError("smtp down")

    with pytest.raises(RuntimeError):
        h(tool_name="send_message", args={}, next_call=boom)
    assert store.recent()[0]["status"] == "failed"


def test_classifier_error_fails_open(store):
    h = Holder(store, lambda: (_ for _ in ()).throw(ValueError()), lambda: 20)
    out, ran = call(h, "send_message", {"text": "x"})
    assert ran


class _Src:
    platform = "telegram"
    chat_id = "42"


class _Event:
    def __init__(self, text):
        self.text, self.source, self.message_id = text, _Src(), "m1"


class _Adapter:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append((chat_id, content, reply_to))


class _Gateway:
    def __init__(self, allowed=True):
        self.allowed, self.adapters = allowed, {"telegram": _Adapter()}

    def _is_user_authorized(self, source):
        return self.allowed


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_gateway_undo_reply(store):
    hook = commands.gateway_hook(store)
    gw = _Gateway()
    assert _run(hook(event=_Event("undo"), gateway=gw)) is None  # nothing pending
    store.add("send_message", "send_message to boss: hi", 20)
    assert _run(hook(event=_Event("hello there"), gateway=gw)) is None
    res = _run(hook(event=_Event(" Undo "), gateway=gw))
    assert res["action"] == "skip"
    assert store.recent()[0]["status"] == "cancelled"
    chat, msg, reply_to = gw.adapters["telegram"].sent[0]
    assert chat == "42" and "Undone" in msg and reply_to == "m1"


def test_gateway_undo_refuses_strangers(store):
    hook = commands.gateway_hook(store)
    store.add("send_message", "send_message to boss: hi", 20)
    assert _run(hook(event=_Event("undo"), gateway=_Gateway(allowed=False))) is None
    assert _run(hook(event=_Event("undo"), gateway=object())) is None  # can't check: fail closed
    assert store.pending(), "a stranger must not cancel your actions"

def test_cross_process_race_real_threads(tmp_path):
    """Real clock + real threads: Undo from another 'process' wins."""
    s = Store(tmp_path / "race.db")
    h = Holder(s, lambda: Rules(), lambda: 1.5)
    result = {}

    def agent():
        result["out"], result["ran"] = call(h, "send_message", {"text": "x"})

    t = threading.Thread(target=agent)
    t.start()
    for _ in range(40):
        if s.pending():
            break
        time.sleep(0.05)
    other = Store(tmp_path / "race.db")  # separate connection, like the Desktop route
    assert "Undone" in commands.undo(other, "")
    t.join(5)
    assert result["ran"] == []


def test_register_with_fake_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    class Ctx:
        def __init__(self):
            self.mw, self.cmds, self.hooks = {}, {}, {}

        def get_config(self, key, default=None):
            return default

        def register_middleware(self, kind, fn):
            self.mw[kind] = fn

        def register_command(self, name, fn, description=""):
            self.cmds[name] = fn

        def register_hook(self, name, fn):
            self.hooks[name] = fn

    ctx = Ctx()
    pkg.register(ctx)
    assert "tool_execution" in ctx.mw
    assert set(ctx.cmds) == {"unsend", "sendnow", "undo-send"}
    assert "pre_gateway_dispatch" in ctx.hooks
    assert ctx.cmds["undo-send"]("") == "Nothing held yet."


def test_debug_listing_shows_seen_calls(store):
    h = make_holder(store, window=1)
    call(h, "read_file", {"path": "x"})
    out = commands.listing(store, "debug", h)
    assert "read_file: passed" in out and "args=['path']" in out


@pytest.mark.parametrize("a,kw,want", [
    (("debug",), {}, "debug"),
    (("/undo-send debug",), {}, "debug"),
    ((["debug"],), {}, "debug"),
    ((), {"raw_args": "debug"}, "debug"),
    ((), {}, ""),
    (("undo-send",), {}, ""),
])
def test_parse_arg(a, kw, want):
    assert commands.parse_arg("undo-send", a, kw) == want


from undo_send.classify import summarize  # noqa: E402

HOOK = "https://discord.com/api/webhooks/123456/SECRETtoken_abc"


@pytest.mark.parametrize("cmd,want", [
    (f"""curl -X POST -H "Content-Type: application/json" -d '{{"content":"I am out 👋"}}' {HOOK}""",
     "POST to discord.com: I am out 👋"),
    (f"""curl -X POST -H 'Content-Type: application/json' -d "{{\\"content\\":\\"Ship it\\"}}" {HOOK}""",
     "POST to discord.com: Ship it"),
    ("curl -X POST https://httpbin.org/post -d hello", "POST to httpbin.org: hello"),
    (f"curl -X DELETE {HOOK}", "DELETE to discord.com"),
])
def test_curl_summary_hides_secrets(cmd, want):
    out = summarize("terminal", {"command": cmd}, "HTTP write")
    assert out == want
    assert "SECRET" not in out and "webhooks" not in out


def test_git_push_summary_redacts_url():
    out = summarize("terminal", {"command": "git push https://user:tok@github.com/a/b main"}, "git push")
    assert "tok" not in out and "github.com" in out


def test_curl_env_var_target():
    cmd = """curl -X POST -H "Content-Type: application/json" -d '{"content":"I quit 👋"}' "$TEAM_DISCORD\""""
    assert summarize("terminal", {"command": cmd}, "HTTP write") == "POST to team discord: I quit 👋"
    ps = """curl.exe -X POST -d '{"content":"hi"}' $env:TEAM_DISCORD"""
    assert summarize("terminal", {"command": ps}, "HTTP write") == "POST to team discord: hi"
