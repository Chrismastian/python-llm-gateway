"""Pure routing logic: which upstream to try, and when to give up.

No network, no file reading -> every decision here is unit-testable with
hand-made Provider objects. Same split as prompts.py in the previous repo.
"""
from llmgw.config import Provider

# Status codes that mean "this provider is unusable right now, try another".
# 429 = rate limited, 5xx = provider-side failure. All of them can be a
# different answer on a different provider.
#
# 0 is included and is NOT an HTTP status: upstream.py reports it when the
# request never got an answer at all (dead port, refused connection, timeout).
# For failover that is the strongest reason to move on, yet a bare set of HTTP
# codes copied from a retry policy silently excludes it -- the gateway then
# forwards status 0 to the client and the client dies with BadStatusLine.
#
# Deliberately NOT included:
#   401 bad api key  -> the key will be wrong on every provider, fail fast
#   404 unknown model -> the model id will be unknown everywhere, fail fast
FAILOVER_STATUS = {0, 429, 500, 502, 503, 504}


def should_failover(status: int) -> bool:
    """True if this HTTP status means 'try the next provider'."""
    # BLANK-1: anggota himpunan atau bukan. Satu baris: return status ... FAILOVER_STATUS.
    # Operator yang dipakai: in. Tidak perlu loop.
    return status in FAILOVER_STATUS


def pick_provider(providers: list[Provider], tried: set[str]) -> Provider | None:
    """Return the highest-priority provider not yet tried, or None if exhausted.

    `tried` holds the NAMES of providers already attempted for this ONE request.
    The order of `providers` IS the priority, so the first match wins.

    Returning None (instead of raising) keeps the decision pure: the caller
    decides what an exhausted list means -- a 503 with a list of what was tried.
    """
    # BLANK-2: cari provider pertama yang namanya BELUM ada di `tried`.
    #
    # Bentuk yang dibutuhkan:
    #   for provider in providers:          <- jalan satu per satu, urut prioritas
    #       if provider.name not in tried:  <- .name adalah string, `not in` untuk himpunan
    #           return provider             <- yang pertama lolos langsung dikembalikan
    #   return None                         <- loop habis tanpa hasil = semua sudah dicoba
    #
    # Perhatikan: `return None` ada DI LUAR loop (sejajar dengan `for`, bukan di dalamnya).
    # Kalau ditaruh di dalam loop, panggilan pertama yang ternyata sudah dicoba
    # akan langsung menyerah padahal provider lain masih tersedia.
    for provider in providers:
        if provider.name not in tried:
            return provider
    return None


# --- Temporary teaching check. Delete before the public commit. ---
if __name__ == "__main__":
    a = Provider("a", "http://a/v1", "k", "m")
    b = Provider("b", "http://b/v1", "k", "m")
    order = [a, b]
    print("fresh        :", pick_provider(order, set()).name)
    print("a tried      :", pick_provider(order, {"a"}).name)
    print("all tried    :", pick_provider(order, {"a", "b"}))
    print("failover 503 :", should_failover(503))
    print("failover 401 :", should_failover(401))
    print("failover 0   :", should_failover(0), "(no response at all)")