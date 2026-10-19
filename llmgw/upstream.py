"""IO layer: one HTTP call to one upstream provider.

No routing decision lives here -- this module does not know other providers
exist. It reports failure with a status code and lets the caller decide.
"""
import json
import urllib.error
import urllib.request

from llmgw.config import Provider

# status 0 means "no HTTP response at all": DNS failure, connection refused,
# timeout. Still a broken provider, so the caller must be able to fail over.
CONNECTION_FAILED = 0


class UpstreamError(RuntimeError):
    """An upstream did not answer usefully.

    status is the upstream HTTP status, or CONNECTION_FAILED when the request
    never reached the upstream (dead port, timeout).
    """

    def __init__(self, provider: str, status: int, body: str):
        super().__init__(f"[{provider}] HTTP {status}: {body[:300]}")
        self.provider = provider
        self.status = status
        self.body = body


def call(provider: Provider, messages: list[dict], timeout: int = 180) -> dict:
    """POST the chat history to this provider and return the raw reply."""
    payload = json.dumps({"model": provider.model, "messages": messages}).encode()
    req = urllib.request.Request(
        f"{provider.base_url}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as err:
        body = err.read().decode(errors="replace")
        raise UpstreamError(provider.name, err.code, body) from err
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise UpstreamError(provider.name, CONNECTION_FAILED, str(err)) from err