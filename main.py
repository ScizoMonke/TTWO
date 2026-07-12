"""TTWO weekly options snapshot.

Fetches the current spot price and the furthest-dated options expiry for
Take-Two Interactive (TTWO) from Yahoo Finance and prints a plain-text snapshot.

This script is designed to run unattended -- e.g. a weekly Claude Code routine
whose stdout is captured and emailed -- so it is deliberately defensive about
the two failure modes that show up in that environment:

  1. Proxy / TLS.  yfinance's default backend (curl_cffi) impersonates a
     browser's TLS fingerprint. A policy-enforcing egress proxy that
     re-terminates TLS (e.g. Claude Code on the web) cannot tunnel that
     fingerprint and resets the connection. When an HTTPS proxy is configured we
     hand yfinance a plain requests session instead, which traverses the proxy
     normally and honors HTTPS_PROXY / REQUESTS_CA_BUNDLE from the environment.

  2. Rate limiting.  Yahoo intermittently returns HTTP 429 for its cookie/crumb
     and options endpoints, especially from a shared egress IP. Every network
     call is wrapped in a bounded exponential-backoff retry so a transient
     throttle turns into an eventual success rather than a hard failure. If the
     data still can't be fetched, a readable error line is printed to stdout so
     the emailed snapshot explains the problem instead of arriving empty.

Behaviour is tunable via environment variables (all optional):
  SNAPSHOT_TICKER        ticker symbol to report on          (default: TTWO)
  SNAPSHOT_MAX_ATTEMPTS  attempts per network call           (default: 6)
  SNAPSHOT_BASE_DELAY    first backoff delay, seconds        (default: 5)
  SNAPSHOT_MAX_DELAY     backoff cap, seconds                (default: 60)
"""

import os
import random
import sys
import time
from datetime import date, datetime

import requests
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

TICKER = os.environ.get("SNAPSHOT_TICKER", "TTWO")

# Retry tuning. Defaults give ~5+10+20+40+60s of backoff across 6 attempts,
# comfortably covering a brief Yahoo throttle without stalling a weekly run.
MAX_ATTEMPTS = int(os.environ.get("SNAPSHOT_MAX_ATTEMPTS", "6"))
BASE_DELAY = float(os.environ.get("SNAPSHOT_BASE_DELAY", "5"))  # seconds
MAX_DELAY = float(os.environ.get("SNAPSHOT_MAX_DELAY", "60"))  # seconds

# Failures worth retrying: Yahoo rate limits (429) and transient network faults
# raised by the requests backend (connection resets, timeouts, DNS blips).
# Anything else is treated as a real error and surfaces immediately.
RETRYABLE_ERRORS = (YFRateLimitError, requests.exceptions.RequestException)


def build_session():
    """Return a requests session when a proxy is configured, else None.

    yfinance's default curl_cffi session impersonates a browser TLS fingerprint
    that a re-terminating egress proxy cannot tunnel (connection reset). A plain
    requests session goes through the proxy and reads HTTPS_PROXY /
    REQUESTS_CA_BUNDLE from the environment. With no proxy set (local runs) we
    return None so yfinance keeps its default, impersonating session, which
    Yahoo is less likely to rate-limit.
    """
    if not (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")):
        return None
    session = requests.Session()
    # A real browser User-Agent makes Yahoo a little less trigger-happy with 429s
    # for the plain-requests (non-impersonated) client.
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    return session


def with_retries(label, fn):
    """Call ``fn()`` with bounded exponential backoff + jitter on transient errors.

    Yahoo throttling and brief network faults are common on autonomous runs;
    retrying turns most of them into an eventual success. Re-raises the last
    error if every attempt is exhausted so the caller can report the failure.
    """
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except RETRYABLE_ERRORS as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS:
                break
            # Exponential backoff (BASE, 2x, 4x, ... capped at MAX_DELAY) with up
            # to 25% jitter so parallel runs don't retry in lockstep against the
            # same shared-IP rate limit.
            delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
            delay += random.uniform(0, delay * 0.25)
            print(
                f"[retry] {label} failed "
                f"(attempt {attempt}/{MAX_ATTEMPTS}): "
                f"{type(exc).__name__}: {exc}. Retrying in {delay:.1f}s...",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise last_error


def get_spot(ticker):
    """Return the latest price, falling through several fields for robustness.

    ``fast_info['last_price']`` is the cheapest source but is occasionally absent
    in a sparse response; ``.info`` fields are slower but more reliable
    fallbacks, so a single thin response doesn't sink the run. A rate-limit or
    network error propagates to the caller's retry loop rather than being
    swallowed here.
    """
    fast = ticker.fast_info
    try:
        price = fast["last_price"]
    except (KeyError, TypeError):
        price = None
    if price:
        return float(price)

    info = ticker.info or {}
    for key in ("regularMarketPrice", "currentPrice", "previousClose"):
        value = info.get(key)
        if value:
            return float(value)

    raise RuntimeError("no spot price available from fast_info or info")


def build_snapshot():
    """Fetch the data and return the formatted snapshot as a string.

    Each network access is individually retried so a throttle on one endpoint
    doesn't force a re-fetch of endpoints that already succeeded.
    """
    ticker = yf.Ticker(TICKER, session=build_session())

    spot = with_retries("spot price", lambda: get_spot(ticker))

    expiries = with_retries("options expiries", lambda: ticker.options)
    if not expiries:
        raise RuntimeError(f"no options expiries returned for {TICKER}")

    # Furthest-dated expiry -- the snapshot tracks the longest-dated chain.
    latest_expiry = expiries[-1]
    chain = with_retries(
        "option chain", lambda: ticker.option_chain(latest_expiry)
    )
    calls = chain.calls
    if calls is None or calls.empty:
        raise RuntimeError(f"no calls in the {latest_expiry} chain for {TICKER}")

    highest_strike = calls["strike"].max()
    days_to_expiry = (
        datetime.strptime(latest_expiry, "%Y-%m-%d").date() - date.today()
    ).days

    return "\n".join(
        [
            f"=== {TICKER} Weekly Options Snapshot ===",
            f"Run timestamp:    {datetime.now().isoformat()}",
            "",
            f"Spot price:       ${spot:.2f}",
            f"Latest expiry:    {latest_expiry} ({days_to_expiry} days out)",
            f"Highest strike:   ${highest_strike:.2f}",
            f"Total expiries:   {len(expiries)}",
            f"Calls in chain:   {len(calls)}",
        ]
    )


def main():
    try:
        print(build_snapshot())
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level guard for unattended runs
        # Emit a readable failure snapshot to stdout so an emailed report
        # explains what went wrong (e.g. persistent rate limiting) instead of
        # arriving empty, and return non-zero for logs/alerting. The detailed
        # traceback still goes to stderr.
        import traceback

        traceback.print_exc()
        print(f"=== {TICKER} Weekly Options Snapshot ===")
        print(f"Run timestamp:    {datetime.now().isoformat()}")
        print("")
        print(f"ERROR: snapshot unavailable: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
