"""Focused tests for the server-side Hindsight proxy validation and envelopes."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api import hindsight


def _handler():
    return SimpleNamespace(client_address=("127.0.0.1", 1234))


def test_validate_api_url_rejects_local_and_non_https(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_HINDSIGHT_ALLOW_INSECURE", raising=False)
    for value in (
        "file:///etc/passwd",
        "http://127.0.0.1:8787",
        "https://169.254.169.254/latest",
        "https://10.0.0.1",
    ):
        with pytest.raises(ValueError):
            hindsight._validate_api_url(value)


def test_validate_api_url_rejects_private_dns_resolution(monkeypatch):
    monkeypatch.setattr(hindsight.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        hindsight._validate_api_url("https://memory.example")


def test_bank_id_is_strict_and_path_is_quoted(monkeypatch):
    assert hindsight._validate_bank_id("shared-agent-memory") == "shared-agent-memory"
    for value in ("../admin", "bank?x=1", "", "a" * 65):
        with pytest.raises(ValueError):
            hindsight._validate_bank_id(value)
    cfg = {"bank_id": "shared-agent-memory"}
    assert hindsight._bank_path(cfg, "memories/list?limit=1") == "/v1/default/banks/shared-agent-memory/memories/list?limit=1"


def test_hindsight_config_uses_profile_files_not_process_env(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    (home / "hindsight").mkdir(parents=True)
    (home / "hindsight" / "config.json").write_text(
        json.dumps({"api_url": "https://memory.example", "bank_id": "profile-bank"}),
        encoding="utf-8",
    )
    (home / ".env").write_text("HINDSIGHT_API_KEY=profile-key\n", encoding="utf-8")
    monkeypatch.setattr(hindsight, "_active_home", lambda: home)
    monkeypatch.setattr(hindsight.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 443))])
    monkeypatch.setattr(hindsight, "_parse_config", lambda _home: {"api_url": "https://memory.example", "bank_id": "profile-bank"})
    monkeypatch.setattr(hindsight, "_profile_secret", lambda name, _home: "profile-key")
    monkeypatch.setattr(hindsight, "get_config_snapshot", lambda: {"memory": {"provider": "hindsight", "memory_enabled": True}} , raising=False)
    cfg = hindsight._hindsight_config()
    assert cfg["_api_key"] == "profile-key"
    assert cfg["bank_id"] == "profile-bank"
    public = json.dumps({k: v for k, v in cfg.items() if not k.startswith("_")})
    assert "profile-key" not in public


def test_non_json_upstream_is_normalized(monkeypatch):
    class Response:
        status = 200
        headers = {"Content-Type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return b"not json"

    monkeypatch.setattr(hindsight.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    status, body = hindsight._proxy_sync("GET", "/health", "key", "https://memory.example", timeout=1)
    assert status == 502
    assert body == {"detail": "Hindsight returned a non-JSON response"}


def test_recall_input_limits_before_proxy(monkeypatch):
    monkeypatch.setattr(hindsight, "_hindsight_config", lambda: {"enabled": True, "recall_budget": "mid", "_api_key": "key", "api_url": "https://memory.example", "bank_id": "bank"})
    called = False

    def proxy(*args, **kwargs):
        nonlocal called
        called = True
        return 200, {"results": []}

    monkeypatch.setattr(hindsight, "_proxy", proxy)
    # The response helper is intentionally mocked: this test is about the
    # observable validation boundary, not HTTP serialization.
    monkeypatch.setattr("api.helpers.bad", lambda handler, msg, status=400: {"status": status, "error": msg})
    monkeypatch.setattr("api.helpers.j", lambda *args, **kwargs: {"ok": True})
    result = hindsight.handle_recall(_handler(), {"query": "x" * (hindsight.MAX_QUERY_CHARS + 1)})
    assert result["status"] == 400
    assert called is False
