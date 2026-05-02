import yfinance as yf
from datetime import datetime, date

TICKER = "TTWO"

t = yf.Ticker(TICKER)
spot = t.fast_info["last_price"]
expiries = t.options  # tuple of YYYY-MM-DD strings

if not expiries:
    print(f"No options data returned for {TICKER}")
    raise SystemExit(1)

latest_expiry = expiries[-1]
chain = t.option_chain(latest_expiry)
calls = chain.calls

highest_strike = calls["strike"].max()
days_to_expiry = (datetime.strptime(latest_expiry, "%Y-%m-%d").date() - date.today()).days

print(f"=== {TICKER} Options Snapshot ===")
print(f"Spot price:       ${spot:.2f}")
print(f"Latest expiry:    {latest_expiry} ({days_to_expiry} days out)")
print(f"Highest strike:   ${highest_strike:.2f}")
print(f"Total expiries:   {len(expiries)}")
print(f"Calls in chain:   {len(calls)}")
print(f"Run timestamp:    {datetime.now().isoformat()}")
