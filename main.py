import time

import yfinance as yf
from datetime import datetime, date

TICKER = "TTWO"

# yfinance's default session uses curl_cffi with browser TLS impersonation
# (impersonate="chrome"). Some managed/corporate HTTPS proxies reset that
# impersonated handshake ("curl (35) Recv failure: Connection reset by peer"),
# and a plain session can then hit Yahoo rate limits (HTTP 429) on the default
# "basic" crumb endpoint. To stay portable we try the default path first and,
# on failure, fall back to a proxy-compatible session (no impersonation, a
# real browser User-Agent, and the "csrf" cookie strategy), retrying transient
# rate limits. The printed output is identical either way.

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


def _proxy_session():
    """A proxy-friendly yfinance session, or None if unavailable."""
    try:
        from curl_cffi import requests as _cr
        s = _cr.Session()  # no impersonate -> survives MITM proxies
    except Exception:
        try:
            import requests as _rq
            s = _rq.Session()
        except Exception:
            return None
    try:
        s.headers.update({
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
    except Exception:
        pass
    return s


def _fetch(session=None, force_csrf=False):
    """Return (spot, expiries, latest_expiry, calls) for TICKER."""
    t = yf.Ticker(TICKER, session=session) if session is not None else yf.Ticker(TICKER)
    if force_csrf:
        try:
            t._data._cookie_strategy = 'csrf'
        except Exception:
            pass
    spot = t.fast_info["last_price"]
    expiries = t.options
    if not expiries:
        return spot, expiries, None, None
    latest_expiry = expiries[-1]
    calls = t.option_chain(latest_expiry).calls
    return spot, expiries, latest_expiry, calls


def _get_snapshot():
    last_err = None
    # First attempt: yfinance defaults (works in unrestricted environments).
    try:
        return _fetch()
    except Exception as e:
        last_err = e
    # Fallback: proxy-compatible session + csrf strategy, with backoff on 429.
    for attempt in range(6):
        try:
            return _fetch(session=_proxy_session(), force_csrf=True)
        except Exception as e:
            last_err = e
            time.sleep(4 * (attempt + 1))
    raise last_err


spot, expiries, latest_expiry, calls = _get_snapshot()

if not expiries:
    print(f"No options data returned for {TICKER}")
    raise SystemExit(1)

highest_strike = calls["strike"].max()
days_to_expiry = (datetime.strptime(latest_expiry, "%Y-%m-%d").date() - date.today()).days

print(f"=== {TICKER} Weekly Options Snapshot ===")
print(f"Run timestamp:    {datetime.now().isoformat()}")
print(f"")
print(f"Spot price:       ${spot:.2f}")
print(f"Latest expiry:    {latest_expiry} ({days_to_expiry} days out)")
print(f"Highest strike:   ${highest_strike:.2f}")
print(f"Total expiries:   {len(expiries)}")
print(f"Calls in chain:   {len(calls)}")
