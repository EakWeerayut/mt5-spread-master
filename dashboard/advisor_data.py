"""
Trading-Advisor data bundle.

Gathers EVERYTHING the trading-advisor agent needs into one deterministic JSON
bundle so the agent reasons on clean numbers instead of re-deriving them:

  META               spot, forward(s), timestamp, source (live/cached)
  STRATEGY_PLAN      wheel_config.json (items, levels, min curve, cover, dates)
  POSITIONS / ORDERS current Deribit positions + open orders (enriched)
  EQUITY_DIAGNOSTICS per-scenario worst (equity - min floor) + binding price
  SECURED_CHECK      put/call cover gaps (port of index.html renderSecuredChart)
  IV_SURFACE         per-expiry ATM IV, 25d skew (risk-reversal), term structure
  OPPORTUNITY_SCREEN richest / cheapest liquid strikes vs fitted smile + a
                     strategy-relevant edge table (the strikes the plan trades)

READ ONLY. No private trading endpoint is ever called.

Usage:
  python dashboard/advisor_data.py            # live fetch, write .advisor_bundle.json + md summary
  python dashboard/advisor_data.py --cached   # use on-disk caches (fast, offline-ish)
  python dashboard/advisor_data.py --out X.json
"""
import os
import sys
import json
import math
import argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import requests
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

import wheel
import wheel_model as WM
from option import _bs_price, _implied_vol, _bs_greeks, _parse_deribit_expiry

DATA_CACHE = os.path.join(HERE, ".data_cache.json")
PRICETABLE_CACHE = os.path.join(HERE, "wheel_pricetable.json")
DEFAULT_OUT = os.path.join(HERE, ".advisor_bundle.json")

# Liquidity / quality gates for the opportunity screen (skip dead + noisy strikes).
MIN_OI = 5.0            # BTC open interest
MAX_SPREAD_PCT = 25.0   # (ask-bid)/mark * 100
MIN_MARK_BTC = 0.003    # skip dust strikes (IV residual is meaningless there)
MIN_T = 0.02            # skip <~7-day expiries (gamma/expiry-day IV noise)
SCREEN_M_LO, SCREEN_M_HI = 0.80, 1.30   # screen near-the-money only (K/F)
# Smile is fitted only on the meaningful region so deep ITM/OTM wings (where a
# quadratic can't fit and IV is unstable) don't drag the curve.
FIT_M_LO, FIT_M_HI = 0.60, 1.70
MIN_T_FIT = 0.01
YEAR_DAYS = 365.0

# Strategy-relevant strikes the plan actually trades (for the edge table).
PLAN_PUT_EXPIRY = wheel.PUT_EXPIRY     # "25DEC26"
PLAN_CALL_EXPIRY = wheel.CALL_EXPIRY   # "26MAR27"
COVER_CALL_STRIKES = [80000, 100000, 120000, 140000]
PLATEAU_CALL_STRIKES = [86000, 90000, 94000]


# ----------------------------------------------------------------------------
# Fetch (live or cached)
# ----------------------------------------------------------------------------
def _fetch_chain_and_spot():
    chain = requests.get(
        "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
        params={"currency": "BTC", "kind": "option"}, timeout=30,
    ).json().get("result", [])
    spot = requests.get(
        "https://www.deribit.com/api/v2/public/get_index_price",
        params={"index_name": "btc_usd"}, timeout=10,
    ).json().get("result", {}).get("index_price", 0)
    return chain, spot


def gather_inputs(cached=False):
    """Return (data, chain, spot, price_table, source)."""
    if cached:
        with open(DATA_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)
        pt = wheel.load_price_table()
        spot = pt.get("spot") if pt else 0
        # cached chain isn't stored standalone; rebuild a thin chain is impossible
        # offline, so opportunity screen needs live. We still expose what we can.
        return data, [], spot, pt, "cached"

    from connectors.deribit import fetch
    data = fetch()
    data["_fetched_at"] = datetime.now().isoformat(timespec="seconds")
    chain, spot = _fetch_chain_and_spot()
    pt = wheel.compute_price_table(chain, spot)
    # persist so the dashboard and model stay in sync with what the advisor saw
    try:
        with open(DATA_CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f)
        wheel.save_price_table(pt)
    except Exception:
        pass
    return data, chain, spot, pt, "live"


