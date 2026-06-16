"""Replicate the wheel equity model and search for action recommendations."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, ".data_cache.json")))
PT = json.load(open(os.path.join(HERE, "wheel_pricetable.json")))

BALANCE = next(a for a in D["account_summaries"] if a["currency"] == "BTC")["balance"]
PERP_ENTRY = D["perpetual_settlement"]["price"]      # 63161.96
FUTURE_ADJ = 1157                                    # kept notional (USD)
EXTERNAL = 6.9659
USABLE = EXTERNAL + BALANCE

LEVELS = [60000, 55000, 50000, 45000, 40000, 35000, 30000]
SCN = [None, 60000, 55000, 50000, 45000, 40000, 35000, 30000, 25000, 20000, 15000]
MIN_BTC = 7.01


def parse(name):
    p = name.split("-")
    if len(p) < 4:
        return None
    try:
        return {"expiry": p[1], "strike": int(p[2]), "type": p[3]}
    except ValueError:
        return None


def _interp(row, K):
    ks = sorted(int(k) for k in row)
    if K <= ks[0]:
        return row[str(ks[0])]
    if K >= ks[-1]:
        return row[str(ks[-1])]
    for i in range(len(ks) - 1):
        if ks[i] <= K <= ks[i + 1]:
            t = (K - ks[i]) / (ks[i + 1] - ks[i])
            return row[str(ks[i])] + t * (row[str(ks[i + 1])] - row[str(ks[i])])
    return row[str(ks[-1])]


def call_price(L, K):
    row = PT["call"].get(str(L))
    return _interp(row, K) if row else 0


def put_price(L, K):
    row = PT["put"].get(str(L))
    return _interp(row, K) if row else 0


def existing_put_settle(X):
    if not X:
        return 0.0
    v = 0.0
    for p in D["open_positions"]:
        info = parse(p["instrument"])
        if not info or info["expiry"] != "25DEC26" or info["type"] != "P":
            continue
        payoff = max(info["strike"] - X, 0) / X
        v += (1 if p["direction"] == "buy" else -1) * abs(p["size"]) * payoff
    return v


def existing_deriv(P):
    v = 0.0
    v += FUTURE_ADJ * (1 / PERP_ENTRY - 1 / P)        # kept futures notional
    for p in D["open_positions"]:
        info = parse(p["instrument"])
        if info and info["expiry"] == "26MAR27" and info["type"] == "C":
            sign = 1 if p["direction"] == "buy" else -1
            v += sign * abs(p["size"]) * max(P - info["strike"], 0) / P
    for o in D["open_orders"]:
        info = parse(o["instrument"])
        sign = 1 if o["direction"] == "buy" else -1
        amt = abs(o.get("amount") or 0)
        if info and info["expiry"] == "26MAR27" and info["type"] == "C":
            v += sign * amt * (max(P - info["strike"], 0) / P - (o.get("price") or 0))
        elif not info:
            e = o.get("price") or 0
            if e > 0:
                v += sign * amt * (1 / e - 1 / P)
    return v


def equity(P, X, items):
    eq = USABLE + existing_put_settle(X) + existing_deriv(P)
    for it in items:
        qty = it.get("qty") or 0
        if not qty:
            continue
        L = it["level"]
        if X is None or L < X:
            continue
        K = it.get("strike") or L
        t = it["type"]
        if t == "long_call":
            eq += qty * max(P - K, 0) / P - qty * call_price(L, K)
        elif t == "short_call":
            eq += qty * call_price(L, K) - qty * max(P - K, 0) / P
        elif t == "long_future":
            eq += qty * (P - L) / P
        elif t == "short_put":
            eq += qty * put_price(L, K) - qty * max(K - X, 0) / X
    return eq


XS = list(range(10000, 100001, 2000))


def metrics(items):
    worst = float("inf")
    spread_sum = 0.0
    spread_n = 0
    for P in XS:
        vals = []
        for X in SCN:
            floor = 60000 if X is None else X
            if P >= floor:
                e = equity(P, X, items)
                vals.append(e)
                worst = min(worst, e)
        if vals:
            spread_sum += max(vals) - min(vals)
            spread_n += 1
    target = equity(80000, 50000, items)
    return {"worst": worst, "target": target, "spread": spread_sum / spread_n}


if __name__ == "__main__":
    # validate against the JS baseline (current saved config)
    cur = json.load(open(os.path.join(HERE, "wheel_config.json")))["items"]
    m = metrics(cur)
    print("BASELINE  worst=%.3f  target=%.3f  spread=%.3f  (usable=%.4f, bal=%.4f)"
          % (m["worst"], m["target"], m["spread"], USABLE, BALANCE))
