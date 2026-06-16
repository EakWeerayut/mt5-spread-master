"""Faithful Python port of the dashboard's wheel equity model (index.html).

Replicates: smile-based BS repricing (callPrice/putPrice), cover-aware callSettle,
existing put/deriv settlement, price-dependent min floor, and equityAt.
Use as a library for optimisation / scenario building.
"""
import json, os, math
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
YEAR_MS = 365 * 24 * 3600 * 1000

def _ts(d):  # ISO date -> ms epoch
    return datetime.strptime(d[:10], "%Y-%m-%d").timestamp() * 1000

def parse(name):
    p = name.split("-")
    if len(p) < 4: return None
    try: return {"expiry": p[1], "strike": int(p[2]), "type": p[3]}
    except ValueError: return None

# ---- futures position (entry from perp settlement); uses global D ----
def futures_position():
    notional = 0.0; esum = 0.0; absum = 0.0
    settle = (D.get("perpetual_settlement") or {}).get("price")
    for p in D["open_positions"]:
        if parse(p["instrument"]): continue
        sign = 1 if p["direction"] == "buy" else -1
        sz = abs(p["size"]); notional += sign * sz
        e = settle if (p["instrument"] == "BTC-PERPETUAL" and settle) else (p.get("average_price") or 0)
        if e > 0: esum += sz * e; absum += sz
    return notional, (esum/absum if absum else 0)

# State globals (set by configure()). Defaults filled from files at import.
D = PT = CFG = None
BALANCE = EXTERNAL = USABLE = COVER = MIN_BTC = MIN_FLAT = None
MIN_CURVE = FUTURE_ADJ = LEVEL_DATES = None
CALL_EXP = PUT_EXP = RATE_C = RATE_P = CALL_SMILE = PUT_SMILE = None
FP_NOTIONAL = FP_ENTRY = None

def configure(cfg, data, pt):
    """Inject the model state (config + Deribit data + price table). Lets the
    optimiser/server run on whatever is live on screen, not stale files."""
    global D, PT, CFG, BALANCE, EXTERNAL, USABLE, COVER, MIN_BTC, MIN_FLAT
    global MIN_CURVE, FUTURE_ADJ, LEVEL_DATES, CALL_EXP, PUT_EXP, RATE_C, RATE_P
    global CALL_SMILE, PUT_SMILE, FP_NOTIONAL, FP_ENTRY
    CFG, D, PT = cfg, data, pt
    BALANCE  = next(a for a in D["account_summaries"] if a["currency"] == "BTC")["balance"]
    EXTERNAL = CFG.get("external_btc", 0)
    USABLE   = EXTERNAL + BALANCE
    COVER    = CFG.get("cover_price")
    MIN_BTC  = CFG.get("min_btc", 0)
    MIN_FLAT = CFG.get("min_flat_price", 65000)
    MIN_CURVE = [p for p in (CFG.get("min_curve") or []) if p.get("price") is not None and p.get("btc") is not None]
    FUTURE_ADJ = CFG.get("future_adj")
    LEVEL_DATES = [p for p in (CFG.get("level_dates") or []) if p.get("level") is not None and p.get("date")]
    CALL_EXP = _ts(PT["call_expiry_date"]); PUT_EXP = _ts(PT["put_expiry_date"])
    RATE_C = PT.get("rate_call", 0); RATE_P = PT.get("rate_put", 0)
    CALL_SMILE = PT["call_smile"]; PUT_SMILE = PT["put_smile"]
    FP_NOTIONAL, FP_ENTRY = futures_position()

def load_files():
    configure(json.load(open(os.path.join(HERE, "wheel_config.json"))),
              json.load(open(os.path.join(HERE, ".data_cache.json"))),
              json.load(open(os.path.join(HERE, "wheel_pricetable.json"))))

load_files()   # default state from disk (CLI use)

# ---- BS smile repricing ----
def _smile_sigma(smile, K):
    if not smile: return 0.6
    if K <= smile[0][0]: return smile[0][1]
    if K >= smile[-1][0]: return smile[-1][1]
    for i in range(len(smile)-1):
        if smile[i][0] <= K <= smile[i+1][0]:
            t = (K-smile[i][0])/(smile[i+1][0]-smile[i][0])
            return smile[i][1] + t*(smile[i+1][1]-smile[i][1])
    return smile[-1][1]

def _ncdf(x):
    return 0.5*(1+math.erf(x/math.sqrt(2)))

