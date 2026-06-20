import os
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.deribit.com/api/v2"


def _authenticate(client_id: str, client_secret: str) -> str:
    resp = requests.get(
        f"{BASE_URL}/public/auth",
        params={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Deribit auth error: {data['error']}")
    return data["result"]["access_token"]


def _get(token: str, method: str, params: dict = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        f"{BASE_URL}/private/{method}",
        headers=headers,
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Deribit API error on {method}: {data['error']}")
    return data["result"]


def _get_public(method: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{BASE_URL}/public/{method}",
        params=params or {},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["result"]


def fetch() -> dict:
    client_id = os.getenv("DERIBIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("DERIBIT_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        raise ValueError("DERIBIT_CLIENT_ID and DERIBIT_CLIENT_SECRET must be set in .env")

    print("  [Deribit] Authenticating...")
    token = _authenticate(client_id, client_secret)

    # --- Account summaries for BTC and ETH ---
    print("  [Deribit] Fetching account summaries...")
    account_summaries = []
    for currency in ("BTC", "ETH", "USDC"):
        try:
            summary = _get(token, "get_account_summary", {"currency": currency, "extended": "true"})
            account_summaries.append({
                "currency": currency,
                "equity": summary.get("equity"),
                "balance": summary.get("balance"),
                "available_funds": summary.get("available_funds"),
                "margin_balance": summary.get("margin_balance"),
                "unrealized_pnl": summary.get("total_pl"),
                "initial_margin": summary.get("initial_margin"),
            })
        except Exception as e:
            print(f"  [Deribit] Could not fetch {currency} summary: {e}")

    # --- Open positions ---
    print("  [Deribit] Fetching open positions...")
    all_positions = []
    for currency in ("BTC", "ETH", "USDC"):
        try:
            positions = _get(token, "get_positions", {"currency": currency})
            for p in positions:
                all_positions.append({
                    "instrument": p.get("instrument_name"),
                    "size": p.get("size"),
                    "direction": p.get("direction"),
                    "average_price": p.get("average_price"),
                    "mark_price": p.get("mark_price"),
                    "index_price": p.get("index_price"),
                    "floating_pnl": p.get("floating_profit_loss"),
                    "realized_pnl": p.get("realized_profit_loss"),
                    "delta": p.get("delta"),
                    "currency": currency,
                })
        except Exception as e:
            print(f"  [Deribit] Could not fetch {currency} positions: {e}")
    print(f"  [Deribit] Found {len(all_positions)} open position(s)")

    # --- Open orders ---
    print("  [Deribit] Fetching open orders...")
    all_orders = []
    for currency in ("BTC", "ETH", "USDC"):
        try:
            orders = _get(token, "get_open_orders_by_currency", {"currency": currency})
            for o in orders:
                all_orders.append({
                    "order_id": o.get("order_id"),
                    "instrument": o.get("instrument_name"),
                    "direction": o.get("direction"),
                    "order_type": o.get("order_type"),
                    "price": o.get("price"),
                    "amount": o.get("amount"),
                    "filled_amount": o.get("filled_amount"),
                    "status": o.get("order_state"),
                    "currency": currency,
                })
        except Exception as e:
            print(f"  [Deribit] Could not fetch {currency} orders: {e}")
    print(f"  [Deribit] Found {len(all_orders)} open order(s)")

    # --- Last BTC-PERPETUAL settlement (daily mark-to-market) ---
    perpetual_settlement = None
    try:
        h = _get(token, "get_settlement_history_by_instrument",
                 {"instrument_name": "BTC-PERPETUAL", "type": "settlement", "count": 1})
        sm = h.get("settlements", [])
        if sm:
            perpetual_settlement = {
                "price": sm[0].get("mark_price"),
                "index_price": sm[0].get("index_price"),
                "timestamp": sm[0].get("timestamp"),
            }
            print(f"  [Deribit] Last perpetual settlement @ {perpetual_settlement['price']}")
    except Exception as e:
        print(f"  [Deribit] Could not fetch perpetual settlement: {e}")

    # --- Transaction logs ---
    print("  [Deribit] Fetching transaction logs (all historical data with caching)...")
    import time
    import json
    
    cache_file = ".deribit_logs_cache.json"
    cached_logs = []
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_logs = json.load(f)
        except Exception as e:
            print(f"  [Deribit] Warning: Could not read cache file {cache_file}: {e}")
            
    known_ids = {str(log.get("id")) for log in cached_logs if "id" in log}
    new_logs = []

    for currency in ("BTC", "ETH", "USDC"):
        continuation = None
        page = 1
        
        # Deribit requires start_timestamp and end_timestamp for transaction logs
        # Use a very early timestamp (e.g., 2018-01-01) up to current time
        start_ts = 1514764800000 
        end_ts = int(time.time() * 1000)
        
        while True:
            try:
                params = {
                    "currency": currency,
                    "count": 1000,
                    "start_timestamp": start_ts,
                    "end_timestamp": end_ts
                }
                if continuation:
                    params["continuation"] = continuation
                
                t_logs = _get(token, "get_transaction_log", params)
                logs = t_logs.get("logs", [])
                
                added_in_page = 0
                found_duplicate = False
                
                for log in logs:
                    log_id = str(log.get("id"))
                    if log_id in known_ids:
                        found_duplicate = True
                        continue
                    
                    log["_currency"] = currency
                    new_logs.append(log)
                    known_ids.add(log_id)
                    added_in_page += 1
                
                continuation = t_logs.get("continuation")
                
                print(f"    - {currency} fetched page {page} (new: {added_in_page})")
                
                if found_duplicate or not continuation or not logs:
                    break
                    
                page += 1
                time.sleep(0.5)  # Rate limiting
            except Exception as e:
                print(f"  [Deribit] Could not fetch {currency} transaction logs (page {page}): {e}")
                break
                
    if new_logs:
        cached_logs.extend(new_logs)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cached_logs, f, indent=2)
            print(f"  [Deribit] Saved {len(new_logs)} new log(s) to cache")
        except Exception as e:
            print(f"  [Deribit] Warning: Could not save cache file {cache_file}: {e}")
            
    print(f"  [Deribit] Returning {len(cached_logs)} total transaction log entry(ies)")
    all_logs = cached_logs

    # --- Asset and Asset (adj) Calculations ---
    from collections import defaultdict
    logs_by_inst = defaultdict(list)
    total_funding_fee = 0.0
    
    for log in all_logs:
        if log.get("_currency") == "BTC":
            inst = log.get("instrument_name")
            if inst:
                logs_by_inst[inst].append(log)
            if log.get("type") == "settlement":
                total_funding_fee += log.get("interest_pl", 0.0)

    total_unrealized_change = 0.0
    open_insts = {p["instrument"]: p for p in all_positions if p.get("currency") == "BTC"}

    for inst, logs in logs_by_inst.items():
        if inst not in open_insts:
            continue

        logs.sort(key=lambda x: x.get("timestamp", 0))
        open_size = 0.0
        unrealized_change = 0.0
        current_dir = None

        for log in logs:
            log_type = log.get("type")
            change = log.get("change", 0.0)
            
            if log_type == "settlement":
                if open_size > 0:
                    if "session_upl" in log:
                        unrealized_change += log["session_upl"]
                    else:
                        unrealized_change += (change - log.get("interest_pl", 0.0))
            elif log_type in ("trade", "delivery"):
                trade_size = log.get("amount", 0.0)
                side = log.get("side", "")
                direction = "buy" if "buy" in side.lower() else "sell"
                
                if log_type == "delivery":
                    trade_size = open_size
                    direction = "buy" if current_dir == "sell" else "sell"
                
                if open_size == 0.0:
                    open_size = trade_size
                    current_dir = direction
                    unrealized_change += change
                elif direction == current_dir:
                    open_size += trade_size
                    unrealized_change += change
                else:
                    if trade_size < open_size:
                        fraction_closed = trade_size / open_size
                        unrealized_change = unrealized_change * (1.0 - fraction_closed)
                        open_size -= trade_size
                    elif abs(trade_size - open_size) < 1e-9:
                        open_size = 0.0
                        unrealized_change = 0.0
                        current_dir = None
                    else:
                        new_size = trade_size - open_size
                        fraction_new = new_size / trade_size
                        unrealized_change = change * fraction_new
                        open_size = new_size
                        current_dir = direction

        if open_size > 0:
            total_unrealized_change += unrealized_change

    for summary in account_summaries:
        if summary.get("currency") == "BTC":
            asset = summary.get("balance", 0.0)
            summary["asset"] = asset
            summary["asset_adj"] = asset - total_unrealized_change
            summary["total_funding_fee"] = total_funding_fee

    return {
        "platform": "Deribit",
        "account_summaries": account_summaries,
        "open_positions": all_positions,
        "open_orders": all_orders,
        "perpetual_settlement": perpetual_settlement,
        "transaction_logs": all_logs,
    }
