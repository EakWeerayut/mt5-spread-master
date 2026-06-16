"""
Wheel strategy backend: option fair-price table, config persistence.

Model notes (buy side; sell side handled separately later):
- Buy action levels: 60000 -> 30000 step 5000.
- Each level has up to 4 actions: Long Call 26MAR27, Short Call 26MAR27,
  Long Future, Short Put 25DEC26. User supplies qty + strike (5000 steps).
- Option fair price = mid(bid, ask) when both present, else mark_price (BTC units).
  For strikes outside the listed chain we extrapolate intrinsic + nearest time value.
- The price table is computed on demand (refresh) and cached to disk so it is
  stable between edits.
"""
import os
import json
import math
from datetime import datetime
from option import _bs_price, _implied_vol

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "wheel_config.json")
PRICETABLE_PATH = os.path.join(HERE, "wheel_pricetable.json")
SNAPSHOTS_PATH = os.path.join(HERE, "wheel_snapshots.json")

CALL_EXPIRY = "26MAR27"
PUT_EXPIRY = "25DEC26"
CALL_EXPIRY_DATE = datetime(2027, 3, 26)
PUT_EXPIRY_DATE = datetime(2026, 12, 25)

# Strikes we expose in the table (covers action strikes incl. high covered calls)
TABLE_STRIKES = list(range(10000, 205000, 5000))

DEFAULT_CONFIG = {
    "external_btc": 0.0,        # BTC held OUTSIDE Deribit; usable = external + Deribit balance
    "min_btc": 1.0,             # flat minimum BTC (used when min_curve empty)
    "min_curve": [],            # [{price, btc}] minimum floor at/above min_flat_price
    "min_flat_price": 65000,    # below this BTC price, the flat min_btc applies
    "hidden_scenarios": [],     # scenario line names hidden by checkbox (view preference)
    "cover_price": None,        # short calls with strike >= this are treated as covered
    "future_adj": None,         # adjusted long-future notional (USD); null -> use actual position
    "items": [],                # [ {"type":"long_call","level":60000,"qty":0.8,"strike":60000}, ... ]
    "level_dates": [],          # [{level, date}] date the level is expected to be reached (YYYY-MM-01);
                                # used to reprice premiums at the remaining time-to-expiry
    "current_level": None,      # the level price has dropped to; null = "never < 60k" (no level passed yet)
}

LEVELS = list(range(60000, 25000, -5000))  # 60000..30000
ACTION_KEYS = ["long_call", "short_call", "long_future", "short_put"]


def _parse(name):
    p = name.split("-")
    if len(p) < 4:
        return None
    try:
        return {"expiry": p[1], "strike": int(p[2]), "type": p[3]}
    except ValueError:
        return None


def _interp(points, x):
    """Linear interpolation over sorted (x, y) points; flat extrapolation."""
    if not points:
        return None
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0) if x1 != x0 else 0
            return y0 + t * (y1 - y0)
    return points[-1][1]


def _iv_smile(option_chain, expiry, typ, S):
    """Build sorted [(strike, sigma)] from the chain's mark_iv (or implied from mark)."""
    pts = []
    for o in option_chain:
        info = _parse(o["instrument_name"])
        if not info or info["expiry"] != expiry or info["type"] != typ:
            continue
        iv = o.get("mark_iv")
        if iv and iv > 0:
            sigma = iv / 100.0
        else:
            mark = o.get("mark_price")
            if not mark or not S:
                continue
            T = 0.5
            raw = _implied_vol(mark * S, S, info["strike"], T, typ)
            if not raw:
                continue
            sigma = raw
        pts.append((info["strike"], sigma))
    return sorted(set(pts))


def _years_to(expiry_date):
    return max((expiry_date - datetime.now()).days / 365.0, 1e-6)


def _forward_for(option_chain, expiry):
    """Average underlying (forward) price for an expiry from the chain."""
    vals = [o.get("underlying_price") for o in option_chain
            if (_parse(o["instrument_name"]) or {}).get("expiry") == expiry
            and o.get("underlying_price")]
    return sum(vals) / len(vals) if vals else None


