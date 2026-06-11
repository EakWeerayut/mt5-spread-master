import sys
import json
import time
import random
import threading

# Global variables
subscribed_symbols = set()
symbols_lock = threading.Lock()
initialized = False

# Starting mock price anchors
prices = {
    "XAUUSD.SC": 2350.0,
    "XAUUSD": 2349.8,
    "EURUSD.SC": 1.0850,
    "EURUSD": 1.0848,
    "GBPUSD.SC": 1.2720,
    "GBPUSD": 1.2718,
    "BTCUSD.SC": 69000.0,
    "BTCUSD": 68980.0
}

def send_to_master(data):
    """Sends JSON messages to the master process via stdout."""
    try:
        print(json.dumps(data), flush=True)
    except Exception:
        sys.exit(1)

def price_streamer():
    """Background thread that streams simulated prices with random walk."""
    global initialized
    
    while True:
        if not initialized:
            time.sleep(0.5)
            continue
            
        with symbols_lock:
            symbols = list(subscribed_symbols)
            
        for symbol in symbols:
            upper_sym = symbol.upper()
            
            # Fetch anchor price or generate a random base
            if upper_sym not in prices:
                prices[upper_sym] = 100.0
                
            # Perform random walk
            current = prices[upper_sym]
            change = current * random.uniform(-0.0005, 0.0005)
            prices[upper_sym] = current + change
            
            # Calculate mock bid/ask
            spread_pct = 0.0002 # 0.02% spread
            bid = prices[upper_sym]
            ask = bid * (1.0 + spread_pct)
            
            send_to_master({
                "type": "tick",
                "symbol": symbol,
                "bid": round(bid, 5),
                "ask": round(ask, 5),
                "time": int(time.time())
            })
            
        time.sleep(1.0) # Tick updates every 1 second for standard UI responsiveness

def handle_initialize(params):
    global initialized
    
    login = params.get("login", 999999)
    server = params.get("server", "MOCK_SERVER_DEMO")
    
    # Mock symbols available
    mock_symbols = [
        "XAUUSD.sc", "XAUUSD",
        "EURUSD.sc", "EURUSD",
        "GBPUSD.sc", "GBPUSD",
        "BTCUSD.sc", "BTCUSD",
        "USDJPY", "AUDUSD", "USDCAD"
    ]
    
    initialized = True
    send_to_master({
        "status": "initialized",
        "symbols": mock_symbols,
        "account_info": {
            "login": login,
            "server": f"[SIMULATION] {server}"
        }
    })

def handle_subscribe(params):
    symbol = params.get("symbol")
    if not symbol:
        return
        
    with symbols_lock:
        subscribed_symbols.add(symbol)
        
    # Send mock symbol specifications
    upper_sym = symbol.upper()
    contract_size = 100.0
    min_volume = 0.01
    
    if upper_sym == "XAUUSD.SC":
        contract_size = 10.0
        min_volume = 0.01
    elif upper_sym == "USOUSD.SC":
        contract_size = 10.0
        min_volume = 0.01
    elif upper_sym == "USOUSD":
        contract_size = 100.0
        min_volume = 0.01
    elif "NYX" in upper_sym or "CLE" in upper_sym or "CL" in upper_sym:
        contract_size = 1000.0
        min_volume = 1.00
    elif "MGC" in upper_sym:
        contract_size = 10.0
        min_volume = 1.00
    elif "GCE" in upper_sym or "CMX" in upper_sym:
        contract_size = 100.0
        min_volume = 1.00
        
    sessions = {
        "0": [[0, 86400]],
        "1": [[0, 86400]],
        "2": [[0, 86400]],
        "3": [[0, 86400]],
        "4": [[0, 86400]]
    }
    
    send_to_master({
        "type": "symbol_info",
        "symbol": symbol,
        "contract_size": contract_size,
        "min_volume": min_volume,
        "sessions": sessions
    })
        
    # Send initial mock tick immediately
    base = prices.get(upper_sym, 100.0)
    send_to_master({
        "type": "tick",
        "symbol": symbol,
        "bid": round(base, 5),
        "ask": round(base * 1.0002, 5),
        "time": int(time.time())
    })

def handle_unsubscribe(params):
    symbol = params.get("symbol")
    if not symbol:
        return
    with symbols_lock:
        subscribed_symbols.discard(symbol)

def handle_trade(params):
    global initialized
    
    symbol = params.get("symbol")
    action = params.get("action")
    volume = params.get("volume", 0.1)
    request_id = params.get("request_id")
    broker_key = params.get("broker_key")
    
    # Simulate trade execution delay (100ms latency)
    time.sleep(0.1)
    
    upper_sym = symbol.upper()
    base_price = prices.get(upper_sym, 100.0)
    fill_price = base_price * 1.0002 if action == "buy" else base_price
    
    send_to_master({
        "status": "trade_result",
        "request_id": request_id,
        "broker_key": broker_key,
        "success": True,
        "price": round(fill_price, 5),
        "ticket": random.randint(10000000, 99999999),
        "volume": float(volume)
    })

def handle_get_history(params):
    symbol = params.get("symbol")
    request_id = params.get("request_id")
    broker_key = params.get("broker_key")
    if not symbol or not request_id:
        return
        
    # Generate 700 mock M15 bars
    current_time = int(time.time())
    # round to nearest 15m
    anchor_time = (current_time // 900) * 900
    
    upper_sym = symbol.upper()
    base_price = prices.get(upper_sym, 100.0)
    
    # Generate mock random walk backwards
    bars = []
    price = base_price
    for i in range(700):
        bar_time = anchor_time - (700 - i) * 900
        # Random walk step
        step = price * random.uniform(-0.001, 0.001)
        price = price + step
        
        # High and low
        high = price * (1.0 + random.uniform(0, 0.0005))
        low = price * (1.0 - random.uniform(0, 0.0005))
        spread = 20.0 if "XAU" in upper_sym else 2.0 # mock spread in points
        point = 0.01
        
        bars.append({
            "time": bar_time,
            "bid_high": round(high, 2),
            "ask_low": round(low + spread * point, 2)
        })
        
    send_to_master({
        "status": "history_result",
        "request_id": request_id,
        "broker_key": broker_key,
        "success": True,
        "bars": bars
    })

def main():
    t = threading.Thread(target=price_streamer, daemon=True)
    t.start()
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        try:
            msg = json.loads(line)
        except Exception:
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
        elif command == "shutdown":
            sys.exit(0)

if __name__ == "__main__":
    main()
