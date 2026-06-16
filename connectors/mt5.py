import os
from dotenv import load_dotenv

load_dotenv()

ORDER_TYPE_MAP = {
    0: "BUY_LIMIT",
    1: "SELL_LIMIT",
    2: "BUY_STOP",
    3: "SELL_STOP",
    4: "BUY_STOP_LIMIT",
    5: "SELL_STOP_LIMIT",
}


def _load_account_configs() -> list[dict]:
    """Read all MT5 account configs from .env. Account 1 uses no suffix; account 2+ use _2, _3, ..."""
    configs = []

    # Account 1 (no suffix)
    login = os.getenv("MT5_LOGIN", "").strip()
    password = os.getenv("MT5_PASSWORD", "").strip()
    server = os.getenv("MT5_SERVER", "").strip()
    if login and password and server:
        name = os.getenv("MT5_NAME", "MT5 (1)").strip()
        configs.append({"label": name, "login": login, "password": password, "server": server})

    # Accounts 2+ (numeric suffix)
    for i in range(2, 10):
        login = os.getenv(f"MT5_LOGIN_{i}", "").strip()
        password = os.getenv(f"MT5_PASSWORD_{i}", "").strip()
        server = os.getenv(f"MT5_SERVER_{i}", "").strip()
        if login and password and server:
            name = os.getenv(f"MT5_NAME_{i}", f"MT5 ({i})").strip()
            configs.append({"label": name, "login": login, "password": password, "server": server})

    return configs


def _fetch_account(mt5, cfg: dict) -> dict:
    label = cfg["label"]
    login = int(cfg["login"])
    password = cfg["password"]
    server = cfg["server"]

    print(f"  [MT5] Logging in to account {label} (login={login}, server={server})...")
    authorized = mt5.login(login, password=password, server=server)
    if not authorized:
        raise RuntimeError(f"MT5 login failed for account {label}: {mt5.last_error()}")

    # Account info
    info = mt5.account_info()
    if info is None:
        raise RuntimeError(f"Could not get account info for account {label}: {mt5.last_error()}")

    account_info = {
        "login": info.login,
        "name": info.name,
        "server": info.server,
        "currency": info.currency,
        "leverage": info.leverage,
        "balance": info.balance,
        "equity": info.equity,
        "margin": info.margin,
        "free_margin": info.margin_free,
        "margin_level": info.margin_level,
        "profit": info.profit,
    }

    # Open positions
    raw_positions = mt5.positions_get()
    open_positions = []
    if raw_positions:
        for p in raw_positions:
            info = mt5.symbol_info(p.symbol)
            contract_size = info.trade_contract_size if info else 1.0
            
            # Custom overrides for contract size (Broker configuration fallback)
            override_map = {
                "CMX.MGC": 10.0,
                "NYX.MCLE": 100.0,
                "CME.MES": 5.0,    # Micro S&P 500
                "CME.MNQ": 2.0,    # Micro Nasdaq
                "CME.MYM": 0.5,    # Micro Dow
                "CME.MBT": 0.1,    # Micro Bitcoin
                "CME.MET": 0.1,    # Micro Ether
            }
            for pattern, size in override_map.items():
                if pattern in p.symbol:
                    contract_size = size
                    break
                
            side = "BUY" if p.type == 0 else "SELL"
            vol = p.volume * contract_size
            if side == "SELL":
                vol = -vol
                
            open_positions.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": side,
                "volume": vol,
                "open_price": p.price_open,
                "current_price": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "swap": p.swap,
                "comment": p.comment,
            })
    print(f"  [MT5] Account {label}: {len(open_positions)} open position(s)")

    # Pending orders
    raw_orders = mt5.orders_get()
    open_orders = []
    if raw_orders:
        for o in raw_orders:
            info = mt5.symbol_info(o.symbol)
            contract_size = info.trade_contract_size if info else 1.0
            
            # Custom overrides for contract size (Broker configuration fallback)
            override_map = {
                "CMX.MGC": 10.0,
                "NYX.MCLE": 100.0,
                "CME.MES": 5.0,    # Micro S&P 500
                "CME.MNQ": 2.0,    # Micro Nasdaq
                "CME.MYM": 0.5,    # Micro Dow
                "CME.MBT": 0.1,    # Micro Bitcoin
                "CME.MET": 0.1,    # Micro Ether
            }
            for pattern, size in override_map.items():
                if pattern in o.symbol:
                    contract_size = size
                    break
                
            order_type = ORDER_TYPE_MAP.get(o.type, str(o.type))
            vol = o.volume_initial * contract_size
                
            open_orders.append({
                "ticket": o.ticket,
                "symbol": o.symbol,
                "type": order_type,
                "volume": vol,
                "price": o.price_open,
                "sl": o.sl,
                "tp": o.tp,
                "comment": o.comment,
            })
    print(f"  [MT5] Account {label}: {len(open_orders)} open order(s)")

    return {
        "label": label,
        "account_info": account_info,
        "open_positions": open_positions,
        "open_orders": open_orders,
    }


def fetch() -> dict:
    configs = _load_account_configs()
    if not configs:
        raise ValueError(
            "No MT5 accounts configured. Set MT5_LOGIN/MT5_PASSWORD/MT5_SERVER "
            "and optionally MT5_LOGIN_2/MT5_PASSWORD_2/MT5_SERVER_2 in .env"
        )

    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise ImportError("MetaTrader5 package is not installed. Run: pip install MetaTrader5")

    print(f"  [MT5] Initializing terminal ({len(configs)} account(s) configured)...")
    if not mt5.initialize():
        raise RuntimeError(
            f"MT5 terminal is not running or could not be initialized. "
            f"Please open MetaTrader5 first. Error: {mt5.last_error()}"
        )

    accounts = []
    try:
        for cfg in configs:
            try:
                account_data = _fetch_account(mt5, cfg)
                accounts.append(account_data)
            except Exception as e:
                print(f"  [MT5] ERROR fetching account {cfg['label']}: {e}")
    finally:
        mt5.shutdown()

    if not accounts:
        raise RuntimeError("All MT5 accounts failed to fetch.")

    return {
        "platform": "MT5",
        "accounts": accounts,
    }
