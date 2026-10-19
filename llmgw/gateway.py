"""Gateway server: one OpenAI-compatible endpoint in front of many providers.

The client sends the same request it would send to any OpenAI-compatible API
and does not learn which upstream answered -- except through the X-Provider
header, which exists for debugging, not for the caller to depend on.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llmgw import config, router, upstream

# Loaded in main(). Kept as a module-level name so tests can swap the list
# without touching the filesystem, and so importing this module never requires
# a config file to exist (CI has none: providers.json is gitignored).
PROVIDERS: list[config.Provider] = []


def handle_chat(body: dict) -> tuple[int, dict, dict]:
    """Try providers in priority order. Returns (status, payload, headers)."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return 400, {"error": {"message": "'messages' must be a non-empty list"}}, {}

    tried: set[str] = set()
    last: upstream.UpstreamError | None = None
    while (provider := router.pick_provider(PROVIDERS, tried)) is not None:
        try:
            reply = upstream.call(provider, messages)
        except upstream.UpstreamError as err:
            if not router.should_failover(err.status):
                # Fail fast: a bad key or unknown model will be just as wrong
                # on the next provider, so passing it through is honest and
                # saves the caller the wait.
                return err.status, {"error": {"message": err.body, "provider": err.provider}}, {}
            tried.add(provider.name)
            last = err
            print(f"[llmgw] {provider.name} failed ({err.status}), failing over", flush=True)
            continue
        reply["gateway"] = {"provider": provider.name, "tried": sorted(tried)}
        print(
            f"[llmgw] provider={provider.name} tried={len(tried)} "
            f"tokens={reply.get('usage', {}).get('total_tokens', 0)}",
            flush=True,
        )
        return 200, reply, {"X-Provider": provider.name, "X-Tried": str(len(tried))}

    return (
        503,
        {
            "error": {
                "message": "every provider failed",
                "tried": sorted(tried),
                "last_error": str(last) if last else None,
            }
        },
        {},
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": {"message": f"unknown path {self.path}"}})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"error": {"message": "body is not valid JSON"}})
            return
        status, payload, headers = handle_chat(body)
        self._send(status, payload, headers)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path == "/v1/models":
            self._send(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": p.name, "object": "model", "model": p.model}
                        for p in PROVIDERS
                    ],
                },
            )
        else:
            self._send(404, {"error": {"message": f"unknown path {self.path}"}})

    def _send(self, status: int, payload: dict, headers: dict | None = None) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        pass  # the [llmgw] line above is the log that matters


def main() -> None:
    global PROVIDERS
    PROVIDERS = config.load_providers()
    port = int(os.environ.get("LLMGW_PORT", "8080"))
    host = os.environ.get("LLMGW_HOST", "127.0.0.1")
    print(f"[llmgw] listening on http://{host}:{port}/v1  ({len(PROVIDERS)} providers)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()