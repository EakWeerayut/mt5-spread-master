"""
SET Thailand market data — all listed stocks.
Symbol list: SET open API → price + 30d volume: yfinance (.BK suffix).
"""

import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

SET_HOME = "https://www.set.or.th/"
SET_API_URL = "https://www.set.or.th/api/set/stock/list"
SET_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
    "Origin": "https://www.set.or.th",
    "Referer": "https://www.set.or.th/th/market/product/stock/quote/-.html",
}

BATCH_SIZE = 100  # yfinance symbols per download call


def _get_set_symbols() -> list[str]:
    # SET API requires session cookies from the main page to avoid 403
    session = requests.Session()
    session.get(SET_HOME, headers=SET_HEADERS, timeout=15)
    resp = session.get(
        SET_API_URL,
        headers=SET_HEADERS,
        params={"assetClass": "S", "language": "en"},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("securitySymbols", [])
    return sorted(item["symbol"] for item in items)


def _parse_batch(raw: pd.DataFrame, tickers_bk: list[str]) -> dict[str, tuple[float, float]]:
    """Extract (last_close, 30d_total_volume) per ticker from a yfinance DataFrame."""
    result: dict[str, tuple[float, float]] = {}
    if raw is None or raw.empty:
        return result

    is_multi = isinstance(raw.columns, pd.MultiIndex)

    for sym_bk in tickers_bk:
        try:
            if is_multi:
                close = raw["Close"][sym_bk].dropna()
                volume = raw["Volume"][sym_bk].dropna()
            else:
                # Single-ticker batch (len == 1)
                close = raw["Close"].dropna()
                volume = raw["Volume"].dropna()

            if not close.empty:
                result[sym_bk] = (float(close.iloc[-1]), float(volume.sum()))
        except (KeyError, TypeError):
            pass

    return result


def fetch() -> dict:
    print("  [MarketSET] Fetching SET symbol list...")
    symbols = _get_set_symbols()
    print(f"  [MarketSET] {len(symbols)} SET stocks — downloading 30d data via yfinance...")

    tickers_bk = [f"{s}.BK" for s in symbols]
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=35)  # buffer for weekends / holidays
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    data_map: dict[str, tuple[float, float]] = {}
    total_batches = (len(tickers_bk) + BATCH_SIZE - 1) // BATCH_SIZE

    for i, offset in enumerate(range(0, len(tickers_bk), BATCH_SIZE), 1):
        batch = tickers_bk[offset: offset + BATCH_SIZE]
        print(f"  [MarketSET]   batch {i}/{total_batches} ({len(batch)} symbols)...")
        try:
            raw = yf.download(
                batch,
                start=start_str,
                end=end_str,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            data_map.update(_parse_batch(raw, batch))
        except Exception as e:
            print(f"  [MarketSET]   batch {i} failed: {e}")

    rows = sorted(
        [
            {"symbol": sym, "price": price, "avg_volume_thb": (vol / 30) * price}
            for sym_bk, sym in zip(tickers_bk, symbols)
            if sym_bk in data_map
            for price, vol in [data_map[sym_bk]]
        ],
        key=lambda r: r["avg_volume_thb"],
        reverse=True,
    )

    print(f"  [MarketSET] Got data for {len(rows)}/{len(symbols)} symbols")
    return {"platform": "MarketSET", "rows": rows}
