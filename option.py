import json
import requests
import os
import math
from datetime import datetime
from scipy.stats import norm
from scipy.optimize import brentq
from concurrent.futures import ThreadPoolExecutor, as_completed
from connectors.deribit import fetch as fetch_deribit
import analyze_iv

def get_deribit_positions():
    try:
        deribit_data = fetch_deribit()
        positions = deribit_data.get("open_positions", [])
    except Exception as e:
        print("Deribit positions error:", e)
        return []

    # Enrich option positions with live Greeks (vega, theta, gamma) via ticker API
    def enrich(pos):
        inst = pos.get("instrument_name", "")
        if not (inst.endswith("-C") or inst.endswith("-P")):
            return pos
        try:
            r = requests.get("https://www.deribit.com/api/v2/public/ticker",
                             params={"instrument_name": inst}, timeout=8)
            d = r.json().get("result", {})
            pos["mark_price"]  = d.get("mark_price", pos.get("mark_price"))
            pos["mark_iv"]     = d.get("mark_iv")
            pos["greeks"]      = d.get("greeks", {})
            pos["index_price"] = d.get("index_price", pos.get("index_price"))
        except Exception:
            pass
        return pos

    print(f"  Fetching live Greeks for {len(positions)} positions...")
    with ThreadPoolExecutor(max_workers=10) as ex:
        positions = list(ex.map(enrich, positions))
    return positions

def get_all_binance_options():
    url = "https://eapi.binance.com/eapi/v1/ticker"
    try:
        resp = requests.get(url, timeout=15)
        all_options = resp.json()
        return [o for o in all_options if isinstance(o, dict) and o.get("symbol", "").startswith("BTC")]
    except Exception as e:
        print("Binance options error:", e)
        return []

# ---------- Greeks helpers ----------

