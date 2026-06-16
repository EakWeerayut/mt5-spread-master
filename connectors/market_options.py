import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _get_binance_options() -> list[dict]:
    # eapi is Binance's European Options API
    url = "https://eapi.binance.com/eapi/v1/ticker"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    
    rows = []
    for item in data:
        symbol = item.get("symbol", "")
        # Filter for BTC options
        if not symbol.startswith("BTC-"):
            continue
            
        # Parse symbol: BTC-240531-70000-C (Underlying-YYMMDD-Strike-Type)
        parts = symbol.split("-")
        if len(parts) != 4:
            continue
            
        underlying = parts[0]
        expiry_str = parts[1]
        strike = parts[2]
        opt_type = parts[3]
        
        # Convert YYMMDD to YYYY-MM-DD
        try:
            expiry_date = datetime.strptime(expiry_str, "%y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            expiry_date = expiry_str
            
        rows.append({
            "exchange": "Binance",
            "symbol": symbol,
            "underlying": underlying,
            "expiry_date": expiry_date,
            "strike": _safe_float(strike),
            "type": opt_type,
            "bid": _safe_float(item.get("bidPrice")),
            "ask": _safe_float(item.get("askPrice")),
            "mark_price": _safe_float(item.get("lastPrice")),  # Using lastPrice or mark price if we fetch it separately. Ticker has open, high, low, lastPrice
            "volume": _safe_float(item.get("volume")),
            "open_interest": 0.0, # Ticker endpoint does not provide OI
            "iv": 0.0 # Ticker endpoint does not provide IV
        })
    return rows

def _get_deribit_options() -> list[dict]:
    url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
    resp = requests.get(
        url,
        params={"currency": "BTC", "kind": "option"},
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json().get("result", [])
    
    rows = []
    for item in data:
        symbol = item.get("instrument_name", "")
        # Parse symbol: BTC-31MAY24-70000-C (Underlying-DDMMMYY-Strike-Type)
        parts = symbol.split("-")
        if len(parts) != 4:
            continue
            
        underlying = parts[0]
        expiry_str = parts[1]
        strike = parts[2]
        opt_type = parts[3]
        
        # Convert DDMMMYY to YYYY-MM-DD
        try:
            expiry_date = datetime.strptime(expiry_str, "%d%b%y").strftime("%Y-%m-%d")
        except ValueError:
            expiry_date = expiry_str
            
        rows.append({
            "exchange": "Deribit",
            "symbol": symbol,
            "underlying": underlying,
            "expiry_date": expiry_date,
            "strike": _safe_float(strike),
            "type": opt_type,
            "bid": _safe_float(item.get("bid_price")),
            "ask": _safe_float(item.get("ask_price")),
            "mark_price": _safe_float(item.get("mark_price")),
            "volume": _safe_float(item.get("volume_usd")), # Deribit provides volume_usd and volume (contracts)
            "open_interest": _safe_float(item.get("open_interest")),
            "iv": _safe_float(item.get("mark_iv"))
        })
    return rows

def fetch() -> dict:
    print("  [MarketOptions] Fetching Binance BTC options...")
    binance_rows = []
    try:
        binance_rows = _get_binance_options()
        print(f"  [MarketOptions] Found {len(binance_rows)} Binance BTC options")
    except Exception as e:
        print(f"  [MarketOptions] Error fetching Binance options: {e}")
        
    print("  [MarketOptions] Fetching Deribit BTC options...")
    deribit_rows = []
    try:
        deribit_rows = _get_deribit_options()
        print(f"  [MarketOptions] Found {len(deribit_rows)} Deribit BTC options")
    except Exception as e:
        print(f"  [MarketOptions] Error fetching Deribit options: {e}")
        
    all_rows = binance_rows + deribit_rows
    # Sort by Expiry Date, then Strike, then Type
    all_rows.sort(key=lambda x: (x["expiry_date"], x["strike"], x["type"]))
    
    return {
        "platform": "MarketOptions",
        "rows": all_rows
    }
