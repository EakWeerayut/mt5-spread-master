import os
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException

load_dotenv()


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch() -> dict:
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_API_SECRET", "").strip()

    if not api_key or not api_secret:
        raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in .env")

    print("  [Binance] Connecting to Binance API...")
    client = Client(api_key, api_secret)

    # Sync time to prevent timestamp errors
    import time
    server_time = client.get_server_time()
    local_time = int(time.time() * 1000)
    client.timestamp_offset = server_time['serverTime'] - local_time

    # --- Spot balances (non-zero only) ---
    print("  [Binance] Fetching spot balances...")
    account = client.get_account()
    spot_balances = [
        {
            "asset": b["asset"],
            "free": _safe_float(b["free"]),
            "locked": _safe_float(b["locked"]),
            "total": _safe_float(b["free"]) + _safe_float(b["locked"]),
        }
        for b in account["balances"]
        if _safe_float(b["free"]) + _safe_float(b["locked"]) > 0
    ]
    print(f"  [Binance] Found {len(spot_balances)} non-zero spot balance(s)")

    # --- Open spot orders ---
    print("  [Binance] Fetching open spot orders...")
    raw_orders = client.get_open_orders()
    spot_orders = [
        {
            "symbol": o["symbol"],
            "order_id": o["orderId"],
            "side": o["side"],
            "type": o["type"],
            "price": _safe_float(o["price"]),
            "orig_qty": _safe_float(o["origQty"]),
            "executed_qty": _safe_float(o["executedQty"]),
            "status": o["status"],
            "time": o["time"],
        }
        for o in raw_orders
    ]
    print(f"  [Binance] Found {len(spot_orders)} open spot order(s)")

    # --- Earn (Simple Earn) balances ---
    print("  [Binance] Fetching Simple Earn flexible positions...")
    earn_flexible = []
    earn_locked = []
    try:
        flex_resp = client._request_margin_api(
            "get", "simple-earn/flexible/position", signed=True, data={"size": 100}
        )
        earn_flexible = [
            {
                "asset": p["asset"],
                "product_id": p.get("productId", ""),
                "amount": _safe_float(p.get("totalAmount", 0)),
                "apy": p.get("latestAnnualPercentageRate", ""),
                "type": "Flexible",
            }
            for p in flex_resp.get("rows", [])
        ]
        print(f"  [Binance] Found {len(earn_flexible)} flexible earn position(s)")
    except BinanceAPIException as e:
        print(f"  [Binance] Could not fetch flexible earn positions: {e}")

    print("  [Binance] Fetching Simple Earn locked positions...")
    try:
        locked_resp = client._request_margin_api(
            "get", "simple-earn/locked/position", signed=True, data={"size": 100}
        )
        earn_locked = [
            {
                "asset": p["asset"],
                "product_id": p.get("productId", ""),
                "amount": _safe_float(p.get("amount", 0)),
                "apy": p.get("apy", ""),
                "type": "Locked",
            }
            for p in locked_resp.get("rows", [])
        ]
        print(f"  [Binance] Found {len(earn_locked)} locked earn position(s)")
    except BinanceAPIException as e:
        print(f"  [Binance] Could not fetch locked earn positions: {e}")

    earn_balances = earn_flexible + earn_locked

    # --- Futures wallet balances (non-zero only) ---
    print("  [Binance] Fetching futures wallet balances...")
    futures_balances = []
    futures_positions = []
    futures_orders = []
    try:
        raw_balances = client.futures_account_balance()
        futures_balances = [
            {
                "asset": b["asset"],
                "wallet_balance": _safe_float(b["balance"]),
                "unrealized_pnl": _safe_float(b["crossUnPnl"]),
                "available_balance": _safe_float(b["availableBalance"]),
            }
            for b in raw_balances
            if _safe_float(b["balance"]) != 0
        ]
        print(f"  [Binance] Found {len(futures_balances)} non-zero futures wallet balance(s)")

        # --- Futures positions (non-zero only) ---
        print("  [Binance] Fetching futures positions...")
        raw_positions = client.futures_position_information()
        futures_positions = [
            {
                "symbol": p["symbol"],
                "position_side": p["positionSide"],
                "position_amt": _safe_float(p["positionAmt"]),
                "entry_price": _safe_float(p["entryPrice"]),
                "mark_price": _safe_float(p.get("markPrice", 0)),
                "unrealized_pnl": _safe_float(p["unRealizedProfit"]),
                "leverage": p.get("leverage", ""),
                "margin_type": p.get("marginType", ""),
            }
            for p in raw_positions
            if _safe_float(p["positionAmt"]) != 0
        ]
        print(f"  [Binance] Found {len(futures_positions)} open futures position(s)")

        # --- Futures open orders ---
        print("  [Binance] Fetching futures open orders...")
        raw_futures_orders = client.futures_get_open_orders()
        futures_orders = [
            {
                "symbol": o["symbol"],
                "order_id": o["orderId"],
                "side": o["side"],
                "type": o["type"],
                "price": _safe_float(o["price"]),
                "orig_qty": _safe_float(o["origQty"]),
                "executed_qty": _safe_float(o["executedQty"]),
                "stop_price": _safe_float(o.get("stopPrice", 0)),
                "status": o["status"],
                "time": o["time"],
            }
            for o in raw_futures_orders
        ]
        print(f"  [Binance] Found {len(futures_orders)} open futures order(s)")

    except BinanceAPIException as e:
        print(f"  [Binance] Could not fetch futures data (account may not have futures): {e}")

    return {
        "platform": "Binance",
        "spot_balances": spot_balances,
        "earn_balances": earn_balances,
        "futures_balances": futures_balances,
        "futures_positions": futures_positions,
        "futures_orders": futures_orders,
        "spot_orders": spot_orders,
    }
