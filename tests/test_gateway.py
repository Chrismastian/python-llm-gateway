"""Tests for the gateway's failover loop, with the network faked out.

upstream.call is the only thing that touches the network, so patching that one
function lets the whole failover decision be tested in milliseconds.
"""
import pytest

from llmgw import gateway, upstream
from llmgw.config import Provider


def provider(name: str) -> Provider:
    return Provider(name=name, base_url=f"http://{name}/v1", api_key="k", model="m")


REPLY = {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 7}}


@pytest.fixture
def two_providers(monkeypatch):
    monkeypatch.setattr(gateway, "PROVIDERS", [provider("first"), provider("second")])


def test_rejects_empty_messages():
    status, payload, _ = gateway.handle_chat({"messages": []})
    assert status == 400
    assert "non-empty list" in payload["error"]["message"]


def test_rejects_missing_messages():
    status, _, _ = gateway.handle_chat({"question": "hi"})
    assert status == 400


def test_happy_path_uses_first_provider(two_providers, monkeypatch):
    monkeypatch.setattr(upstream, "call", lambda p, m: REPLY)
    status, payload, headers = gateway.handle_chat({"messages": [{"role": "user"}]})
    assert status == 200
    assert headers["X-Provider"] == "first"
    assert payload["gateway"]["tried"] == []


def test_fails_over_on_retryable_error(two_providers, monkeypatch):
    def fake(provider_, messages):
        if provider_.name == "first":
            raise upstream.UpstreamError("first", 503, "upstream is down")
        return REPLY

    monkeypatch.setattr(upstream, "call", fake)
    status, payload, headers = gateway.handle_chat({"messages": [{"role": "user"}]})
    assert status == 200
    assert headers["X-Provider"] == "second"
    assert payload["gateway"]["tried"] == ["first"]


def test_fails_over_on_dead_port(two_providers, monkeypatch):
    # status 0 = no response at all; this is the case that produced
    # http.client.BadStatusLine before status 0 was in FAILOVER_STATUS.
    def fake(provider_, messages):
        if provider_.name == "first":
            raise upstream.UpstreamError("first", 0, "connection refused")
        return REPLY

    monkeypatch.setattr(upstream, "call", fake)
    status, _, headers = gateway.handle_chat({"messages": [{"role": "user"}]})
    assert status == 200
    assert headers["X-Provider"] == "second"


def test_bad_key_fails_fast_without_touching_other_providers(two_providers, monkeypatch):
    calls = []

    def fake(provider_, messages):
        calls.append(provider_.name)
        raise upstream.UpstreamError(provider_.name, 401, "Invalid API key")

    monkeypatch.setattr(upstream, "call", fake)
    status, payload, _ = gateway.handle_chat({"messages": [{"role": "user"}]})
    assert status == 401
    assert calls == ["first"]  # the second provider was never called
    assert payload["error"]["provider"] == "first"


def test_all_providers_failing_reports_each_one(two_providers, monkeypatch):
    monkeypatch.setattr(
        upstream,
        "call",
        lambda p, m: (_ for _ in ()).throw(upstream.UpstreamError(p.name, 503, "down")),
    )
    status, payload, _ = gateway.handle_chat({"messages": [{"role": "user"}]})
    assert status == 503
    assert payload["error"]["tried"] == ["first", "second"]
    assert "503" in payload["error"]["last_error"]