def _bs_price(S, K, T, sigma, opt_type):
    """Black-Scholes option price (no risk-free rate for crypto)."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0) if opt_type == "C" else max(K - S, 0)
    d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "C":
        return S * norm.cdf(d1) - K * norm.cdf(d2)
    else:
        return K * norm.cdf(-d2) - S * norm.cdf(-d1)

def _bs_greeks(S, K, T, sigma, opt_type):
    """Return delta, gamma, vega (per 1% IV), theta (per day) via BS."""
    if T <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    delta = norm.cdf(d1) if opt_type == "C" else -norm.cdf(-d1)
    gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
    vega  = S * norm.pdf(d1) * math.sqrt(T) / 100   # USD per 1% IV change
    theta = (-(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))) / 365
    return {"delta": round(delta, 5), "gamma": round(gamma, 8),
            "vega": round(vega, 4), "theta": round(theta, 4)}

def _implied_vol(price, S, K, T, opt_type):
    """Bisection-method IV. Returns None on failure."""
    try:
        return brentq(lambda v: _bs_price(S, K, T, v, opt_type) - price, 0.005, 10.0, xtol=1e-6)
    except Exception:
        return None

def _parse_deribit_expiry(expiry_str):
    """'26JUN26'  ->  datetime(2026, 6, 26)"""
    try:
        return datetime.strptime(expiry_str, "%d%b%y")
    except Exception:
        return None

def _add_greeks_deribit(opt, today=None):
    """
    Enrich a Deribit book-summary record with BS Greeks using mark_iv.
    Greeks are added under the key 'greeks'.
    """
    if today is None:
        today = datetime.now(tz=__import__('datetime').timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    name = opt.get("instrument_name", "")
    parts = name.split("-")
    if len(parts) != 4:
        return opt
    expiry_dt = _parse_deribit_expiry(parts[1])
    if expiry_dt is None:
        return opt
    T = max((expiry_dt - today).days / 365.0, 1e-6)
    S = opt.get("underlying_price") or opt.get("estimated_delivery_price")
    if not S:
        return opt
    K_str = parts[2]
    opt_type = parts[3]  # "C" or "P"
    try:
        K = float(K_str)
    except ValueError:
        return opt
    iv = opt.get("mark_iv")
    if not iv:
        # fallback: derive IV from mark_price (BTC-denominated -> convert to USD)
        mark_btc = opt.get("mark_price")
        if mark_btc and S:
            mark_usd = mark_btc * S
            iv_raw = _implied_vol(mark_usd, S, K, T, opt_type)
            iv = iv_raw * 100 if iv_raw else None
    if not iv:
        return opt
    sigma = iv / 100.0
    opt["greeks"] = _bs_greeks(S, K, T, sigma, opt_type)
    return opt

def _add_greeks_binance(opt, today=None):
    """
    Enrich a Binance ticker record with BS Greeks derived from mid price.
    Greeks added under key 'greeks'; implied_iv (%) added as 'mark_iv'.
    Symbol format: BTC-YYMMDD-STRIKE-TYPE  e.g. BTC-260619-70000-P
    """
    if today is None:
        today = datetime.now(tz=__import__('datetime').timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    sym = opt.get("symbol", "")
    parts = sym.split("-")
    if len(parts) != 4:
        return opt
    try:
        expiry_dt = datetime.strptime(parts[1], "%y%m%d")
    except ValueError:
        return opt
    T = max((expiry_dt - today).days / 365.0, 1e-6)
    S = float(opt.get("exercisePrice") or 0)
    if not S:
        return opt
    K = float(opt.get("strikePrice") or 0)
    if not K:
        return opt
    opt_type = parts[3]  # "C" or "P"
    bid = float(opt.get("bidPrice") or 0)
    ask = float(opt.get("askPrice") or 0)
    last = float(opt.get("lastPrice") or 0)
    mid = (bid + ask) / 2 if bid and ask else (bid or ask or last)
    if not mid:
        return opt
    iv_raw = _implied_vol(mid, S, K, T, opt_type)
    if not iv_raw:
        return opt
    opt["mark_iv"] = round(iv_raw * 100, 2)
    opt["greeks"] = _bs_greeks(S, K, T, iv_raw, opt_type)
    return opt

# ---------- Deribit options with Greeks ----------

def get_all_deribit_options():
    options = []
    try:
        url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
        resp = requests.get(url, params={"currency": "BTC", "kind": "option"}, timeout=15)
        data = resp.json().get("result", [])
        options.extend(data)
    except Exception as e:
        print(f"Error fetching Deribit BTC: {e}")
        return options

    print(f"  Adding Greeks to {len(options)} Deribit options...")
    today = datetime.now(tz=__import__('datetime').timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    options = [_add_greeks_deribit(o, today) for o in options]
    return options

def main():
    os.makedirs("option", exist_ok=True)
    print("Fetching Deribit positions...")
    positions = get_deribit_positions()
    with open(os.path.join("option", "deribit_positions.json"), "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)
    print(f"Saved {len(positions)} Deribit positions to option/deribit_positions.json")
    
    print("Fetching Binance options...")
    binance_options = get_all_binance_options()
    print(f"  Adding Greeks to {len(binance_options)} Binance options...")
    today = datetime.now(tz=__import__('datetime').timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    binance_options = [_add_greeks_binance(o, today) for o in binance_options]
    with open(os.path.join("option", "binance_options.json"), "w", encoding="utf-8") as f:
        json.dump(binance_options, f, indent=2)
    print(f"Saved {len(binance_options)} Binance options to option/binance_options.json")
    
    print("Fetching Deribit options...")
    deribit_options = get_all_deribit_options()
    with open(os.path.join("option", "deribit_options.json"), "w", encoding="utf-8") as f:
        json.dump(deribit_options, f, indent=2)
    print(f"Saved {len(deribit_options)} Deribit options to option/deribit_options.json")

    print("\n" + "="*50)
    print("Running IV Analysis...")
    print("="*50)
    analyze_iv.main()

if __name__ == "__main__":
    main()