def compute_price_table(option_chain, spot):
    """2-D fair-price table: price[type][level][strike] in BTC.

    Premium is what you'd pay/receive when the option is traded at the moment
    BTC spot equals the execution level L (not at the current spot). We reprice
    with Black-Scholes using the current IV smile (sticky-strike) and current
    time-to-expiry held constant.
    """
    call_smile = _iv_smile(option_chain, CALL_EXPIRY, "C", spot)
    put_smile = _iv_smile(option_chain, PUT_EXPIRY, "P", spot)
    T_call = _years_to(CALL_EXPIRY_DATE)
    T_put = _years_to(PUT_EXPIRY_DATE)

    # Options are priced off the FORWARD, not spot. Forward = spot * basis,
    # where basis (contango) is taken from the current chain and held constant.
    fwd_call = _forward_for(option_chain, CALL_EXPIRY) or spot
    fwd_put = _forward_for(option_chain, PUT_EXPIRY) or spot
    basis_call = (fwd_call / spot) if spot else 1.0
    basis_put = (fwd_put / spot) if spot else 1.0

    # Annualized cost-of-carry implied by the chain's forward basis, held constant.
    # forward(T') = level * exp(rate * T'), so the client can reprice at any remaining time.
    rate_call = math.log(basis_call) / T_call if basis_call > 0 else 0.0
    rate_put = math.log(basis_put) / T_put if basis_put > 0 else 0.0

    table = {
        "spot": spot,
        "call_expiry": CALL_EXPIRY,
        "put_expiry": PUT_EXPIRY,
        "call_expiry_date": CALL_EXPIRY_DATE.date().isoformat(),
        "put_expiry_date": PUT_EXPIRY_DATE.date().isoformat(),
        "fwd_call": round(fwd_call, 2),
        "fwd_put": round(fwd_put, 2),
        "basis_call": round(basis_call, 5),
        "basis_put": round(basis_put, 5),
        # Raw repricing inputs (client-side Black-Scholes at a user-assigned date per level)
        "T_call": round(T_call, 6),
        "T_put": round(T_put, 6),
        "rate_call": round(rate_call, 6),
        "rate_put": round(rate_put, 6),
        "call_smile": [[k, round(s, 6)] for k, s in call_smile],
        "put_smile": [[k, round(s, 6)] for k, s in put_smile],
        "levels": LEVELS,
        "strikes": TABLE_STRIKES,
        "call": {},   # call[L][K]
        "put": {},    # put[L][K]
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }
    for L in LEVELS:
        # forward at the moment spot == level L (basis assumed constant)
        Fc = L * basis_call
        Fp = L * basis_put
        c_row, p_row = {}, {}
        for K in TABLE_STRIKES:
            sig_c = _interp(call_smile, K) or 0.6
            sig_p = _interp(put_smile, K) or 0.6
            c_usd = _bs_price(Fc, K, T_call, sig_c, "C")
            p_usd = _bs_price(Fp, K, T_put, sig_p, "P")
            c_row[str(K)] = round(c_usd / Fc, 6)   # BTC premium (priced off forward)
            p_row[str(K)] = round(p_usd / Fp, 6)
        table["call"][str(L)] = c_row
        table["put"][str(L)] = p_row
    return table


def save_price_table(table):
    with open(PRICETABLE_PATH, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)


def load_price_table():
    if os.path.exists(PRICETABLE_PATH):
        with open(PRICETABLE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    clean = {
        "external_btc": cfg.get("external_btc", 0.0),
        "min_btc": cfg.get("min_btc", 1.0),
        "min_curve": cfg.get("min_curve", []),
        "min_flat_price": cfg.get("min_flat_price", 65000),
        "hidden_scenarios": cfg.get("hidden_scenarios", []),
        "cover_price": cfg.get("cover_price"),
        "future_adj": cfg.get("future_adj"),
        "items": cfg.get("items", []),
        "level_dates": cfg.get("level_dates", []),
        "current_level": cfg.get("current_level"),
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)
    return clean


def load_snapshots():
    if os.path.exists(SNAPSHOTS_PATH):
        try:
            with open(SNAPSHOTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_snapshots(d):
    with open(SNAPSHOTS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f)


def net_premium_existing(positions):
    """Net premium of existing option positions in BTC.
    Long (buy) = premium paid (cost, subtract). Short (sell) = received (add).
    Returns premium PAID (positive = net cost in BTC)."""
    paid = 0.0
    for p in positions:
        info = _parse(p.get("instrument", ""))
        if not info:
            continue  # skip perpetual/futures
        size = abs(p.get("size", 0))
        avg = p.get("average_price", 0) or 0
        if p.get("direction") == "buy":
            paid += size * avg
        else:
            paid -= size * avg
    return paid