def _bs_usd(F, K, T, sigma, typ):
    if T <= 0 or sigma <= 0:
        return max(F-K,0) if typ=="C" else max(K-F,0)
    d1 = (math.log(F/K)+0.5*sigma*sigma*T)/(sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    if typ=="C": return F*_ncdf(d1) - K*_ncdf(d2)
    return K*_ncdf(-d2) - F*_ncdf(-d1)

def assigned_date_ms(L):
    a = sorted(LEVEL_DATES, key=lambda p: p["level"])
    if not a: return datetime.now().timestamp()*1000
    if L <= a[0]["level"]:  return _ts(a[0]["date"])
    if L >= a[-1]["level"]: return _ts(a[-1]["date"])
    for i in range(len(a)-1):
        if a[i]["level"] <= L <= a[i+1]["level"]:
            t = (L-a[i]["level"])/(a[i+1]["level"]-a[i]["level"])
            return _ts(a[i]["date"]) + t*(_ts(a[i+1]["date"])-_ts(a[i]["date"]))
    return _ts(a[-1]["date"])

def _t_to_expiry(exp_ms, L):
    return max((exp_ms - assigned_date_ms(L))/YEAR_MS, 1e-6)

def call_price(L, K):
    T = _t_to_expiry(CALL_EXP, L); F = L*math.exp(RATE_C*T)
    return _bs_usd(F, K, T, _smile_sigma(CALL_SMILE, K), "C")/F

def put_price(L, K):
    T = _t_to_expiry(PUT_EXP, L); F = L*math.exp(RATE_P*T)
    return _bs_usd(F, K, T, _smile_sigma(PUT_SMILE, K), "P")/F

def call_settle(K, P):
    if COVER and K >= COVER: return 1.0 if P >= K else 0.0
    return max(P-K,0)/P

def existing_put_settle(P):
    v = 0.0
    for p in D["open_positions"]:
        info = parse(p["instrument"])
        if not info or info["expiry"]!="25DEC26" or info["type"]!="P": continue
        payoff = max(info["strike"]-P,0)/P
        v += (1 if p["direction"]=="buy" else -1)*abs(p["size"])*payoff
    return v

def existing_deriv(P):
    v = 0.0
    if FP_ENTRY>0 and FP_NOTIONAL!=0:
        adjN = FUTURE_ADJ if FUTURE_ADJ is not None else FP_NOTIONAL
        v += adjN*(1/FP_ENTRY - 1/P)
    for p in D["open_positions"]:
        info = parse(p["instrument"])
        if info and info["expiry"]=="26MAR27" and info["type"]=="C":
            sign = 1 if p["direction"]=="buy" else -1
            v += sign*abs(p["size"])*call_settle(info["strike"], P)
    # (no 26MAR27 C orders or futures orders in current data)
    return v

def min_at(P):
    if P < MIN_FLAT: return MIN_BTC
    if not MIN_CURVE: return MIN_BTC
    pts = sorted(MIN_CURVE, key=lambda p: p["price"])
    if P <= pts[0]["price"]:  return pts[0]["btc"]
    if P >= pts[-1]["price"]: return pts[-1]["btc"]
    for i in range(len(pts)-1):
        if pts[i]["price"] <= P <= pts[i+1]["price"]:
            t = (P-pts[i]["price"])/(pts[i+1]["price"]-pts[i]["price"])
            return pts[i]["btc"] + t*(pts[i+1]["btc"]-pts[i]["btc"])
    return pts[-1]["btc"]

def equity(P, X, items):
    eq = USABLE + existing_put_settle(P) + existing_deriv(P)
    for it in items:
        qty = it.get("qty") or 0
        if not qty: continue
        L = it["level"]
        if X is None or L < X: continue
        K = it.get("strike") or L
        t = it["type"]
        if t=="long_call":   eq += qty*call_settle(K,P) - qty*call_price(L,K)
        elif t=="short_call":eq += qty*call_price(L,K) - qty*call_settle(K,P)
        elif t=="long_future":eq += qty*(P-L)/P
        elif t=="short_put": eq += qty*put_price(L,K) - qty*max(K-P,0)/P
    return eq

W_LEVELS = [60000,55000,50000,45000,40000,35000,30000]
W_SCEN   = [None,60000,55000,50000,45000,40000,35000,30000,25000,20000,15000]
def scen_name(X): return "never<60k" if X is None else "low%dk"%(X//1000)

if __name__ == "__main__":
    items = CFG["items"]
    print("usable=%.4f bal=%.4f ext=%.4f cover=%s perp_entry=%.2f fut_adj=%s"
          % (USABLE, BALANCE, EXTERNAL, COVER, FP_ENTRY, FUTURE_ADJ))
    # low50 curve
    print("\n--- low50 curve (X=50000) ---")
    xs = list(range(50000, 160001, 2000))
    ys = [(P, equity(P,50000,items)) for P in xs]
    peakP, peakV = max(ys, key=lambda t: t[1])
    print("peak at $%d = %.4f BTC" % (peakP, peakV))
    for P in [62000,70000,80000,86000,90000,98000,100000,110000,120000,140000]:
        print("  $%-7d eq=%.4f  min=%.3f" % (P, equity(P,50000,items), min_at(P)))
    # global checks (targets 3 & 4)
    print("\n--- target 3 (P>cur, all lines >= usable %.3f) & target 4 (P<cur >= min) ---" % USABLE)
    CUR = 61970
    XS = list(range(10000, 200001, 2000))
    worst3 = ("",1e9,0); worst4=("",1e9,0)
    for X in W_SCEN:
        floor = 60000 if X is None else X
        for P in XS:
            if P < floor: continue
            e = equity(P,X,items)
            if P > CUR and e-USABLE < worst3[1]: worst3=(scen_name(X),e-USABLE,P)
            if P < CUR and e-min_at(P) < worst4[1]: worst4=(scen_name(X),e-min_at(P),P)
    print("worst3 (eq-usable) %.3f @ $%d %s" % (worst3[1],worst3[2],worst3[0]))
    print("worst4 (eq-min)    %.3f @ $%d %s" % (worst4[1],worst4[2],worst4[0]))
