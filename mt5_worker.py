import MetaTrader5 as mt5
import sys
import json
import time
import threading

# Global variables
subscribed_symbols = set()
symbols_lock = threading.Lock()
output_lock = threading.Lock()  # serialize stdout writes across threads
initialized = False
mt5_path = None

def send_to_master(data):
    """Sends JSON messages to the master process via stdout.

    Must be atomic: the price-streamer thread and the command-handling thread both
    write here, and interleaved writes corrupt the line-delimited JSON the master
    parses (e.g. two objects glued onto one line). A lock + single write fixes it.
    """
    try:
        msg = json.dumps(data)
        with output_lock:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
    except Exception:
        # If stdout is closed or error, exit
        sys.exit(1)

def get_filling_mode(symbol):
    """Auto-detects the filling mode supported by the broker for the symbol."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return mt5.ORDER_FILLING_FOK
    
    filling = info.filling_mode
    # Check flags
    if filling & 1:  # SYMBOL_FILLING_FOK
        return mt5.ORDER_FILLING_FOK
    elif filling & 2:  # SYMBOL_FILLING_IOC
        return mt5.ORDER_FILLING_IOC
    else:
        return mt5.ORDER_FILLING_RETURN

def price_streamer():
    """Background thread that streams prices for all subscribed symbols."""
    global initialized
    last_ticks = {}
    
    while True:
        if not initialized:
            time.sleep(0.5)
            continue
            
        with symbols_lock:
            symbols = list(subscribed_symbols)
            
        for symbol in symbols:
            try:
                # Make sure symbol is selected in Market Watch
                mt5.symbol_select(symbol, True)
                tick = mt5.symbol_info_tick(symbol)
                if tick is not None:
                    # Check if price has changed or if it's the first time
                    last_tick = last_ticks.get(symbol)
                    if not last_tick or last_tick.bid != tick.bid or last_tick.ask != tick.ask:
                        last_ticks[symbol] = tick
                        
                        # Fetch positions for the symbol
                        positions = mt5.positions_get(symbol=symbol)
                        net_volume = 0.0
                        if positions:
                            for pos in positions:
                                if pos.type == mt5.POSITION_TYPE_BUY:
                                    net_volume += pos.volume
                                elif pos.type == mt5.POSITION_TYPE_SELL:
                                    net_volume -= pos.volume
                                    
                        send_to_master({
                            "type": "tick",
                            "symbol": symbol,
                            "bid": tick.bid,
                            "ask": tick.ask,
                            "time": tick.time,
                            "net_position": round(net_volume, 2)
                        })
            except Exception as e:
                send_to_master({
                    "type": "log",
                    "level": "error",
                    "message": f"Error getting tick for {symbol}: {str(e)}"
                })
        
        time.sleep(1.0) # Check prices every 1s to match frontend and prevent micro-spike triggers

def handle_initialize(params):
    global initialized, mt5_path
    
    path = params.get("path")
    login = params.get("login")
    password = params.get("password")
    server = params.get("server")
    
    # Validation
    if not path or not login or not password or not server:
        send_to_master({
            "status": "error",
            "message": "Missing connection parameters (path, login, password, server)"
        })
        return
        
    try:
        login = int(login)
    except ValueError:
        send_to_master({
            "status": "error",
            "message": "Login must be an integer"
        })
        return

    init_success = mt5.initialize(
        path=path,
        login=login,
        password=password,
        server=server
    )
    
    if not init_success:
        err_code, err_desc = mt5.last_error()
        send_to_master({
            "status": "error",
            "message": f"MT5 Init Failed. Code: {err_code}, Desc: {err_desc}"
        })
        return
        
    # Force login to specific account (crucial if terminal was already open or cached other account)
    login_success = mt5.login(
        login=login,
        password=password,
        server=server
    )
    
    if not login_success:
        err_code, err_desc = mt5.last_error()
        send_to_master({
            "status": "error",
            "message": f"MT5 Login Failed. Code: {err_code}, Desc: {err_desc}"
        })
        return
        
    # Get all available symbols for recommendation search
    all_symbols = mt5.symbols_get()
    symbol_names = []
    if all_symbols:
        symbol_names = [s.name for s in all_symbols]
        
    initialized = True
    mt5_path = path
    send_to_master({
        "status": "initialized",
        "symbols": symbol_names,
        "account_info": {
            "login": login,
            "server": server
        }
    })

def handle_subscribe(params):
    symbol = params.get("symbol")
    if not symbol:
        return
        
    # Select the symbol in Market Watch first
    success = mt5.symbol_select(symbol, True)
    if not success:
        send_to_master({
            "type": "log",
            "level": "warning",
            "message": f"Could not select symbol {symbol} in Market Watch"
        })
        
    with symbols_lock:
        already_subscribed = symbol in subscribed_symbols
        subscribed_symbols.add(symbol)

    # Already streaming: skip the expensive session recompute (6000 M5 bars) so the
    # master can cheaply re-subscribe every poll (self-heals after a reconnect).
    if already_subscribed:
        return

    # Query symbol specifications
    info = mt5.symbol_info(symbol)
    if info:
        # Calculate true contract size in ounces/units based on tick size and value
        contract_size = info.trade_contract_size
        if info.trade_tick_size > 0:
            contract_size = info.trade_tick_value / info.trade_tick_size
            
        # Cent accounts (.sc) report standard USD tick values but trade at 1/100th the size
        if symbol.lower().endswith('.sc'):
            contract_size = contract_size / 100.0
            
        # Query 6000 M5 bars (approx 20.8 days of data) to detect active trading sessions with 5m precision
        sessions = {}
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 6000)
        if rates is not None and len(rates) > 0:
            by_day = {}
            for r in rates:
                t = int(r['time'])
                srv_time = time.gmtime(t)
                wday = srv_time.tm_wday
                time_of_day = srv_time.tm_hour * 3600 + srv_time.tm_min * 60
                if wday not in by_day:
                    by_day[wday] = set()
                by_day[wday].add(time_of_day)
            for wday, times_set in by_day.items():
                times = sorted(list(times_set))
                if not times:
                    continue
                day_sessions = []
                start_t = times[0]
                prev_t = times[0]
                for t in times[1:]:
                    if t - prev_t > 1800: # gap > 30 minutes
                        day_sessions.append([start_t, prev_t + 300])
                        start_t = t
                    prev_t = t
                day_sessions.append([start_t, prev_t + 300])
                sessions[str(wday)] = day_sessions
            
        send_to_master({
            "type": "symbol_info",
            "symbol": symbol,
            "contract_size": contract_size,
            "min_volume": info.volume_min,
            "sessions": sessions
        })
        
    # Return immediate tick if available
    tick = mt5.symbol_info_tick(symbol)
    if tick:
        send_to_master({
            "type": "tick",
            "symbol": symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "time": tick.time
        })

def handle_unsubscribe(params):
    symbol = params.get("symbol")
    if not symbol:
        return
    with symbols_lock:
        subscribed_symbols.discard(symbol)

def handle_trade(params):
    global initialized
    broker_key = params.get("broker_key")
    
    if not initialized:
        send_to_master({
            "status": "trade_result",
            "request_id": params.get("request_id"),
            "broker_key": broker_key,
            "success": False,
            "error": "MT5 Terminal not initialized"
        })
        return
        
    symbol = params.get("symbol")
    action = params.get("action") # "buy" or "sell"
    volume = params.get("volume")
    request_id = params.get("request_id")
    
    if not symbol or not action or not volume:
        send_to_master({
            "status": "trade_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": False,
            "error": "Missing trade parameters (symbol, action, volume)"
        })
        return
        
    try:
        volume = float(volume)
    except ValueError:
        send_to_master({
            "status": "trade_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": False,
            "error": "Volume must be a float number"
        })
        return
        
    # Select the symbol
    mt5.symbol_select(symbol, True)
    
    # Determine the price
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        send_to_master({
            "status": "trade_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": False,
            "error": f"Failed to get price tick for {symbol}"
        })
        return
        
    order_type = mt5.ORDER_TYPE_BUY if action.lower() == "buy" else mt5.ORDER_TYPE_SELL
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    
    dry_run = params.get("dry_run", True)
    # Dry Run Mode: paper trade using real MT5 prices without sending orders to the market
    if dry_run:
        import random
        time.sleep(0.1) # simulate brief server execution latency
        send_to_master({
            "status": "trade_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": True,
            "price": price,
            "ticket": random.randint(10000000, 99999999),
            "volume": volume,
            "is_dry_run": True
        })
        return
        
    filling_mode = get_filling_mode(symbol)
    
    # 1. Close any active opposite positions up to the target order volume (Netting behavior)
    remaining_volume = volume
    last_deal_price = price
    
    positions = mt5.positions_get(symbol=symbol)
    if positions:
        opposite_type = mt5.POSITION_TYPE_SELL if order_type == mt5.ORDER_TYPE_BUY else mt5.POSITION_TYPE_BUY
        for pos in positions:
            if pos.type == opposite_type and remaining_volume > 0:
                # Target close direction (opposite of pos.type)
                close_type = mt5.ORDER_TYPE_BUY if pos.type == mt5.POSITION_TYPE_SELL else mt5.ORDER_TYPE_SELL
                
                # Determine how much volume of this position we need to close
                close_vol = min(pos.volume, remaining_volume)
                close_vol = round(close_vol, 2)
                
                # Fetch fresh price for closing this specific position
                t_close = mt5.symbol_info_tick(symbol)
                if t_close is not None:
                    close_price = t_close.ask if close_type == mt5.ORDER_TYPE_BUY else t_close.bid
                    
                    close_req = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": symbol,
                        "volume": close_vol,
                        "type": close_type,
                        "position": pos.ticket,
                        "price": close_price,
                        "deviation": 20,
                        "magic": 999111,
                        "comment": f"Net Close Pos #{pos.ticket}",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": filling_mode,
                    }
                    res_close = mt5.order_send(close_req)
                    if res_close and res_close.retcode == mt5.TRADE_RETCODE_DONE:
                        send_to_master({
                            "type": "log",
                            "level": "info",
                            "message": f"Successfully netted/closed opposite position #{pos.ticket} (closed {close_vol} of {pos.volume} lots)."
                        })
                        remaining_volume -= close_vol
                        remaining_volume = round(remaining_volume, 2)
                        # MT5 netting accounts can return 0.0 for res_close.price;
                        # fall back to the price we submitted if that happens.
                        last_deal_price = res_close.price if res_close.price and res_close.price > 0 else close_price
                    else:
                        err_comment = res_close.comment if res_close else "Empty response"
                        send_to_master({
                            "type": "log",
                            "level": "warning",
                            "message": f"Failed to net/close opposite position #{pos.ticket}. Code: {res_close.retcode if res_close else 'N/A'}, Comment: {err_comment}"
                        })

    # If the entire order volume was used for netting/closing existing positions, return success
    if remaining_volume <= 0.001:
        send_to_master({
            "status": "trade_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": True,
            "price": last_deal_price,
            "ticket": 999999, # Dummy ticket for netting close
            "volume": volume
        })
        return

    # 2. Get fresh price for the remaining main position volume to open
    tick = mt5.symbol_info_tick(symbol)
    if tick is not None:
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        
    # Build order request for remaining volume
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": remaining_volume,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": 999111,
        "comment": "Spread Master Trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }
    
    result = mt5.order_send(request)
    
    if result is None:
        send_to_master({
            "status": "trade_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": False,
            "error": "Order send failed, empty response from MT5 API"
        })
        return
        
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        send_to_master({
            "status": "trade_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": False,
            "error": f"Execution failed. Code: {result.retcode}, Comment: {result.comment}"
        })
    else:
        # Fallback to the requested tick price if MT5 returns 0.0 for the execution price
        exec_price = result.price if (result.price and result.price > 0) else price
        send_to_master({
            "status": "trade_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": True,
            "price": exec_price,
            "ticket": result.order,
            "volume": result.volume
        })

def handle_get_position_costs(params):
    """Reports REAL open-position costs for a symbol: net volume, avg entry,
    accrued swap (position.swap), realized commission (from opening deals), and
    floating profit. Used by the 'Actual' panel for the current position."""
    symbol = params.get("symbol")
    request_id = params.get("request_id")
    broker_key = params.get("broker_key")
    if not request_id:
        return

    out = {
        "status": "position_costs_result",
        "request_id": request_id,
        "broker_key": broker_key,
        "symbol": symbol,
        "success": False,
        "positions": [],
        "net_volume": 0.0,
        "avg_open": None,
        "swap": 0.0,
        "commission": 0.0,
        "profit": 0.0,
        "open_time": None,
    }

    if not initialized:
        out["error"] = "MT5 Terminal not initialized"
        send_to_master(out)
        return

    try:
        positions = mt5.positions_get(symbol=symbol) or []
        net_vol = 0.0
        vol_abs = 0.0
        weighted_open = 0.0
        swap_sum = 0.0
        profit_sum = 0.0
        comm_sum = 0.0
        earliest = None
        pos_list = []

        for p in positions:
            is_buy = (p.type == mt5.POSITION_TYPE_BUY)
            net_vol += p.volume if is_buy else -p.volume
            vol_abs += p.volume
            weighted_open += p.price_open * p.volume
            swap_sum += p.swap
            profit_sum += p.profit
            if earliest is None or p.time < earliest:
                earliest = p.time
            # realized commission for this position (entry deal, negative)
            deals = mt5.history_deals_get(position=p.ticket) or []
            for d in deals:
                comm_sum += d.commission
            pos_list.append({
                "ticket": p.ticket,
                "type": "buy" if is_buy else "sell",
                "volume": p.volume,
                "price_open": p.price_open,
                "swap": p.swap,
                "profit": p.profit,
                "time": int(p.time),
            })

        out.update({
            "success": True,
            "positions": pos_list,
            "net_volume": round(net_vol, 2),
            "avg_open": (weighted_open / vol_abs) if vol_abs else None,
            "swap": round(swap_sum, 2),
            "commission": round(comm_sum, 2),
            "profit": round(profit_sum, 2),
            "open_time": int(earliest) if earliest else None,
        })
    except Exception as e:
        out["error"] = str(e)

    send_to_master(out)

def handle_get_history(params):
    symbol = params.get("symbol")
    request_id = params.get("request_id")
    broker_key = params.get("broker_key")
    if not symbol or not request_id:
        return
        
    if not initialized:
        send_to_master({
            "status": "history_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": False,
            "error": "MT5 Terminal not initialized"
        })
        return
        
    info = mt5.symbol_info(symbol)
    if not info:
        send_to_master({
            "status": "history_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": False,
            "error": f"Symbol {symbol} not found"
        })
        return
        
    point = info.point
    # Fetch 700 M15 bars (approx 7.2 days of data)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 700)
    
    if rates is None or len(rates) == 0:
        send_to_master({
            "status": "history_result",
            "request_id": request_id,
            "broker_key": broker_key,
            "success": False,
            "error": f"Failed to copy rates for {symbol}"
        })
        return
        
    bars = []
    for r in rates:
        low = float(r['low'])
        high = float(r['high'])
        spread = float(r['spread'])
        bars.append({
            "time": int(r['time']),
            "bid_high": high,
            "ask_low": low + spread * point,
            "bid_close": float(r['close']),
            "ask_close": float(r['close']) + spread * point
        })
        
    send_to_master({
        "status": "history_result",
        "request_id": request_id,
        "broker_key": broker_key,
        "success": True,
        "bars": bars
    })

def main():
    # Start price streaming thread
    t = threading.Thread(target=price_streamer, daemon=True)
    t.start()
    
    # Read commands from stdin line-by-line
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        try:
            msg = json.loads(line)
        except Exception as e:
            send_to_master({"type": "log", "level": "error", "message": f"Failed to parse command JSON: {str(e)}"})
            continue
            
        command = msg.get("command")
        
        if command == "initialize":
            handle_initialize(msg)
        elif command == "subscribe":
            handle_subscribe(msg)
        elif command == "unsubscribe":
            handle_unsubscribe(msg)
        elif command == "trade":
            handle_trade(msg)
        elif command == "get_history":
            handle_get_history(msg)
        elif command == "get_position_costs":
            handle_get_position_costs(msg)
        elif command == "shutdown":
            if initialized:
                mt5.shutdown()
            sys.exit(0)
        else:
            send_to_master({"type": "log", "level": "warning", "message": f"Unknown command: {command}"})

if __name__ == "__main__":
    main()
