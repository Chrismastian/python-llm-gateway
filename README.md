# python-llm-gateway

One OpenAI-compatible endpoint in front of many LLM providers, with automatic
failover. Standard library only, no framework, no SDK.

## Why

A single hard-coded model id is a single point of failure: when that provider
runs out of quota or goes down, your app goes down with it. This gateway takes
the request, tries providers in your configured priority order, and only gives
up when every one of them has failed -- reporting which ones were tried and why
the last one failed.

## Provider priority is failover policy

Providers are tried top to bottom. The decision to move on is not "any error":
it is a small allowlist of statuses that can plausibly succeed elsewhere.

| Status | Meaning | Action |
|---|---|---|
| `0` | no response at all (dead port, refused, timeout) | fail over |
| `429` | rate limited | fail over |
| `5xx` | provider-side failure | fail over |
| `401` | bad API key | fail fast -- wrong on every provider |
| `404` | unknown model id | fail fast -- unknown on every provider |

`0` is not an HTTP status. It exists because a request that never reached the
upstream still has to be told apart from a reply: forwarding it as a status
code makes HTTP clients die with `BadStatusLine`.

## Configuration

`providers.json` holds the ordered provider list. It stores the NAME of the
environment variable holding the key, never the key itself, and is gitignored --
so a key cannot be committed by accident.

```json
{
  "providers": [
    {"name": "free-fast", "base_url": "http://127.0.0.1:20128/v1",
     "api_key_env": "LLM_API_KEY", "model": "oc/deepseek-v4.1-flash-free"},
    {"name": "local-combo", "base_url": "http://127.0.0.1:20128/v1",
     "api_key_env": "LLM_API_KEY", "model": "hermes"}
  ]
}
```

```
cp providers.example.json providers.json   # then edit
export LLM_API_KEY=...
export LLMGW_HOST=127.0.0.1 LLMGW_PORT=8080   # optional
export LLMGW_PROVIDERS=providers.json          # optional, path to the list
python -m llmgw.gateway
```

## Endpoints

- `POST /v1/chat/completions` -- same body as any OpenAI-compatible API.
  The reply is the upstream reply, plus a `gateway` field naming the provider
  that answered and the ones already tried.
- `GET /v1/models` -- the configured providers as model ids.

Response headers: `X-Provider` (who answered), `X-Tried` (how many failed first).

Every attempt is logged to stdout as one line, which is what makes a failover
visible instead of silent:

```
[llmgw] listening on http://127.0.0.1:8080/v1  (2 providers)
[llmgw] dead-port failed (0), failing over
[llmgw] provider=free-fast tried=1 tokens=1299
```

When every provider is exhausted the caller gets `503` with the full picture:

```json
{
  "error": {
    "message": "every provider failed",
    "tried": ["dead-a", "dead-b", "out-of-quota"],
    "last_error": "[out-of-quota] HTTP 503: ... You have reached the limit ..."
  }
}
```

## Layout

```
llmgw/config.py    provider list + environment key resolution
llmgw/router.py    pure decision: who is next, is this error worth failing over
llmgw/upstream.py  IO: one HTTP call to one provider
llmgw/gateway.py   stdlib HTTP server + the failover loop
```

## Tests

23 tests, no network and no API key required -- the failover loop is exercised
by patching `upstream.call`, the single function that touches the network.

```
python -m pytest
```

`providers.test.json` (two dead ports) and `providers.exhausted.json` (dead
ports plus an out-of-quota provider) are fixtures for manual run-throughs:

```
LLMGW_PROVIDERS=providers.test.json python -m llmgw.gateway
```

## Limits

- No authentication on the gateway itself: it is meant to run on localhost.
- Each request is routed independently; there is no health memory, so a
  provider that is down is retried on the next request too.
- Non-streaming only.