# ----------------------------------------------------------------------------
# Option-chain enrichment + IV analytics
# ----------------------------------------------------------------------------
def _years_to_expiry(expiry_str):
    d = _parse_deribit_expiry(expiry_str)
    if not d:
        return None
    return max((d - datetime.now()).days / YEAR_DAYS, 1e-6)


def _iv_from_btc(price_btc, S, K, T, typ):
    if not price_btc or price_btc <= 0 or not S:
        return None
    iv = _implied_vol(price_btc * S, S, K, T, typ)
    return round(iv * 100, 2) if iv else None


def enrich_chain(chain):
    """Per-option: bid/ask/mark IV, delta, spread%, T, moneyness. Keeps raw too."""
    out = []
    for o in chain:
        info = wheel._parse(o.get("instrument_name", ""))
        if not info:
            continue
        K, typ, exp = info["strike"], info["type"], info["expiry"]
        S = o.get("underlying_price") or o.get("estimated_delivery_price") or 0
        T = _years_to_expiry(exp)
        if not S or not T:
            continue
        bid = o.get("bid_price") or 0
        ask = o.get("ask_price") or 0
        mark = o.get("mark_price") or 0
        mark_iv = o.get("mark_iv")
        spread_pct = round((ask - bid) / mark * 100, 1) if (mark and ask and bid) else None
        delta = (o.get("greeks") or {}).get("delta")
        if delta is None and mark_iv:
            delta = _bs_greeks(S, K, T, mark_iv / 100.0, typ).get("delta")
        out.append({
            "instrument": o["instrument_name"], "expiry": exp, "strike": K, "type": typ,
            "S": round(S, 2), "T": round(T, 5),
            "bid": bid, "ask": ask, "mark": mark,
            "mark_iv": mark_iv,
            "bid_iv": _iv_from_btc(bid, S, K, T, typ),
            "ask_iv": _iv_from_btc(ask, S, K, T, typ),
            "delta": round(delta, 4) if delta is not None else None,
            "spread_pct": spread_pct,
            "oi": o.get("open_interest") or 0,
            "vol": o.get("volume") or 0,
            "moneyness": round(K / S, 4),
        })
    return out


def fit_smiles(chain, spot):
    """Per (expiry, type) SMOOTHED IV smile: least-squares polynomial in
    log-moneyness ln(K/F), weighted by sqrt(open interest). Smoothing is the
    point — a fit that does NOT pass through every node lets us measure each
    strike's residual (mark_iv − fitted_iv) as a real richness signal.

    Returns {(expiry, type): {coeffs, F, T, n, kmin, kmax}}.
    """
    fwd_cache = {}
    groups = {}
    for o in chain:
        info = wheel._parse(o.get("instrument_name", ""))
        iv = o.get("mark_iv")
        if not info or not iv or iv <= 0:
            continue
        exp = info["expiry"]
        if exp not in fwd_cache:
            fwd_cache[exp] = wheel._forward_for(chain, exp) or spot
        F = fwd_cache[exp]
        if not F:
            continue
        m = info["strike"] / F
        if not (FIT_M_LO <= m <= FIT_M_HI):     # fit only the meaningful region
            continue
        groups.setdefault((exp, info["type"]), []).append(
            (info["strike"], iv, o.get("open_interest") or 0))
    fits = {}
    for (exp, typ), pts in groups.items():
        F = fwd_cache.get(exp) or spot
        T = _years_to_expiry(exp)
        if not F or not T or T < MIN_T_FIT or len(pts) < 5:
            continue
        xs = np.array([math.log(k / F) for k, _, _ in pts])
        ys = np.array([iv for _, iv, _ in pts])
        w = np.sqrt(np.array([oi for _, _, oi in pts]) + 1.0)
        deg = 2 if len(pts) >= 6 else 1
        try:
            coeffs = np.polyfit(xs, ys, deg, w=w)
        except Exception:
            continue
        ks = [k for k, _, _ in pts]
        fits[(exp, typ)] = {"coeffs": coeffs, "F": F, "T": T,
                            "n": len(pts), "kmin": min(ks), "kmax": max(ks)}
    return fits


