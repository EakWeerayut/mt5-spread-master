"""
Binance Futures market data — all active USDT perpetual symbols.
Uses public REST API (no API key required).
"""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

FAPI = "https://fapi.binance.com"


def _get_symbols() -> list[str]:
    resp = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=15)
    resp.raise_for_status()
    return sorted(
        s["symbol"]
        for s in resp.json()["symbols"]
        if s["symbol"].endswith("USDT")
        and s["status"] == "TRADING"
        and s.get("contractType") == "PERPETUAL"
    )


def _get_prices() -> dict[str, float]:
    resp = requests.get(f"{FAPI}/fapi/v1/ticker/price", timeout=15)
    resp.raise_for_status()
    return {item["symbol"]: float(item["price"]) for item in resp.json()}


def _get_30d_volume(symbol: str) -> tuple[str, float]:
    resp = requests.get(
        f"{FAPI}/fapi/v1/klines",
        params={"symbol": symbol, "interval": "1d", "limit": 30},
        timeout=10,
    )
    resp.raise_for_status()
    # k[7] = quote asset volume (USDT)
    vol = sum(float(k[7]) for k in resp.json())
    return symbol, vol


def fetch() -> dict:
    print("  [MarketBinance] Fetching exchange info...")
    symbols = _get_symbols()
    print(f"  [MarketBinance] {len(symbols)} active USDT perpetual symbols")

    print("  [MarketBinance] Fetching current prices...")
    price_map = _get_prices()

    print(f"  [MarketBinance] Fetching 30d volume ({len(symbols)} symbols, parallel)...")
    vol_map: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_get_30d_volume, s): s for s in symbols}
        done = 0
        for f in as_completed(futures):
            try:
                sym, vol = f.result()
                vol_map[sym] = vol
            except Exception as e:
                sym = futures[f]
                print(f"  [MarketBinance] Warning: {sym} volume failed — {e}")
                vol_map[sym] = 0
            done += 1
            if done % 100 == 0:
                print(f"  [MarketBinance]   {done}/{len(symbols)}...")

    rows = sorted(
        [
            {
                "symbol": f"{s}.P",
                "price": price_map.get(s, 0),
                "avg_volume_usd": vol_map.get(s, 0) / 30,
            }
            for s in symbols
        ],
        key=lambda r: r["avg_volume_usd"],
        reverse=True,
    )
    print(f"  [MarketBinance] Done — {len(rows)} symbols")
    return {"platform": "MarketBinance", "rows": rows}
