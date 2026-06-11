import os
import sys
import json
import subprocess
import threading
import time
import uuid
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer
from urllib.parse import urlparse, parse_qs
import cmx_data_manager
import oil_data_manager
import tfx_data_manager
import uko_uso_data_manager

# Configuration file path
CONFIG_FILE = "spread_trader_config.json"

def load_env():
    """Manually parses the .env file in the workspace to load MT5 credentials."""
    env = {}
    if os.path.exists(".env"):
        try:
            with open(".env", "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        env[k] = v
        except Exception as e:
            print(f"Error reading .env: {e}")
    return env

env_config = load_env()

def get_mt5_accounts():
    accounts = []
    
    # MTS Account (from env)
    mts_login = env_config.get("MT5_LOGIN")
    mts_pass = env_config.get("MT5_PASSWORD")
    mts_server = env_config.get("MT5_SERVER")
    mts_name = env_config.get("MT5_NAME", "MTS")
    if mts_login and mts_pass and mts_server:
        accounts.append({
            "id": "mts",
            "name": mts_name,
            "login": mts_login,
            "password": mts_pass,
            "server": mts_server
        })
        
    # Vantage Account (from env)
    vantage_login = env_config.get("MT5_LOGIN_2")
    vantage_pass = env_config.get("MT5_PASSWORD_2")
    vantage_server = env_config.get("MT5_SERVER_2")
    vantage_name = env_config.get("MT5_NAME_2", "Vantage")
    if vantage_login and vantage_pass and vantage_server:
        accounts.append({
            "id": "vantage",
            "name": vantage_name,
            "login": vantage_login,
            "password": vantage_pass,
            "server": vantage_server
        })
        
    # Account 3 (from env)
    login_3 = env_config.get("MT5_LOGIN_3")
    pass_3 = env_config.get("MT5_PASSWORD_3")
    server_3 = env_config.get("MT5_SERVER_3")
    name_3 = env_config.get("MT5_NAME_3", "Account 3")
    if login_3 and pass_3 and server_3:
        accounts.append({
            "id": "acc3",
            "name": name_3,
            "login": login_3,
            "password": pass_3,
            "server": server_3
        })
        
    return accounts

mt5_accounts = get_mt5_accounts()

# Global states
state = {
    "broker1": {
        "connected": False,
        "login": None,
        "server": None,
        "symbol": None,
        "bid": None,
        "ask": None,
        "symbols": [],
        "contract_size": None,
        "min_volume": None
    },
    "broker2": {
        "connected": False,
        "login": None,
        "server": None,
        "symbol": None,
        "bid": None,
        "ask": None,
        "symbols": [],
        "contract_size": None,
        "min_volume": None
    },
    "orders": [],
    "logs": []
}

state_lock = threading.Lock()

# Worker processes references
workers = {
    "broker1": None,
    "broker2": None
}

is_sharing_worker = False

# Pending trade requests (mapping: order_id -> {broker_key: trade_result_dict})
pending_trades = {}
trades_lock = threading.Lock()

# Pending history requests (mapping: request_id -> {"event": threading.Event, "broker1": res, "broker2": res})
pending_history = {}
history_lock = threading.Lock()

def log_message(message):
    """Appends a system message to the global logs."""
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    full_message = f"{timestamp} {message}"
    print(full_message)
    with state_lock:
        state["logs"].append(full_message)
        # Keep logs list size reasonable
        if len(state["logs"]) > 200:
            state["logs"].pop(0)

def load_saved_config():
    """Loads previously saved broker configuration."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            log_message(f"Error loading config.json: {str(e)}")
    return {}

def save_config(config):
    """Saves broker configuration to a local JSON file."""
    try:
        # Preserve favorites if they exist in the saved config but not in the new config
        existing = load_saved_config()
        if "favorites" in existing and "favorites" not in config:
            config["favorites"] = existing["favorites"]
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        log_message(f"Error saving config.json: {str(e)}")

# Worker communications
def send_to_worker(broker_key, payload):
    """Sends JSON line command to a specific worker subprocess stdin."""
    target_key = broker_key
    if is_sharing_worker and broker_key == "broker2":
        target_key = "broker1"
        
    worker = workers[target_key]
    if worker and worker.poll() is None:
        try:
            worker.stdin.write(json.dumps(payload) + "\n")
            worker.stdin.flush()
        except Exception as e:
            log_message(f"Error sending to {target_key} worker: {str(e)}")

def read_worker_output(broker_key, worker):
    """Background thread function to parse stdout messages from a worker."""
    global state
    log_message(f"Started reading output thread for {broker_key}")
    
    for line in iter(worker.stdout.readline, ''):
        if not line:
            break
            
        line = line.strip()
        try:
            msg = json.loads(line)
        except Exception as e:
            log_message(f"Error parsing worker {broker_key} output line: {line}. Err: {str(e)}")
            continue
            
        msg_type = msg.get("type")
        status = msg.get("status")
        
        # 1. Handle Initialization status
        if status == "initialized":
            with state_lock:
                state[broker_key]["connected"] = True
                state[broker_key]["login"] = msg["account_info"]["login"]
                state[broker_key]["server"] = msg["account_info"]["server"]
                state[broker_key]["symbols"] = msg.get("symbols", [])
                
                # If sharing worker, mirror broker1 state to broker2
                if is_sharing_worker and broker_key == "broker1":
                    state["broker2"]["connected"] = True
                    state["broker2"]["login"] = msg["account_info"]["login"]
                    state["broker2"]["server"] = msg["account_info"]["server"]
                    state["broker2"]["symbols"] = msg.get("symbols", [])
                    
            log_message(f"{broker_key.upper()} Initialized successfully! Server: {msg['account_info']['server']}")
            if is_sharing_worker and broker_key == "broker1":
                log_message(f"BROKER2 Shared connection initialized with BROKER1 on Server: {msg['account_info']['server']}")
            
        elif status == "error":
            with state_lock:
                state[broker_key]["connected"] = False
                if is_sharing_worker and broker_key == "broker1":
                    state["broker2"]["connected"] = False
            log_message(f"{broker_key.upper()} Init Error: {msg.get('message')}")
            if is_sharing_worker and broker_key == "broker1":
                log_message(f"BROKER2 Shared connection Init Error: {msg.get('message')}")
            
        # Handle Symbol Info
        elif msg_type == "symbol_info":
            symbol = msg.get("symbol")
            contract_size = msg.get("contract_size")
            min_volume = msg.get("min_volume")
            sessions = msg.get("sessions", {})
            with state_lock:
                if state[broker_key]["symbol"] == symbol:
                    state[broker_key]["contract_size"] = contract_size
                    state[broker_key]["min_volume"] = min_volume
                    state[broker_key]["sessions"] = sessions
                if is_sharing_worker and state["broker2"]["symbol"] == symbol:
                    state["broker2"]["contract_size"] = contract_size
                    state["broker2"]["min_volume"] = min_volume
                    state["broker2"]["sessions"] = sessions
            log_message(f"[{broker_key.upper()}]: Symbol spec for {symbol} - Contract Size: {contract_size}, Min Volume: {min_volume} (Weekly sessions loaded, click clock icon to view)")
            
        # 2. Handle Ticks
        elif msg_type == "tick":
            symbol = msg.get("symbol")
            tick_time = msg.get("time")
            with state_lock:
                updated = False
                if state[broker_key]["symbol"] == symbol:
                    state[broker_key]["bid"] = msg.get("bid")
                    state[broker_key]["ask"] = msg.get("ask")
                    state[broker_key]["net_position"] = msg.get("net_position", 0.0)
                    state[broker_key]["tick_time"] = tick_time
                    state[broker_key]["local_tick_time"] = time.time()
                    
                    # Update timezone offset dynamically
                    offset = tick_time - time.time()
                    if -43200 <= offset <= 50400:
                        state[broker_key]["timezone_offset"] = round(offset / 3600) * 3600
                        
                    updated = True
                if is_sharing_worker and state["broker2"]["symbol"] == symbol:
                    state["broker2"]["bid"] = msg.get("bid")
                    state["broker2"]["ask"] = msg.get("ask")
                    state["broker2"]["net_position"] = msg.get("net_position", 0.0)
                    state["broker2"]["tick_time"] = tick_time
                    state["broker2"]["local_tick_time"] = time.time()
                    
                    # Update timezone offset dynamically
                    offset = tick_time - time.time()
                    if -43200 <= offset <= 50400:
                        state["broker2"]["timezone_offset"] = round(offset / 3600) * 3600
                        
                    updated = True
            if updated:
                # Trigger checking orders on tick update
                check_spread_limit_orders()
            
        # 3. Handle Trade results
        elif status == "trade_result":
            request_id = msg.get("request_id")
            actual_broker_key = msg.get("broker_key", broker_key)
            handle_trade_response(actual_broker_key, request_id, msg)
            
        # 3.5 Handle History results
        elif status == "history_result":
            request_id = msg.get("request_id")
            actual_broker_key = msg.get("broker_key", broker_key)
            handle_history_response(actual_broker_key, request_id, msg)
            
        # 4. Handle logs from worker
        elif msg_type == "log":
            level = msg.get("level", "info")
            log_message(f"[{broker_key.upper()} Worker {level}]: {msg.get('message')}")
            
    # If stdout loop exits, the process ended
    with state_lock:
        state[broker_key]["connected"] = False
        if is_sharing_worker and broker_key == "broker1":
            state["broker2"]["connected"] = False
    log_message(f"{broker_key.upper()} Worker process stopped.")
    if is_sharing_worker and broker_key == "broker1":
        log_message("BROKER2 Shared connection worker stopped.")

def handle_history_response(broker_key, request_id, result):
    """Tracks historical rate responses from both workers."""
    with history_lock:
        if request_id not in pending_history:
            return
        pending_history[request_id][broker_key] = result
        
        # Check if both worker results are received
        r = pending_history[request_id]
        if r["broker1"] is not None and r["broker2"] is not None:
            r["event"].set()

def handle_trade_response(broker_key, request_id, result):
    """Tracks responses from both workers for triggered spread trades."""
    with trades_lock:
        if request_id not in pending_trades:
            log_message(f"Received stray trade response from {broker_key} for request: {request_id}")
            return
            
        pending_trades[request_id][broker_key] = result
        trades_dict = pending_trades[request_id]
        
    # Check if both broker executions are complete
    if "broker1" in trades_dict and "broker2" in trades_dict:
        # Both leg executions finished
        r1 = trades_dict["broker1"]
        r2 = trades_dict["broker2"]
        
        order = None
        with state_lock:
            for o in state["orders"]:
                if o["id"] == request_id:
                    order = o
                    break
                    
        if not order:
            log_message(f"Order {request_id} not found in state during execution completion.")
            return
 
        success1 = r1.get("success", False)
        success2 = r2.get("success", False)
        
        if success1 and success2:
            price1 = r1["price"]
            price2 = r2["price"]
            # Actual Spread achieved
            actual_spread = price1 - price2
            
            with state_lock:
                order["status"] = "completed"
                order["actual_spread"] = actual_spread
                order["fill_details"] = {
                    "broker1": {"price": price1, "ticket": r1["ticket"]},
                    "broker2": {"price": price2, "ticket": r2["ticket"]}
                }
            prefix = "[DRY RUN COMPLETED]" if order.get("dry_run", True) else "[ORDER COMPLETED]"
            log_message(f"{prefix}: Spread order {request_id} executed successfully!")
            log_message(f" -> Leg 1 ({order['symbol1']}): {price1} (Ticket {r1['ticket']})")
            log_message(f" -> Leg 2 ({order['symbol2']}): {price2} (Ticket {r2['ticket']})")
            log_message(f" -> Target Spread: {order['target_spread']:.2f} | Actual Spread Achieved: {actual_spread:.2f}")
        else:
            # Handle partial failure or complete failure
            error_msg = []
            if not success1:
                error_msg.append(f"Leg 1 ({order['symbol1']}) failed: {r1.get('error')}")
            if not success2:
                error_msg.append(f"Leg 2 ({order['symbol2']}) failed: {r2.get('error')}")
                
            combined_error = " | ".join(error_msg)
            with state_lock:
                order["status"] = "failed"
                order["error"] = combined_error
                
            log_message(f"[ORDER FAILED]: Spread order {request_id} failed!")
            log_message(f" -> Details: {combined_error}")
            if success1:
                log_message(f" -> WARNING: Leg 1 executed (Ticket {r1['ticket']}) but Leg 2 failed. Unhedged position alert!")
            if success2:
                log_message(f" -> WARNING: Leg 2 executed (Ticket {r2['ticket']}) but Leg 1 failed. Unhedged position alert!")
                
        # Clean up memory
        with trades_lock:
            pending_trades.pop(request_id, None)

def stop_worker(broker_key):
    """Stops and cleans up the worker process."""
    global workers
    worker = workers[broker_key]
    if worker:
        try:
            worker.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
            worker.stdin.flush()
        except Exception:
            pass
        
        try:
            worker.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                worker.terminate()
                worker.wait(timeout=0.5)
            except Exception:
                pass
        workers[broker_key] = None

def start_worker(broker_key, path=None):
    """Launches the MT5 worker subprocess. Runs in simulation mode if path is 'MOCK'."""
    global workers
    # Stop existing worker first to ensure clean state
    stop_worker(broker_key)
        
    try:
        worker_script = "mt5_worker.py"
        if path and ("MOCK" in path.upper() or "SIMULATE" in path.upper() or path.upper() == ""):
            worker_script = "mock_mt5_worker.py"
            log_message(f"Initializing {broker_key.upper()} worker in SIMULATION (MOCK) MODE...")
            
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), worker_script)
        # Run worker with Python executable, using piping for stdin/stdout
        proc = subprocess.Popen(
            [sys.executable, script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        workers[broker_key] = proc
        
        # Start reading stdout thread
        t = threading.Thread(target=read_worker_output, args=(broker_key, proc), daemon=True)
        t.start()
        
        return True
    except Exception as e:
        log_message(f"Failed to start worker process for {broker_key}: {str(e)}")
        return False

def is_market_open_in_server(broker_key):
    """Checks if the market is open for a broker symbol based on tick freshness, valid timezone offset, and weekly sessions."""
    with state_lock:
        b_state = state[broker_key]
        tick_time = b_state.get("tick_time")
        local_tick_time = b_state.get("local_tick_time")
        sessions = b_state.get("sessions")
        
    if not tick_time or not local_tick_time:
        return False
        
    # 1. Tick must have been received recently by the server (within last 5 minutes)
    now = time.time()
    if now - local_tick_time > 300:
        return False
        
    # 2. The tick's timestamp offset from local time must be a valid timezone offset (between -12h and +14h)
    offset = tick_time - now
    if offset < -43200 or offset > 50400:
        return False
        
    # 3. Check weekly session hours if available
    if sessions:
        # Estimate current broker server time
        srv_now_ts = now + offset
        srv_now = time.gmtime(srv_now_ts) # server time treated as UTC
        wday_str = str(srv_now.tm_wday)
        
        if wday_str not in sessions:
            return False
        intervals = sessions[wday_str]
        time_of_day = srv_now.tm_hour * 3600 + srv_now.tm_min * 60 + srv_now.tm_sec
        
        in_safe_window = False
        for open_sec, close_sec in intervals:
            # Stop 5 minutes (300 seconds) after market opens and 5 minutes before market closes
            if open_sec + 300 <= time_of_day <= close_sec - 300:
                in_safe_window = True
                break
                
        if not in_safe_window:
            return False
            
    return True

def check_spread_limit_orders():
    """Calculates active spreads and triggers limit orders if price conditions are met."""
    global state
    
    # Read prices
    with state_lock:
        b1_bid = state["broker1"]["bid"]
        b1_ask = state["broker1"]["ask"]
        b2_bid = state["broker2"]["bid"]
        b2_ask = state["broker2"]["ask"]
        
        symbol1 = state["broker1"]["symbol"]
        symbol2 = state["broker2"]["symbol"]
        
        active_orders = [o for o in state["orders"] if o["status"] == "pending"]
        
    # We must have valid prices for both legs
    if b1_bid is None or b1_ask is None or b2_bid is None or b2_ask is None:
        return
        
    # Calculate spreads
    # Ask Spread (Buying the spread: Buy Leg 1 & Sell Leg 2)
    spread_ask = b1_ask - b2_bid
    # Bid Spread (Selling the spread: Sell Leg 1 & Buy Leg 2)
    spread_bid = b1_bid - b2_ask
    
    for order in active_orders:
        trigger = False
        direction = order["direction"] # "buy" or "sell"
        target = order["target_spread"]
        
        if direction == "buy":
            # Target is buying the spread at or below target price
            if spread_ask <= target:
                trigger = True
                log_message(f"[TRIGGERED]: Buy Spread reached target. Spread Ask: {spread_ask:.2f} <= Target: {target:.2f}")
        else:
            # Target is selling the spread at or above target price
            if spread_bid >= target:
                trigger = True
                log_message(f"[TRIGGERED]: Sell Spread reached target. Spread Bid: {spread_bid:.2f} >= Target: {target:.2f}")
                
        if trigger:
            # Check if both markets are open before executing
            is_b1_open = is_market_open_in_server("broker1")
            is_b2_open = is_market_open_in_server("broker2")
            if is_b1_open and is_b2_open:
                execute_spread_order(order, direction, symbol1, symbol2)
            else:
                now = time.time()
                last_warned = order.get("last_warned_closed", 0)
                if now - last_warned > 60:
                    order["last_warned_closed"] = now
                    closed_legs = []
                    if not is_b1_open:
                        closed_legs.append(f"Leg 1 ({symbol1})")
                    if not is_b2_open:
                        closed_legs.append(f"Leg 2 ({symbol2})")
                    log_message(f"[WARNING] Order #{order['id']} target spread reached, but execution postponed because market is closed for: {', '.join(closed_legs)}")

def execute_spread_order(order, direction, symbol1, symbol2):
    """Triggers parallel market orders to both workers for execution."""
    order_id = order["id"]
    
    with state_lock:
        order["status"] = "executing"
        
    with trades_lock:
        pending_trades[order_id] = {}
        
    log_message(f"Sending parallel trade commands for order {order_id}...")
    
    if direction == "buy":
        # Buy Symbol 1, Sell Symbol 2
        send_to_worker("broker1", {
            "command": "trade",
            "symbol": symbol1,
            "action": "buy",
            "volume": order["volume1"],
            "request_id": order_id,
            "broker_key": "broker1",
            "dry_run": order.get("dry_run", True)
        })
        send_to_worker("broker2", {
            "command": "trade",
            "symbol": symbol2,
            "action": "sell",
            "volume": order["volume2"],
            "request_id": order_id,
            "broker_key": "broker2",
            "dry_run": order.get("dry_run", True)
        })
    else:
        # Sell Symbol 1, Buy Symbol 2
        send_to_worker("broker1", {
            "command": "trade",
            "symbol": symbol1,
            "action": "sell",
            "volume": order["volume1"],
            "request_id": order_id,
            "broker_key": "broker1",
            "dry_run": order.get("dry_run", True)
        })
        send_to_worker("broker2", {
            "command": "trade",
            "symbol": symbol2,
            "action": "buy",
            "volume": order["volume2"],
            "request_id": order_id,
            "broker_key": "broker2",
            "dry_run": order.get("dry_run", True)
        })

def is_time_in_safe_window(t_sec, sessions):
    """Checks if a unix timestamp falls within the safe trading window of a weekly session."""
    if not sessions:
        return True
    srv_time = time.gmtime(t_sec)
    wday_str = str(srv_time.tm_wday)
    if wday_str not in sessions:
        return False
    time_of_day = srv_time.tm_hour * 3600 + srv_time.tm_min * 60 + srv_time.tm_sec
    for open_sec, close_sec in sessions[wday_str]:
        if open_sec + 300 <= time_of_day <= close_sec - 300:
            return True
    return False

# Custom Web Server API Handling
class APIHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Prevent default console flooding from simple server requests
        pass

    def end_headers(self):
        # Add CORS
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        query = parse_qs(parsed_path.query)
        
        # 1. API: Get Current State Data
        if path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            with state_lock:
                # Calculate live spreads dynamically for UI
                b1_bid = state["broker1"]["bid"]
                b1_ask = state["broker1"]["ask"]
                b2_bid = state["broker2"]["bid"]
                b2_ask = state["broker2"]["ask"]
                
                spread_info = {"ask_spread": None, "bid_spread": None}
                if b1_bid is not None and b1_ask is not None and b2_bid is not None and b2_ask is not None:
                    spread_info["ask_spread"] = b1_ask - b2_bid
                    spread_info["bid_spread"] = b1_bid - b2_ask

                    spread_info["fair_value"] = None
                    spread_info["fair_value_before"] = None
                    spread_info["asset_type"] = None
                    sym1 = state["broker1"].get("symbol", "")
                    sym2 = state["broker2"].get("symbol", "")
                    cmx_sym = None
                    oil_sym = None
                    uko_uso_sym = False
                    
                    if sym1 and sym1.startswith("CMX.MGC") and sym2 == "XAUUSD.sc":
                        cmx_sym = sym1
                    elif sym2 and sym2.startswith("CMX.MGC") and sym1 == "XAUUSD.sc":
                        cmx_sym = sym2
                        
                    if sym1 and sym1.startswith("NYX.MCLE") and "USO" in sym2:
                        oil_sym = sym1
                    elif sym2 and sym2.startswith("NYX.MCLE") and "USO" in sym1:
                        oil_sym = sym2
                        
                    if ("UKOUSD" in sym1 and "USOUSD" in sym2) or ("USOUSD" in sym1 and "UKOUSD" in sym2):
                        uko_uso_sym = True
                        
                    if cmx_sym:
                        spread_info["asset_type"] = "gold"
                        try:
                            meta_path = "historical_data/cmx/meta.json"
                            if os.path.exists(meta_path):
                                with open(meta_path, "r") as f:
                                    meta = json.load(f)
                                exp = meta.get(cmx_sym, {}).get("expiration_time", 0)
                                if exp > 0:
                                    dte = (exp - time.time()) / 86400.0
                                    if dte > 0:
                                        m, c = 0.5612, -2.5948
                                        reg_path = "historical_data/cmx/regression.json"
                                        if os.path.exists(reg_path):
                                            try:
                                                with open(reg_path, "r") as rf:
                                                    reg = json.load(rf)
                                                    m = reg.get("slope", m)
                                                    c = reg.get("intercept", c)
                                            except Exception:
                                                pass
                                        fv = m * dte + c
                                        spread_info["fair_value"] = round(fv, 2)
                        except Exception as e:
                            pass
                    elif oil_sym:
                        spread_info["asset_type"] = "oil"
                        try:
                            meta_path = "historical_data/oil/meta.json"
                            if os.path.exists(meta_path):
                                with open(meta_path, "r") as f:
                                    meta = json.load(f)
                                exp = meta.get(oil_sym, {}).get("expiration_time", 0)
                                if exp > 0:
                                    dte = (exp - time.time()) / 86400.0
                                    if dte > 0:
                                        m, c = 0, 0
                                        reg_path = "historical_data/oil/regression.json"
                                        if os.path.exists(reg_path):
                                            try:
                                                with open(reg_path, "r") as rf:
                                                    reg = json.load(rf)
                                                    m = reg.get("slope", m)
                                                    c = reg.get("intercept", c)
                                            except Exception:
                                                pass
                                        if m != 0 or c != 0:
                                            fv = m * dte + c
                                            spread_info["fair_value"] = round(fv, 2)
                        except Exception as e:
                            pass
                    elif uko_uso_sym:
                        spread_info["asset_type"] = "uko_uso"
                        try:
                            fv_path = "historical_data/uko_uso/fair_value.json"
                            if os.path.exists(fv_path):
                                with open(fv_path, "r") as f:
                                    fv_data = json.load(f)
                                    spread_info["fair_value"] = round(fv_data.get("average", 0), 2)
                                    if fv_data.get("average_before_war") is not None:
                                        spread_info["fair_value_before"] = round(fv_data.get("average_before_war"), 2)
                        except Exception as e:
                            pass
                    
                response_data = {
                    "broker1": {
                        "connected": state["broker1"]["connected"],
                        "login": state["broker1"]["login"],
                        "server": state["broker1"]["server"],
                        "symbol": state["broker1"]["symbol"],
                        "bid": b1_bid,
                        "ask": b1_ask,
                        "contract_size": state["broker1"]["contract_size"],
                        "min_volume": state["broker1"]["min_volume"],
                        "sessions": state["broker1"].get("sessions"),
                        "timezone_offset": state["broker1"].get("timezone_offset"),
                        "net_position": state["broker1"].get("net_position", 0.0)
                    },
                    "broker2": {
                        "connected": state["broker2"]["connected"],
                        "login": state["broker2"]["login"],
                        "server": state["broker2"]["server"],
                        "symbol": state["broker2"]["symbol"],
                        "bid": b2_bid,
                        "ask": b2_ask,
                        "contract_size": state["broker2"]["contract_size"],
                        "min_volume": state["broker2"]["min_volume"],
                        "sessions": state["broker2"].get("sessions"),
                        "timezone_offset": state["broker2"].get("timezone_offset"),
                        "net_position": state["broker2"].get("net_position", 0.0)
                    },
                    "spread": spread_info,
                    "orders": state["orders"],
                    "logs": state["logs"]
                }
                
            self.wfile.write(json.dumps(response_data).encode("utf-8"))
            return
            
        # 2. API: Get Saved Config
        elif path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            saved_config = load_saved_config()
            self.wfile.write(json.dumps(saved_config).encode("utf-8"))
            return
            
        # 3. API: Search symbols for recommendations
        elif path == "/api/search":
            broker = query.get("broker", ["broker1"])[0]
            q = query.get("q", [""])[0].upper()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            matches = []
            with state_lock:
                symbols = state.get(broker, {}).get("symbols", [])
                
            if q:
                # Find matching symbols starting with q, then containing q
                starts = [s for s in symbols if s.upper().startswith(q)]
                contains = [s for s in symbols if q in s.upper() and not s.upper().startswith(q)]
                matches = (starts + contains)[:10] # limit to 10
            else:
                matches = symbols[:10]
                
            self.wfile.write(json.dumps(matches).encode("utf-8"))
            return
            
        # 4. API: Get pre-configured accounts (passwords stripped)
        elif path == "/api/accounts":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            safe_accounts = [
                {k: v for k, v in acc.items() if k != "password"}
                for acc in mt5_accounts
            ]
            self.wfile.write(json.dumps(safe_accounts).encode("utf-8"))
            return
            
        # 4.5 API: Get saved favorites
        elif path == "/api/favorites":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            config = load_saved_config()
            favs = config.get("favorites", [])
            self.wfile.write(json.dumps(favs).encode("utf-8"))
            return
            
        # 4.6 API: Get historical spread data (24h, 3D, 7D)
        elif path == "/api/history":
            symbol1 = query.get("symbol1", [None])[0]
            symbol2 = query.get("symbol2", [None])[0]
            
            if not symbol1 or not symbol2:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Missing symbol1 or symbol2"}).encode("utf-8"))
                return
                
            # Verify workers are online
            with state_lock:
                conn1 = state["broker1"]["connected"]
                conn2 = state["broker2"]["connected"]
                
            if not conn1 or not conn2:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Both MT5 terminals must be initialized to retrieve history"}).encode("utf-8"))
                return
                
            request_id = str(uuid.uuid4())[:8]
            event = threading.Event()
            
            with history_lock:
                pending_history[request_id] = {
                    "event": event,
                    "broker1": None,
                    "broker2": None
                }
                
            # Request history from workers
            send_to_worker("broker1", {"command": "get_history", "symbol": symbol1, "request_id": request_id, "broker_key": "broker1"})
            send_to_worker("broker2", {"command": "get_history", "symbol": symbol2, "request_id": request_id, "broker_key": "broker2"})
            
            # Wait up to 4 seconds
            success = event.wait(timeout=4.0)
            
            with history_lock:
                res_dict = pending_history.pop(request_id, None)
                
            if not success or not res_dict or not res_dict["broker1"] or not res_dict["broker2"]:
                self.send_response(504)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Timeout waiting for historical data from MT5 workers"}).encode("utf-8"))
                return
                
            r1 = res_dict["broker1"]
            r2 = res_dict["broker2"]
            
            if not r1.get("success", False) or not r2.get("success", False):
                err = r1.get("error", "") or r2.get("error", "")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": f"Historical data fetch failed: {err}"}).encode("utf-8"))
                return
                
            bars1 = r1.get("bars", [])
            bars2 = r2.get("bars", [])
            
            # Align by timezone offset
            offset = 0
            if bars1 and bars2:
                latest_t1 = max(b["time"] for b in bars1)
                latest_t2 = max(b["time"] for b in bars2)
                offset = round((latest_t1 - latest_t2) / 3600) * 3600
                
            time_map1 = {b["time"]: b for b in bars1}
            time_map2 = {b["time"] + offset: b for b in bars2}
            
            common_times = sorted(list(set(time_map1.keys()) & set(time_map2.keys())), reverse=True)
            
            # Load Regression/FV Data for historical lines
            cmx_sym = None
            oil_sym = None
            uko_uso_sym = False
            
            if symbol1 and symbol1.startswith("CMX.MGC") and symbol2 == "XAUUSD.sc": cmx_sym = symbol1
            elif symbol2 and symbol2.startswith("CMX.MGC") and symbol1 == "XAUUSD.sc": cmx_sym = symbol2
            
            if symbol1 and symbol1.startswith("NYX.MCLE") and "USO" in symbol2: oil_sym = symbol1
            elif symbol2 and symbol2.startswith("NYX.MCLE") and "USO" in symbol1: oil_sym = symbol2
            
            if symbol1 and symbol2 and (("UKOUSD" in symbol1 and "USOUSD" in symbol2) or ("USOUSD" in symbol1 and "UKOUSD" in symbol2)):
                uko_uso_sym = True
                
            fv_m = None
            fv_c = None
            fv_exp = 0
            fv_avg = None
            fv_avg_before = None
            
            if cmx_sym:
                try:
                    if os.path.exists("historical_data/cmx/meta.json"):
                        with open("historical_data/cmx/meta.json", "r") as f:
                            meta = json.load(f)
                        # Try exact key first, then fall back to nearest expiry
                        if cmx_sym in meta:
                            fv_exp = meta[cmx_sym].get("expiration_time", 0)
                        else:
                            now_ts = time.time()
                            future = {k: v["expiration_time"] for k, v in meta.items() if v.get("expiration_time", 0) > now_ts}
                            if future:
                                fv_exp = min(future.values())
                            elif meta:
                                fv_exp = max(v.get("expiration_time", 0) for v in meta.values())
                    if os.path.exists("historical_data/cmx/regression.json"):
                        with open("historical_data/cmx/regression.json", "r") as f:
                            d = json.load(f)
                            fv_m, fv_c = d.get("slope"), d.get("intercept")
                except: pass
            elif oil_sym:
                try:
                    if os.path.exists("historical_data/oil/meta.json"):
                        with open("historical_data/oil/meta.json", "r") as f:
                            meta = json.load(f)
                        if oil_sym in meta:
                            fv_exp = meta[oil_sym].get("expiration_time", 0)
                        else:
                            now_ts = time.time()
                            future = {k: v["expiration_time"] for k, v in meta.items() if v.get("expiration_time", 0) > now_ts}
                            if future:
                                fv_exp = min(future.values())
                            elif meta:
                                fv_exp = max(v.get("expiration_time", 0) for v in meta.values())
                    if os.path.exists("historical_data/oil/regression.json"):
                        with open("historical_data/oil/regression.json", "r") as f:
                            d = json.load(f)
                            fv_m, fv_c = d.get("slope"), d.get("intercept")
                except: pass
            elif uko_uso_sym:
                try:
                    if os.path.exists("historical_data/uko_uso/fair_value.json"):
                        with open("historical_data/uko_uso/fair_value.json", "r") as f:
                            d = json.load(f)
                            fv_avg = d.get("average")
                            fv_avg_before = d.get("average_before_war")
                except: pass

            # Get sessions from state
            with state_lock:
                sessions1 = state["broker1"].get("sessions")
                sessions2 = state["broker2"].get("sessions")

            # Filter out bars adjacent to market open/close gaps (where gap > 900 seconds)
            # and daily rollover bars (23:45, 00:00, 00:15 in server time) where spreads widen
            filtered_times = []
            for idx, t in enumerate(common_times):
                # Exclude times outside the safe trading window for either broker
                if sessions1 and not is_time_in_safe_window(t, sessions1):
                    continue
                if sessions2 and not is_time_in_safe_window(t - offset, sessions2):
                    continue

                is_near_gap = False
                # Check gap to next (newer in time, i.e. idx - 1)
                if idx > 0:
                    t_next = common_times[idx - 1]
                    if t_next - t > 900:
                        is_near_gap = True
                # Check gap to prev (older in time, i.e. idx + 1)
                if idx < len(common_times) - 1:
                    t_prev = common_times[idx + 1]
                    if t - t_prev > 900:
                        is_near_gap = True
                        
                # Exclude daily rollover bars for Broker 1 (server time t)
                srv_time1 = time.gmtime(t)
                h1 = srv_time1.tm_hour
                m1 = srv_time1.tm_min
                if (h1 == 23 and m1 == 45) or (h1 == 0 and m1 in [0, 15]):
                    is_near_gap = True
                    
                # Exclude daily rollover bars for Broker 2 (server time t - offset)
                srv_time2 = time.gmtime(t - offset)
                h2 = srv_time2.tm_hour
                m2 = srv_time2.tm_min
                if (h2 == 23 and m2 == 45) or (h2 == 0 and m2 in [0, 15]):
                    is_near_gap = True
                    
                if not is_near_gap:
                    filtered_times.append(t)
            
            stats = {
                "24h": {"best_bid": None, "best_ask": None},
                "3d": {"best_bid": None, "best_ask": None},
                "7d": {"best_bid": None, "best_ask": None}
            }
            
            chart_data = []
            if filtered_times:
                anchor_time = max(filtered_times)
                for tf_name, seconds in [("24h", 86400), ("3d", 259200), ("7d", 604800)]:
                    tf_bids = []
                    tf_asks = []
                    for t in filtered_times:
                        if anchor_time - t <= seconds:
                            # Use close prices - these reflect prices that actually occurred
                            # at the same moment (end of each 15-min bar), giving realistic
                            # spread values. bid_high vs ask_low from different intra-bar
                            # moments would produce impossible (too optimistic) values.
                            bid_close1 = time_map1[t]["bid_close"]
                            ask_close2 = time_map2[t]["ask_close"]
                            tf_bids.append(bid_close1 - ask_close2)
                            
                            ask_close1 = time_map1[t]["ask_close"]
                            bid_close2 = time_map2[t]["bid_close"]
                            tf_asks.append(ask_close1 - bid_close2)
                            
                            # Build chart data during the 7d loop (since it contains all data we want to plot)
                            if tf_name == "7d":
                                # Mid Spread = ((Bid1 + Ask1)/2) - ((Bid2 + Ask2)/2)
                                # We'll use the close prices for this as well.
                                mid1 = (bid_close1 + ask_close1) / 2
                                mid2 = (bid_close2 + ask_close2) / 2
                                mid_spread = mid1 - mid2
                                
                                # Compute Fair Value historically
                                fv = None
                                fv_before = None
                                if (cmx_sym or oil_sym) and fv_m is not None and fv_c is not None and fv_exp > 0:
                                    dte = (fv_exp - t) / 86400.0
                                    fv = round(fv_m * dte + fv_c, 2)
                                elif uko_uso_sym:
                                    fv = round(fv_avg, 2) if fv_avg is not None else None
                                    fv_before = round(fv_avg_before, 2) if fv_avg_before is not None else None
                                
                                pt = {
                                    "time": t,
                                    "mid_spread": round(mid_spread, 4)
                                }
                                if fv is not None: pt["fair_value"] = fv
                                if fv_before is not None: pt["fair_value_before"] = fv_before
                                
                                chart_data.append(pt)
                            
                    if tf_bids:
                        stats[tf_name]["best_bid"] = max(tf_bids)
                    if tf_asks:
                        stats[tf_name]["best_ask"] = min(tf_asks)
            
            # Sort chart data chronologically
            chart_data.sort(key=lambda x: x["time"])
                        
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok", 
                "stats": stats,
                "chart_data": chart_data
            }).encode("utf-8"))
            return

        elif path == "/api/history_debug":
            symbol1 = query.get("symbol1", [None])[0] or "USOUSD.sc"
            symbol2 = query.get("symbol2", [None])[0] or "NYX.MCLEU6"
            with state_lock:
                conn1 = state["broker1"]["connected"]
                conn2 = state["broker2"]["connected"]
            if not conn1 or not conn2:
                self.send_response(400); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Not connected"}).encode("utf-8"))
                return
            request_id = "debug_" + str(int(time.time()))
            with history_lock:
                pending_history[request_id] = {"event": threading.Event(), "broker1": None, "broker2": None}
            send_to_worker("broker1", {"command": "get_history", "symbol": symbol1, "request_id": request_id, "broker_key": "broker1"})
            send_to_worker("broker2", {"command": "get_history", "symbol": symbol2, "request_id": request_id, "broker_key": "broker2"})
            pending_history[request_id]["event"].wait(timeout=15)
            with history_lock:
                res_dict = pending_history.pop(request_id, None)
            if not res_dict or not res_dict["broker1"] or not res_dict["broker2"]:
                self.send_response(408); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Timeout"}).encode("utf-8"))
                return
            bars1 = res_dict["broker1"].get("bars", [])
            bars2 = res_dict["broker2"].get("bars", [])
            latest_t1 = max(b["time"] for b in bars1) if bars1 else 0
            latest_t2 = max(b["time"] for b in bars2) if bars2 else 0
            offset = round((latest_t1 - latest_t2) / 3600) * 3600
            time_map1 = {b["time"]: b for b in bars1}
            time_map2 = {b["time"] + offset: b for b in bars2}
            common_times = sorted(list(set(time_map1.keys()) & set(time_map2.keys())), reverse=True)
            with state_lock:
                sessions1 = state["broker1"].get("sessions")
                sessions2 = state["broker2"].get("sessions")
            filtered_times = []
            for idx, t in enumerate(common_times):
                if sessions1 and not is_time_in_safe_window(t, sessions1): continue
                if sessions2 and not is_time_in_safe_window(t - offset, sessions2): continue
                is_near_gap = False
                if idx > 0 and common_times[idx-1] - t > 900: is_near_gap = True
                if idx < len(common_times)-1 and t - common_times[idx+1] > 900: is_near_gap = True
                s1 = time.gmtime(t); s2 = time.gmtime(t - offset)
                if (s1.tm_hour == 23 and s1.tm_min == 45) or (s1.tm_hour == 0 and s1.tm_min in [0,15]): is_near_gap = True
                if (s2.tm_hour == 23 and s2.tm_min == 45) or (s2.tm_hour == 0 and s2.tm_min in [0,15]): is_near_gap = True
                if not is_near_gap: filtered_times.append(t)
            # Compute per-bar spreads
            rows = []
            for t in filtered_times:
                b1 = time_map1[t]; b2 = time_map2[t]
                bid_sp = b1["bid_close"] - b2["ask_close"]
                ask_sp = b1["ask_close"] - b2["bid_close"]
                rows.append({
                    "time_utc": time.strftime("%m-%d %H:%M", time.gmtime(t)),
                    "b1_close": round(b1["bid_close"], 4),
                    "b2_close": round(b2["bid_close"], 4),
                    "bid_spread": round(bid_sp, 4),
                    "ask_spread": round(ask_sp, 4),
                })
            rows_by_bid = sorted(rows, key=lambda r: r["bid_spread"], reverse=True)
            rows_by_ask = sorted(rows, key=lambda r: r["ask_spread"])
            debug_info = {
                "total_common_bars": len(common_times),
                "total_filtered_bars": len(filtered_times),
                "offset_hours": offset / 3600,
                "latest_t1_utc": time.strftime("%m-%d %H:%M", time.gmtime(latest_t1)),
                "latest_t2_utc": time.strftime("%m-%d %H:%M", time.gmtime(latest_t2)),
                "top10_highest_bid": rows_by_bid[:10],
                "top10_lowest_ask": rows_by_ask[:10],
                "b1_close_range": [round(min(r["b1_close"] for r in rows),4), round(max(r["b1_close"] for r in rows),4)] if rows else None,
                "b2_close_range": [round(min(r["b2_close"] for r in rows),4), round(max(r["b2_close"] for r in rows),4)] if rows else None,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(debug_info, indent=2).encode("utf-8"))
            return
            
        elif path == "/api/cmx_chart_data":
            try:
                data = cmx_data_manager.get_chart_data()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if path == "/api/oil_chart_data":
            try:
                data = oil_data_manager.get_chart_data()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if path == "/api/tfx_chart_data":
            try:
                data = tfx_data_manager.get_chart_data()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return


        if path == "/api/uko_uso_chart_data":
            try:
                data = uko_uso_data_manager.get_chart_data()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if path == "/api/uko_uso_fetch":
            try:
                res = uko_uso_data_manager.fetch_and_store()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        # Standard: Serve HTML/CSS/JS files
        else:
            # Default to index.html
            if path == "/" or path == "":
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        # Helper to read JSON
        def read_json():
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            return json.loads(post_data.decode("utf-8"))
            
        # 1. API: Connect to Terminals using pre-configured account IDs
        if path == "/api/connect":
            try:
                data = read_json()
                config = data.get("config", {})
                
                # Save config
                save_config(config)
                
                b1 = config.get("broker1", {})
                acc1_id = b1.get("accountId")
                
                b2 = config.get("broker2", {})
                acc2_id = b2.get("accountId")
                
                global is_sharing_worker
                is_sharing_worker = (acc1_id == acc2_id)
                
                # Setup Broker 1
                acc1 = next((a for a in mt5_accounts if a["id"] == acc1_id), None)
                if not acc1:
                    raise Exception(f"Account '{acc1_id}' not found in pre-configured credentials")
                
                start_worker("broker1", b1.get("path"))
                send_to_worker("broker1", {
                    "command": "initialize",
                    "path": b1.get("path"),
                    "login": acc1["login"],
                    "password": acc1["password"],
                    "server": acc1["server"]
                })
                    
                # Setup Broker 2
                acc2 = next((a for a in mt5_accounts if a["id"] == acc2_id), None)
                if not acc2:
                    raise Exception(f"Account '{acc2_id}' not found in pre-configured credentials")
                
                if is_sharing_worker:
                    stop_worker("broker2")
                    log_message("Single MT5 terminal shared login detected. Broker 2 will share connection with Broker 1.")
                else:
                    time.sleep(2) # Prevent MT5 initialization race conditions
                    start_worker("broker2", b2.get("path"))
                    send_to_worker("broker2", {
                        "command": "initialize",
                        "path": b2.get("path"),
                        "login": acc2["login"],
                        "password": acc2["password"],
                        "server": acc2["server"]
                    })
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "message": "Connection commands sent"}).encode("utf-8"))
                
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return
            
        # 2. API: Disconnect
        elif path == "/api/disconnect":
            stop_worker("broker1")
            stop_worker("broker2")
            
            with state_lock:
                state["broker1"]["connected"] = False
                state["broker1"]["bid"] = None
                state["broker1"]["ask"] = None
                state["broker2"]["connected"] = False
                state["broker2"]["bid"] = None
                state["broker2"]["ask"] = None
                
            log_message("Disconnected both MT5 terminals.")
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            return
            
        # 3. API: Subscribe Symbols
        elif path == "/api/subscribe":
            try:
                data = read_json()
                symbol1 = data.get("symbol1")
                symbol2 = data.get("symbol2")
                
                with state_lock:
                    state["broker1"]["symbol"] = symbol1
                    state["broker1"]["bid"] = None
                    state["broker1"]["ask"] = None
                    
                    state["broker2"]["symbol"] = symbol2
                    state["broker2"]["bid"] = None
                    state["broker2"]["ask"] = None
                
                if symbol1:
                    send_to_worker("broker1", {"command": "subscribe", "symbol": symbol1})
                if symbol2:
                    send_to_worker("broker2", {"command": "subscribe", "symbol": symbol2})
                    
                log_message(f"Subscribed to Symbol 1: {symbol1} and Symbol 2: {symbol2}")
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return
            
        # 4. API: Create Spread Limit Order
        elif path == "/api/order":
            try:
                data = read_json()
                
                # Check symbols are selected
                with state_lock:
                    s1 = state["broker1"]["symbol"]
                    s2 = state["broker2"]["symbol"]
                    
                if not s1 or not s2:
                    raise Exception("Please select symbols for both brokers first")
                    
                order = {
                    "id": str(uuid.uuid4())[:8], # unique 8-character ID
                    "symbol1": s1,
                    "symbol2": s2,
                    "direction": data.get("direction"), # "buy" or "sell"
                    "volume1": float(data.get("volume1")),
                    "volume2": float(data.get("volume2")),
                    "target_spread": float(data.get("target_spread")),
                    "dry_run": bool(data.get("dry_run", True)),
                    "status": "pending",
                    "time": time.strftime("%H:%M:%S")
                }
                
                with state_lock:
                    state["orders"].append(order)
                    
                mode_str = "[DRY RUN]" if order["dry_run"] else "[LIVE]"
                log_message(f"{mode_str} [ORDER PLACED] {order['direction'].upper()} Spread. Vol1: {order['volume1']}, Vol2: {order['volume2']}, Target Spread: {order['target_spread']:.2f}")
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "order": order}).encode("utf-8"))
                
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return
            
        # 5. API: Cancel Spread Order
        elif path == "/api/order/cancel":
            try:
                data = read_json()
                order_id = data.get("order_id")
                
                cancelled = False
                with state_lock:
                    for o in state["orders"]:
                        if o["id"] == order_id and o["status"] == "pending":
                            o["status"] = "cancelled"
                            cancelled = True
                            break
                            
                if cancelled:
                    log_message(f"[ORDER CANCELLED] Spread order {order_id}")
                    
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok" if cancelled else "not_found"}).encode("utf-8"))
                
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return
            
        # 6. API: Save Favorite
        elif path == "/api/favorites/save":
            try:
                data = read_json()
                name = data.get("name")
                b1 = data.get("broker1")
                b2 = data.get("broker2")
                
                if not name or not b1 or not b2:
                    raise Exception("Missing name, broker1, or broker2 config data")
                    
                config = load_saved_config()
                if "favorites" not in config:
                    config["favorites"] = []
                    
                # Create and append new favorite
                fav = {
                    "id": str(uuid.uuid4())[:8],
                    "name": name,
                    "broker1": b1,
                    "broker2": b2
                }
                config["favorites"].append(fav)
                save_config(config)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "favorite": fav}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return
            
        # 7. API: Delete Favorite
        elif path == "/api/favorites/delete":
            try:
                data = read_json()
                fav_id = data.get("id")
                if not fav_id:
                    raise Exception("Missing favorite id")
                    
                config = load_saved_config()
                favs = config.get("favorites", [])
                config["favorites"] = [f for f in favs if f["id"] != fav_id]
                save_config(config)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        if path == "/api/uko_uso_chart_data":
            try:
                data = uko_uso_data_manager.get_chart_data()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if path == "/api/oil_fetch":
            try:
                res = oil_data_manager.fetch_and_store()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        if path == "/api/tfx_fetch":
            try:
                tfx_data_manager.fetch_new_data()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return
            
        if path == "/api/uko_uso_fetch":
            try:
                res = uko_uso_data_manager.fetch_and_store()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return
            
        # 8. API: Fetch CMX Data
        elif path == "/api/cmx_fetch":
            try:
                # We need to run this in a thread so it doesn't block the main server thread
                # However, since the user explicitly clicks it, we can return the response when done
                res = cmx_data_manager.fetch_and_store()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

def shutdown_server():
    """Shuts down active worker subprocesses on exit."""
    log_message("Shutting down workers...")
    stop_worker("broker1")
    stop_worker("broker2")
    time.sleep(0.5)

def main():
    PORT = 8080
    max_retries = 10
    server = None
    
    # Enable socket address reuse to prevent WinError 10048
    ThreadingTCPServer.allow_reuse_address = True
    
    for i in range(max_retries):
        current_port = PORT + i
        try:
            # Enable threading in the TCP server for concurrent polling and asset serving
            server = ThreadingTCPServer(("0.0.0.0", current_port), APIHandler)
            log_message(f"Starting Multi-Broker Spread Master Server on http://localhost:{current_port}")
            
            # Automatically open the web UI in browser
            try:
                import webbrowser
                webbrowser.open(f"http://localhost:{current_port}")
            except Exception as e:
                log_message(f"Could not open browser automatically: {e}")
                
            break
        except OSError as e:
            # Catch all bind errors (e.g. 10048 address in use, 10013 permission forbidden) and try next port
            print(f"Port {current_port} is unavailable ({e}), trying next port...")
            continue
                
    if not server:
        log_message("Failed to bind to any port in the range 8080-8089. Please ensure other processes are not blocking these ports.")
        return
    
    # Ensure subprocesses exit clean
    import atexit
    atexit.register(shutdown_server)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log_message("Server closed.")

if __name__ == "__main__":
    main()