def fitted_iv(fits, exp, K, typ):
    d = fits.get((exp, typ))
    if not d:
        return None
    return round(float(np.polyval(d["coeffs"], math.log(K / d["F"]))), 2)


def fitted_fair_btc(fits, exp, K, typ):
    d = fits.get((exp, typ))
    if not d:
        return None
    iv = fitted_iv(fits, exp, K, typ)
    if not iv or iv <= 0:
        return None
    return _bs_price(d["F"], K, d["T"], iv / 100.0, typ) / d["F"]


def _delta_of(F, K, T, sig, typ):
    if T <= 0 or sig <= 0:
        return None
    d1 = (math.log(F / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    from math import erf
    nd = 0.5 * (1 + erf(d1 / math.sqrt(2)))
    return nd if typ == "C" else nd - 1


def iv_surface(fits):
    """Per-expiry ATM IV (from fitted smile), 25-delta risk-reversal, term struct."""
    expiries = sorted({e for (e, _) in fits},
                      key=lambda e: _years_to_expiry(e) or 0)
    rows = []
    for exp in expiries:
        dC = fits.get((exp, "C"))
        dP = fits.get((exp, "P"))
        d = dC or dP
        F, T = d["F"], d["T"]
        atm_c = fitted_iv(fits, exp, F, "C") if dC else None
        atm_p = fitted_iv(fits, exp, F, "P") if dP else None
        atm = (atm_c + atm_p) / 2 if (atm_c and atm_p) else (atm_c or atm_p)
        rows.append({
            "expiry": exp, "T": round(T, 4), "fwd": round(F, 1),
            "atm_iv": round(atm, 2) if atm else None,
            "rr25": _risk_reversal_25(fits, exp, F, T),
        })
    return rows


def _risk_reversal_25(fits, exp, F, T):
    """25d call IV − 25d put IV from the fitted smile (skew sign; +call/-put)."""
    def iv_at_delta(typ, target):
        d = fits.get((exp, typ))
        if not d:
            return None
        best, bestd = None, 1e9
        K, step = d["kmin"], max((d["kmax"] - d["kmin"]) / 60.0, 500)
        while K <= d["kmax"]:
            sig = fitted_iv(fits, exp, K, typ)
            if sig and sig > 0:
                dl = _delta_of(F, K, T, sig / 100.0, typ)
                if dl is not None and abs(dl - target) < bestd:
                    bestd, best = abs(dl - target), sig
            K += step
        return best
    c = iv_at_delta("C", 0.25)
    p = iv_at_delta("P", -0.25)
    if c is None or p is None:
        return None
    return round(c - p, 2)


# ----------------------------------------------------------------------------
# Equity diagnostics (uses wheel_model, configured to live state)
# ----------------------------------------------------------------------------
def _cur_max_level(cfg):
    c = cfg.get("current_level")
    return 60000 if c is None else c


def _active_scenarios(cfg):
    m = _cur_max_level(cfg)
    return [X for X in WM.W_SCEN if (60000 if X is None else X) <= m]


def equity_diagnostics(cfg, ref_prices=(70000, 80000, 90000, 100000, 120000, 150000)):
    items = cfg["items"]
    usable = WM.USABLE
    xs = list(range(10000, 200001, 2000))
    lines = []
    global_worst = (None, 1e9, None)  # (scen, margin, price)
    for X in _active_scenarios(cfg):
        floor = 60000 if X is None else X
        worst_m, worst_p = 1e9, None
        for P in xs:
            if P < floor:
                continue
            e = WM.equity(P, X, items)
            m = e - WM.min_at(P)
            if m < worst_m:
                worst_m, worst_p = m, P
            if m < global_worst[1]:
                global_worst = (WM.scen_name(X), m, P)
        eq_ref = {str(P): round(WM.equity(P, X, items), 4)
                  for P in ref_prices if P >= floor}
        lines.append({
            "scenario": WM.scen_name(X),
            "worst_margin_vs_min": round(worst_m, 4),
            "binds_at": worst_p,
            "equity_at_ref": eq_ref,
        })
    return {
        "usable_btc": round(usable, 4),
        "balance_btc": round(WM.BALANCE, 4),
        "external_btc": round(WM.EXTERNAL, 4),
        "cover_price": WM.COVER,
        "future_notional_usd": WM.FP_NOTIONAL,
        "future_entry": round(WM.FP_ENTRY, 2) if WM.FP_ENTRY else 0,
        "future_adj_usd": WM.FUTURE_ADJ,
        "global_worst": {"scenario": global_worst[0],
                         "margin": round(global_worst[1], 4),
                         "price": global_worst[2]},
        "lines": lines,
    }


# ----------------------------------------------------------------------------
# Secured check (faithful port of index.html renderSecuredChart)
# ----------------------------------------------------------------------------
_WHEEL_CUTOFF = datetime(2026, 12, 25)


def _is_wheel_exp(exp):
    d = _parse_deribit_expiry(exp)
    return bool(d and d < _WHEEL_CUTOFF)


def _ord_amt(o):
    return max((o.get("amount") or 0) - (o.get("filled_amount") or 0), 0)


def _oblig_by_strike(data, typ):
    """sell = +, buy = -, split pos/ord. Only wheel-book expiries (< 25Dec26)."""
    m = {}

    def add(strike, key, qty):
        m.setdefault(strike, {"pos": 0.0, "ord": 0.0})[key] += qty
    for p in data.get("open_positions", []):
        i = wheel._parse(p.get("instrument", ""))
        if i and i["type"] == typ and _is_wheel_exp(i["expiry"]):
            add(i["strike"], "pos", (1 if p["direction"] == "sell" else -1) * abs(p.get("size") or 0))
    for o in data.get("open_orders", []):
        i = wheel._parse(o.get("instrument", ""))
        if i and i["type"] == typ and _is_wheel_exp(i["expiry"]):
            add(i["strike"], "ord", (1 if o["direction"] == "sell" else -1) * _ord_amt(o))
    return m


def secured_check(cfg, data):
    # ---- Puts: short-put obligations vs planned long_call + long_future cover ----
    put_by_strike = _oblig_by_strike(data, "P")
    plan_by_level = {}
    for it in cfg.get("items", []):
        if it.get("qty") and it["type"] in ("long_call", "long_future"):
            plan_by_level[it["level"]] = plan_by_level.get(it["level"], 0) + it["qty"]
    put_points = sorted(set(list(put_by_strike) + list(plan_by_level)))
    put_carry, put_over, put_worst = 0.0, 0, 0.0
    put_rows = []
    for K in sorted(put_points, reverse=True):
        plan = plan_by_level.get(K, 0)
        frame = plan + put_carry
        pb = put_by_strike.get(K, {"pos": 0, "ord": 0})
        oblig = pb["pos"] + pb["ord"]
        gap = frame - oblig
        if gap < -1e-9:
            put_over += 1
            put_worst = max(put_worst, -gap)
        put_carry = gap
        put_rows.append({"strike": K, "pos": round(pb["pos"], 3),
                         "ord": round(pb["ord"], 3), "oblig": round(oblig, 3),
                         "gap": round(gap, 3)})

    # ---- Calls: short-call obligations vs strategy base gap (>100k) ----
    X = cfg.get("current_level")
    floor = 60000 if X is None else X
    base_gap = 1e9
    for P in range(100000, 200001, 2000):
        if P < floor:
            continue
        g = WM.equity(P, X, cfg["items"]) - WM.min_at(P)
        base_gap = min(base_gap, g)
    if base_gap == 1e9:
        base_gap = 0.0
    call_by_strike = _oblig_by_strike(data, "C")
    call_points = sorted(call_by_strike)
    call_carry, call_over, call_worst = 0.0, 0, 0.0
    call_rows = []
    for idx, K in enumerate(call_points):
        plan = base_gap if idx == 0 else 0
        frame = plan + call_carry
        pb = call_by_strike.get(K, {"pos": 0, "ord": 0})
        oblig = pb["pos"] + pb["ord"]
        gap = frame - oblig
        if gap < -1e-9:
            call_over += 1
            call_worst = max(call_worst, -gap)
        call_carry = gap
        call_rows.append({"strike": K, "pos": round(pb["pos"], 3),
                          "ord": round(pb["ord"], 3), "oblig": round(oblig, 3),
                          "gap": round(gap, 3)})

    return {
        "put_verdict": "secured" if put_over == 0 else "over",
        "put_strikes_over": put_over, "put_worst_gap": round(put_worst, 3),
        "put_rows": put_rows,
        "strategy_base_gap_over_100k": round(base_gap, 4),
        "call_verdict": "secured" if call_over == 0 else "over",
        "call_strikes_over": call_over, "call_worst_gap": round(call_worst, 3),
        "call_rows": call_rows,
    }


# ----------------------------------------------------------------------------
# Opportunity screen (mispricing vs fitted smile + strategy edge table)
# ----------------------------------------------------------------------------
def _liquid(e):
    """Liquid AND meaningful: OI, spread, near-the-money, non-dust, not expiring, strictly OTM."""
    is_otm = (e["type"] == "C" and e["moneyness"] >= 1.0) or (e["type"] == "P" and e["moneyness"] <= 1.0)
    return ((e["oi"] or 0) >= MIN_OI
            and (e["spread_pct"] is None or e["spread_pct"] <= MAX_SPREAD_PCT)
            and (e["mark"] or 0) >= MIN_MARK_BTC
            and (e["T"] or 0) >= MIN_T
            and SCREEN_M_LO <= e["moneyness"] <= SCREEN_M_HI
            and is_otm)


def opportunity_screen(enriched, fits, spot, top=12):
    scored = []
    for e in enriched:
        if e["mark_iv"] is None or not _liquid(e):
            continue
        sm_iv = fitted_iv(fits, e["expiry"], e["strike"], e["type"])
        if sm_iv is None:
            continue
        rich = round(e["mark_iv"] - sm_iv, 2)   # +rich (sell), -cheap (buy)
        fair = fitted_fair_btc(fits, e["expiry"], e["strike"], e["type"])
        sell_edge = round((e["bid"] or 0) - fair, 5) if fair else None  # sell at bid vs fair
        buy_edge = round(fair - (e["ask"] or 0), 5) if fair else None   # buy at ask vs fair
        scored.append({**{k: e[k] for k in ("instrument", "expiry", "strike", "type",
                                            "bid", "ask", "mark", "mark_iv", "delta",
                                            "spread_pct", "oi", "vol")},
                       "smile_iv": sm_iv, "rich_ivpts": rich,
                       "sell_edge_btc": sell_edge, "buy_edge_btc": buy_edge})
    rich_sorted = sorted(scored, key=lambda r: r["rich_ivpts"], reverse=True)
    return {
        "note": "rich_ivpts = mark_iv - fitted_smile_iv. + = expensive (sell side), - = cheap (buy side). "
                "Liquidity filtered: OI>=%.0f, spread<=%.0f%%." % (MIN_OI, MAX_SPREAD_PCT),
        "richest_sell_candidates": rich_sorted[:top],
        "cheapest_buy_candidates": rich_sorted[-top:][::-1],
    }


def strategy_edge_table(enriched, fits):
    """Bid/ask + edge for the exact strikes/expiries the plan trades."""
    idx = {(e["expiry"], e["strike"], e["type"]): e for e in enriched}
    rows = []

    def add(exp, K, typ, role):
        e = idx.get((exp, K, typ))
        if not e:
            rows.append({"role": role, "expiry": exp, "strike": K, "type": typ,
                         "available": False})
            return
        sm_iv = fitted_iv(fits, exp, K, typ)
        fair = fitted_fair_btc(fits, exp, K, typ)
        rows.append({
            "role": role, "expiry": exp, "strike": K, "type": typ, "available": True,
            "bid": e["bid"], "ask": e["ask"], "mark": e["mark"],
            "mark_iv": e["mark_iv"], "smile_iv": sm_iv,
            "rich_ivpts": round(e["mark_iv"] - sm_iv, 2) if (e["mark_iv"] and sm_iv) else None,
            "sell_premium_btc_at_bid": e["bid"], "buy_cost_btc_at_ask": e["ask"],
            "delta": e["delta"], "oi": e["oi"], "spread_pct": e["spread_pct"],
        })
    # Covered / plateau calls (26MAR27)
    for K in COVER_CALL_STRIKES:
        add(PLAN_CALL_EXPIRY, K, "C", "covered_call")
    for K in PLATEAU_CALL_STRIKES:
        add(PLAN_CALL_EXPIRY, K, "C", "plateau_call")
    # Ladder short puts (25DEC26) around the action levels
    for K in range(35000, 70001, 5000):
        add(PLAN_PUT_EXPIRY, K, "P", "ladder_put")
    return rows


# ----------------------------------------------------------------------------
# Assemble + emit
# ----------------------------------------------------------------------------
def position_view(data):
    pos = []
    for p in data.get("open_positions", []):
        info = wheel._parse(p.get("instrument", ""))
        pos.append({
            "instrument": p.get("instrument"), "direction": p.get("direction"),
            "size": p.get("size"), "avg_price": p.get("average_price"),
            "mark_price": p.get("mark_price"), "index_price": p.get("index_price"),
            "delta": p.get("delta"), "floating_pnl": p.get("floating_pnl"),
            "kind": "option" if info else "future",
            "expiry": info["expiry"] if info else None,
            "strike": info["strike"] if info else None,
            "type": info["type"] if info else None,
            "book": ("wheel" if info and _is_wheel_exp(info["expiry"])
                     else "strategy" if info else "future"),
        })
    orders = []
    for o in data.get("open_orders", []):
        info = wheel._parse(o.get("instrument", ""))
        orders.append({
            "instrument": o.get("instrument"), "direction": o.get("direction"),
            "order_type": o.get("order_type"), "price": o.get("price"),
            "amount": o.get("amount"), "filled": o.get("filled_amount"),
            "remaining": _ord_amt(o), "status": o.get("status"),
            "book": ("wheel" if info and _is_wheel_exp(info["expiry"])
                     else "strategy" if info else "future"),
        })
    return pos, orders


def build_bundle(cached=False):
    data, chain, spot, pt, source = gather_inputs(cached=cached)
    cfg = wheel.load_config()
    WM.configure(cfg, data, pt)

    enriched = enrich_chain(chain) if chain else []
    fits = fit_smiles(chain, spot) if chain else {}
    pos, orders = position_view(data)

    btc_summary = {}
    for s in data.get("account_summaries", []):
        if s.get("currency") == "BTC":
            btc_summary = s
            break

    bundle = {
        "META": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "spot": round(spot, 2) if spot else None,
            "fwd_call": pt.get("fwd_call") if pt else None,
            "fwd_put": pt.get("fwd_put") if pt else None,
            "call_expiry": PLAN_CALL_EXPIRY, "put_expiry": PLAN_PUT_EXPIRY,
            "n_chain": len(enriched),
            "deribit_fetched_at": data.get("_fetched_at"),
            "asset": btc_summary.get("asset"),
            "asset_adj": btc_summary.get("asset_adj"),
            "total_funding_fee": btc_summary.get("total_funding_fee"),
        },
        "STRATEGY_PLAN": cfg,
        "POSITIONS": pos,
        "ORDERS": orders,
        "EQUITY_DIAGNOSTICS": equity_diagnostics(cfg),
        "SECURED_CHECK": secured_check(cfg, data),
        "IV_SURFACE": iv_surface(fits) if fits else [],
        "OPPORTUNITY_SCREEN": opportunity_screen(enriched, fits, spot) if enriched else {},
        "STRATEGY_EDGE_TABLE": strategy_edge_table(enriched, fits) if enriched else [],
    }
    return bundle


def md_summary(b):
    m = b["META"]
    eq = b["EQUITY_DIAGNOSTICS"]
    sc = b["SECURED_CHECK"]
    out = []
    out.append(f"# Advisor bundle ({m['source']}) @ {m['generated_at']}")
    out.append(f"Spot ${m['spot']:,} | fwd_call {m['fwd_call']} fwd_put {m['fwd_put']} | "
               f"chain {m['n_chain']} opts")
    if m.get("asset") is not None:
        out.append(f"Asset: {m['asset']:.4f} BTC | Asset Adj: {m['asset_adj']:.4f} BTC | Funding: {m['total_funding_fee']:.6f} BTC")
    out.append("")
    out.append(f"## Equity  usable={eq['usable_btc']} BTC  cover=${eq['cover_price']}")
    gw = eq["global_worst"]
    out.append(f"Global worst margin vs min: {gw['margin']} BTC @ ${gw['price']} ({gw['scenario']})")
    for ln in eq["lines"]:
        out.append(f"  {ln['scenario']:>10}: worst {ln['worst_margin_vs_min']:+.3f} @ ${ln['binds_at']}")
    out.append("")
    out.append("## Secured check")
    out.append(f"  PUT : {sc['put_verdict']} (over {sc['put_strikes_over']}, worst {sc['put_worst_gap']})")
    out.append(f"  CALL: {sc['call_verdict']} (over {sc['call_strikes_over']}, worst {sc['call_worst_gap']}), "
               f"base_gap>100k={sc['strategy_base_gap_over_100k']}")
    out.append("")
    if b["IV_SURFACE"]:
        out.append("## IV surface (ATM / 25d risk-reversal)")
        for r in b["IV_SURFACE"][:14]:
            out.append(f"  {r['expiry']:>9} T={r['T']:.3f} ATM {r['atm_iv']}  RR25 {r['rr25']}")
        out.append("")
    op = b.get("OPPORTUNITY_SCREEN") or {}
    if op:
        out.append("## Richest (sell) / cheapest (buy) vs smile")
        for r in op.get("richest_sell_candidates", [])[:6]:
            out.append(f"  SELL {r['instrument']:<24} rich {r['rich_ivpts']:+.1f}iv  bid {r['bid']}  oi {r['oi']}")
        for r in op.get("cheapest_buy_candidates", [])[:6]:
            out.append(f"  BUY  {r['instrument']:<24} cheap {r['rich_ivpts']:+.1f}iv  ask {r['ask']}  oi {r['oi']}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", action="store_true", help="use on-disk caches (no live fetch)")
    ap.add_argument("--refresh", action="store_true", help="(default) live fetch from Deribit")
    ap.add_argument("--out", default=DEFAULT_OUT, help="JSON output path")
    ap.add_argument("--json", action="store_true", help="print full JSON to stdout instead of md")
    args = ap.parse_args()

    bundle = build_bundle(cached=args.cached)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)

    if args.json:
        print(json.dumps(bundle, indent=2))
    else:
        print(md_summary(bundle))
        print(f"\n[written] {args.out}")


if __name__ == "__main__":
    main()
