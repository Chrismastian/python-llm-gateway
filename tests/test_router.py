"""Tests for the pure routing decisions. No network, no config file."""
import pytest

from llmgw.config import Provider
from llmgw.router import should_failover, pick_provider, FAILOVER_STATUS


def make(name: str) -> Provider:
    return Provider(name=name, base_url=f"http://{name}/v1", api_key="k", model="m")


@pytest.mark.parametrize("status", sorted(FAILOVER_STATUS))
def test_failover_statuses_are_retryable_elsewhere(status):
    assert should_failover(status) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_side_errors_never_fail_over(status):
    # The same wrong key or unknown model id will be wrong everywhere: fail fast.
    assert should_failover(status) is False


def test_status_zero_fails_over():
    # 0 is not HTTP: the request never reached the upstream at all.
    # Without this, a dead port would be forwarded to the client as status 0
    # and the client would die with http.client.BadStatusLine.
    assert should_failover(0) is True


def test_pick_provider_follows_file_order():
    providers = [make("first"), make("second"), make("third")]
    assert pick_provider(providers, set()).name == "first"


def test_pick_provider_skips_already_tried():
    providers = [make("first"), make("second")]
    assert pick_provider(providers, {"first"}).name == "second"


def test_pick_provider_returns_none_when_exhausted():
    providers = [make("first"), make("second")]
    assert pick_provider(providers, {"first", "second"}) is None


def test_pick_provider_returns_none_for_empty_list():
    assert pick_provider([], set()) is None