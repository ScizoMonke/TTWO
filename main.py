import os

import requests
import yfinance as yf
from datetime import datetime, date

TICKER = "TTWO"


def _session():
    # yfinance's default backend (curl_cffi) impersonates a browser's TLS
    # fingerprint. A policy-enforcing egress proxy that re-terminates TLS
    # (e.g. Claude Code on the web) can't tunnel that fingerprint and resets
    # the connection. When a proxy is configured, fall back to a plain requests
    # session, which honors HTTPS_PROXY / REQUESTS_CA_BUNDLE from the
    # environment. With no proxy set (local runs) return None so yfinance uses
    # its default, impersonating session.
    if not (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")):
        return None
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    return s


t = yf.Ticker(TICKER, session=_session())
spot = t.fast_info["last_price"]
expiries = t.options

if not expiries:
    print(f"No options data returned for {TICKER}")
    raise SystemExit(1)

latest_expiry = expiries[-1]
chain = t.option_chain(latest_expiry)
calls = chain.calls

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
