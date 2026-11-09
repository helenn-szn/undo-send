"""Backend route tests: the Desktop chip's Undo cancels a real held action."""
import importlib.util
import threading
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("_undo_api", ROOT / "dashboard" / "plugin_api.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/plugins/undo-send")
    return TestClient(app), api


def test_chip_undo_cancels_held_action(client):
    c, api = client
    from undo_send.classify import Rules
    from undo_send.hold import Holder
    from undo_send.store import Store

    api._store = None  # fresh store under this test's HERMES_HOME
    agent_store = Store(api.store().path)
    holder = Holder(agent_store, lambda: Rules(), lambda: 3)
    ran, out = [], {}

    def agent():
        out["r"] = holder(tool_name="send_message", args={"to": "boss", "text": "hi"},
                          next_call=lambda a: ran.append(a) or "ok")

    t = threading.Thread(target=agent)
    t.start()
    for _ in range(40):
        items = c.get("/api/plugins/undo-send/pending").json()["items"]
        if items:
            break
        time.sleep(0.05)
    assert items and items[0]["summary"].startswith("send_message to boss")
    assert 0 < items[0]["seconds_left"] <= 3
    r = c.post(f"/api/plugins/undo-send/unsend/{items[0]['id']}").json()
    assert r["ok"] and r["status"] == "cancelled"
    t.join(5)
    assert ran == [] and "cancelled_by_user" in out["r"]
    assert c.get("/api/plugins/undo-send/recent").json()["items"][0]["status"] == "cancelled"


def test_unknown_id_404(client):
    c, _ = client
    assert c.post("/api/plugins/undo-send/unsend/nope").status_code == 404
