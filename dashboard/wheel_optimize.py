"""Wheel buy-action optimiser.

The ONLY thing you choose is which equity line(s) to shape, e.g. low50.
Everything else (External BTC, Min-BTC curve, cover price, future adj, existing
actions...) is read live from wheel_config.json -- i.e. whatever you set on the
dashboard. The 5 targets are fixed logic:

  T1  the chosen line's plateau is as HIGH as possible (maximised; it need NOT be
      the price-axis peak -- the line may keep rising past --peak)
  T2  the chosen line is a flat plateau from --peak up to the cover price
  T3  EVERY line >= Usable BTC (ext+bal) for prices ABOVE $80k up to the cover price
      (below $80k only the Min-BTC floor applies, not usable)
  T4+T5  EVERY line >= the Min-BTC floor for ALL prices up to $200k

Usage:
  python wheel_optimize.py low50              # optimise, print report (dry run)
  python wheel_optimize.py low50 --save       # also save as a dashboard scenario
  python wheel_optimize.py low50,low55        # shape two lines
  python wheel_optimize.py low50 --peak 80000 --name "My scenario"

Equity is linear in the action quantities, so coefficients are precomputed once
and the search is fast. Results are re-verified against the real model.
"""
import argparse, json, os, copy, datetime
import numpy as np
from scipy.optimize import linprog
import wheel_model as W

HERE = W.HERE
STEP = 2000
PMAX = 200000
T3_LO = 80000     # T3 (>= usable) applies only to prices strictly ABOVE this, up to cover
MONO_LO = 80000   # MONO (deeper line >= shallower) applies from this price upward
GAP_LO = 80000    # GAP reference price; gap must not shrink for prices ABOVE this
HEIGHT_W = 1.0    # T1: reward for the shaped line's plateau height (maximise it)
REG_W = 0.001     # tiny pull toward zero -> uniquely pick the smallest position that
                  # reaches the max height (keeps the result well-defined / idempotent)
def _cover(): return W.COVER or 100000
def _cur():
    pos = W.D.get("open_positions") or []
    ip = (pos[0].get("index_price") if pos else None) or 62000
    return int(round(ip))

# ---------------- scenario-name parsing ----------------
def parse_scen(name):
    s = str(name).strip().lower().replace("low", "").replace("k", "").replace("<60", "").replace(" ", "")
    if s in ("never", ""): return None
    try: return int(float(s)) * 1000 if int(float(s)) < 1000 else int(float(s))
    except ValueError: raise SystemExit("unknown scenario: %s" % name)

def floor_of(X): return 60000 if X is None else X
_UNIV_LV = (40000, 45000, 50000, 55000, 60000)   # buy-action levels in the knob universe
def _frozen_line(X, lock):
    """A scenario line is frozen (no decision variable can move it) if no UNLOCKED
    universe level can affect it. An action at level L affects scenario X only when
    L >= X; the never<60k line (X=None) is never affected by any action."""
    if X is None: return True
    return not any(l not in lock for l in _UNIV_LV if l >= X)
def _grid(lo, hi=PMAX):
    """Price grid aligned to multiples of STEP (so peak=$80k / cover-$ are always
    sampled regardless of the scenario floor's parity), restricted to >= lo."""
    start = ((int(lo) + STEP - 1) // STEP) * STEP
    return list(range(start, hi + 1, STEP))
def line_label(X): return "NEVER" if X is None else "%dK" % (X // 1000)
def auto_name(shaped):
    return "%s-%s" % ("+".join(line_label(X) for X in shaped),
                      datetime.datetime.now().strftime("%y%m%d%H%M"))

# ---------------- per-unit (linear) contribution ----------------
def per_unit(t, L, K, P, X):
    if X is None or L < X: return 0.0
    K = K or L
    if t == "long_call":   return W.call_settle(K, P) - W.call_price(L, K)
    if t == "short_call":  return W.call_price(L, K) - W.call_settle(K, P)
    if t == "long_future": return (P - L) / P
    if t == "short_put":   return W.put_price(L, K) - max(K - P, 0) / P
    return 0.0

# ---------------- fixed knob universe (config-items-independent) ----------------
# The optimiser DESIGNS the buy actions from this fixed candidate set, starting from
# zero. It deliberately ignores whatever items are currently in the config so that
# "sim" is a pure function of (params + price table + positions): running it twice --
# even after the UI loads the previous result back in -- gives the SAME answer.
CAP = {"long_call": 8.0, "short_call": 8.0, "short_put": 5.0, "long_future": 5.0}
_LC = {60000: [60000, 100000, 120000, 140000],
       55000: [55000, 100000, 120000, 140000],
       50000: [50000, 86000, 90000, 94000, 100000, 120000, 140000],
       45000: [80000, 100000, 120000, 140000, 170000, 190000],
       40000: [40000, 100000, 120000, 140000]}
_SC = {60000: [80000, 100000],
       55000: [80000, 100000, 120000, 140000],
       50000: [80000, 100000, 120000, 140000],
       45000: [80000, 100000],
       40000: [80000, 100000]}
_SP = {50000: [55000, 60000], 45000: [50000], 40000: [45000]}
_LEVELS_LF = (60000, 55000, 50000, 45000, 40000)

def build_knobs(base_items=None):
    """Fixed universe -> (type, level, strike, base_qty=0, lo=0, hi=CAP). base_items
    is ignored on purpose (kept as an argument for call-site compatibility)."""
    knobs = []
    for L, strikes in _LC.items():
        for K in strikes: knobs.append(("long_call", L, K, 0.0, 0, CAP["long_call"]))
    for L, strikes in _SC.items():
        for K in strikes: knobs.append(("short_call", L, K, 0.0, 0, CAP["short_call"]))
    for L in _LEVELS_LF:
        knobs.append(("long_future", L, L, 0.0, 0, CAP["long_future"]))
    for L, strikes in _SP.items():
        for K in strikes: knobs.append(("short_put", L, K, 0.0, 0, CAP["short_put"]))
    return knobs

# ---------------- precompute linear model over needed points ----------------
class LinModel:
    def __init__(self, knobs, base_items):
        self.knobs = knobs
        self.base = np.array([k[3] for k in knobs])
        self.bounds = [(k[4], k[5]) for k in knobs]
        knob_keys = {(t, L, K) for (t, L, K, *_ ) in knobs}
        self.fixed = [it for it in base_items
                      if (it["type"], it["level"], it.get("strike") or it["level"]) not in knob_keys]
        self.idx = {}; self.C = []; self.M = []
    def point(self, P, X):
        key = (P, X)
        if key in self.idx: return self.idx[key]
        c = W.USABLE + W.existing_put_settle(P) + W.existing_deriv(P)
        for it in self.fixed:
            q = it.get("qty") or 0
            if q: c += q * per_unit(it["type"], it["level"], it.get("strike"), P, X)
        self.C.append(c)
        self.M.append([per_unit(t, L, K, P, X) for (t, L, K, *_ ) in self.knobs])
        self.idx[key] = len(self.C) - 1
        return self.idx[key]
    def finalize(self):
        self.C = np.array(self.C); self.M = np.array(self.M)
    def eq(self, v): return self.C + self.M @ v

# ---------------- core optimiser (callable from CLI or server) ----------------
def optimize(shaped, peak=80000, starts=24, seed=0, lock_levels=None):
    """Return an optimised items[] list for the given shaped scenario(s).
    Assumes W.configure() has already set the model state.
    lock_levels: levels whose buy actions are FROZEN to the current config (the
    optimiser keeps them as-is and only designs the other levels)."""
    COVER = _cover(); CUR = _cur()
    lock = set(lock_levels or [])
    base_items = copy.deepcopy(W.CFG["items"])
    knobs = [k for k in build_knobs() if k[1] not in lock]       # tunable: unlocked levels
    locked_items = [it for it in base_items if it["level"] in lock]   # frozen config actions
    LM = LinModel(knobs, locked_items)

    plat_hi = COVER - STEP
    shape_pts = []
    for X in shaped:
        plat_prices = sorted(set(range(peak, plat_hi + 1, STEP)) | {peak, plat_hi})
        ipk = LM.point(peak, X)
        iplat = [LM.point(P, X) for P in plat_prices]
        icurve = [LM.point(P, X) for P in sorted(set(_grid(floor_of(X))) | {peak, plat_hi})]
        shape_pts.append((ipk, iplat, icurve))
    t3 = [LM.point(P, X) for X in W.W_SCEN for P in range(T3_LO + STEP, COVER, STEP)
          if P >= floor_of(X)]
    t45 = [(LM.point(P, X), W.min_at(P)) for X in W.W_SCEN for P in _grid(floor_of(X))]
    # GAP condition: for every line, the gap above the current-level reference
    # (never<60k when current_level is null) must not SHRINK above $80k.
    # gap(X,P) = eq(X,P) - eq(ref,P);  require gap(X,P) >= gap(X,$80k) for P > $80k.
    cl = W.CFG.get("current_level")
    X_REF = None if cl is None else cl
    cmax = 60000 if cl is None else cl
    gap_pts = []
    for X in W.W_SCEN:
        if X == X_REF or floor_of(X) > cmax: continue
        i80, i80r = LM.point(GAP_LO, X), LM.point(GAP_LO, X_REF)
        for P in range(GAP_LO + STEP, PMAX + 1, STEP):
            gap_pts.append((LM.point(P, X), i80, LM.point(P, X_REF), i80r))
    # MONOTONIC condition: for P >= MONO_LO ($80k), a DEEPER line (dropped lower) must
    # return MORE than a shallower one. Lines for floor < $40k are identical (all actions
    # trigger), so we order the distinct ones: never < low60 < low55 < ... < low40.
    ORD = [X for X in (None, 60000, 55000, 50000, 45000, 40000) if floor_of(X) <= cmax]
    mono_pts = []
    for i in range(len(ORD) - 1):
        Xs, Xd = ORD[i], ORD[i + 1]                  # Xd deeper -> must be >= Xs
        for P in range(MONO_LO, PMAX + 1, STEP):
            mono_pts.append((LM.point(P, Xd), LM.point(P, Xs)))
    LM.finalize()
    t3 = np.array(t3, dtype=int)
    t45i = np.array([a for a, _ in t45], dtype=int); t45min = np.array([m for _, m in t45])
    USABLE = W.USABLE

    lo = np.array([b[0] for b in LM.bounds]); hi = np.array([b[1] for b in LM.bounds])
    M, C = LM.M, LM.C
    n = len(knobs); m = len(shaped); nv = n + m

    # ---- LINEAR PROGRAM ----------------------------------------------------
    # equity is linear in the knob qtys (eq = C + M v), so every target is a linear
    # inequality and "maximise the shaped line's plateau" is a linear objective.
    # We add a slack t_k per shaped line = its plateau FLOOR and maximise sum(t_k):
    #   maximise  sum_k t_k
    #   s.t.  eq(P, X_k) >= t_k            for every plateau price P in [$80k, cover)
    #         eq(cover-, X_k) >= eq($80k, X_k)        (plateau non-decreasing to cover)
    #         eq(P, X) >= usable           for every line, $80k < P < cover   (T3)
    #         eq(P, X) >= min_floor(P)     for every line, floor..$200k        (T4+T5)
    #         0 <= v <= cap
    # Small buffers keep it feasible after rounding to the 0.1 trade grid.
    # Buffers absorb the worst-case drift from rounding qtys to the 0.1 trade grid,
    # so the verified (rounded) result still clears every hard target.
    T3_BUF = 0.020; FLOOR_BUF = 0.030; COVER_BUF = 0.006
    rows = []; b_ub = []
    for k, (ipk, iplat, icurve) in enumerate(shape_pts):
        for r in iplat:                                   # plateau point >= t_k
            row = np.zeros(nv); row[:n] = -M[r]; row[n + k] = 1.0
            rows.append(row); b_ub.append(C[r])
        icv = iplat[-1]                                   # eq@cover- >= eq@$80k + buf
        row = np.zeros(nv); row[:n] = M[ipk] - M[icv]
        rows.append(row); b_ub.append(C[icv] - C[ipk] - COVER_BUF)
    for r in t3:                                          # T3: >= usable above $80k
        row = np.zeros(nv); row[:n] = -M[r]
        rows.append(row); b_ub.append(C[r] - (USABLE + T3_BUF))
    for r, mn in zip(t45i, t45min):                       # T4+T5: >= min floor
        row = np.zeros(nv); row[:n] = -M[r]
        rows.append(row); b_ub.append(C[r] - (mn + FLOOR_BUF))
    GAP_BUF = MONO_BUF = 0.005
    for iP, i98, iPr, i98r in gap_pts:                    # gap(P>=100k) >= gap(98k)
        coef = M[iP] - M[i98] - M[iPr] + M[i98r]
        cterm = C[iP] - C[i98] - C[iPr] + C[i98r]
        row = np.zeros(nv); row[:n] = -coef
        rows.append(row); b_ub.append(cterm - GAP_BUF)
    for iD, iS in mono_pts:                               # deeper line >= shallower (P>=100k)
        row = np.zeros(nv); row[:n] = -(M[iD] - M[iS])
        rows.append(row); b_ub.append(C[iD] - C[iS] - MONO_BUF)

    # Drop constraint rows that no decision variable can influence (all-zero on v):
    # these are fully determined by locked/existing positions, so the optimiser can't
    # act on them. Keeping them would make a locked level spuriously infeasible -- the
    # user explicitly froze that line and accepts it as-is.
    A = np.array(rows); b = np.array(b_ub)
    keep = np.any(np.abs(A) > 1e-9, axis=1)
    res = linprog(np.concatenate([np.zeros(n), -np.ones(m)]),
                  A_ub=A[keep], b_ub=b[keep],
                  bounds=[(0, h) for h in hi] + [(None, None)] * m, method="highs")
    if not res.success:
        raise RuntimeError("LP solve failed: " + (res.message or "infeasible"))
    vc = np.asarray(res.x[:n], dtype=float)

    # ---- snap to the 0.1 trade grid, then a tiny lattice polish ----
    # Polish objective mirrors the LP: maximise the plateau floor, hard-penalise any
    # T3 / floor / cover / gap violation (so rounding never breaks a constraint).
    gP = np.array([g[0] for g in gap_pts], dtype=int)
    g98 = np.array([g[1] for g in gap_pts], dtype=int)
    gPr = np.array([g[2] for g in gap_pts], dtype=int)
    g98r = np.array([g[3] for g in gap_pts], dtype=int)
    mD = np.array([p[0] for p in mono_pts], dtype=int)
    mS = np.array([p[1] for p in mono_pts], dtype=int)
    def ppen(v):
        y = LM.eq(v); val = 0.0
        for (ipk, iplat, icurve) in shape_pts:
            val -= float(np.min(y[iplat]))                       # maximise plateau floor
            val += max(0.0, y[ipk] - y[iplat[-1]]) * 50          # cover- >= $80k
        val += float(np.sum(np.clip(-(y[t3] - USABLE), 0, None))) * 300
        val += float(np.sum(np.clip(-(y[t45i] - t45min), 0, None))) * 300
        if len(gP):                                              # gap(P>=100k) >= gap(98k)
            val += float(np.sum(np.clip(-((y[gP] - y[g98]) - (y[gPr] - y[g98r])), 0, None))) * 300
        if len(mD):                                              # deeper line >= shallower
            val += float(np.sum(np.clip(-(y[mD] - y[mS]), 0, None))) * 300
        return val

    OPT_STEP = 0.1
    step = np.array([OPT_STEP if t in ("long_call", "short_call", "short_put") else 0.01
                     for (t, L, K, *_ ) in knobs])
    v = np.clip(np.round(vc / step) * step, lo, hi)
    improved = True
    while improved:
        improved = False
        cur = ppen(v)
        for i in range(len(v)):
            for d in (step[i], -step[i]):
                cand = v.copy()
                cand[i] = min(max(round((v[i] + d) / step[i]) * step[i], lo[i]), hi[i])
                if abs(cand[i] - v[i]) < 1e-12: continue
                p = ppen(cand)
                if p < cur - 1e-12:
                    v = cand; cur = p; improved = True
    v = np.round(v, 2)     # clean float dust (all values are 0.1 / 0.01 multiples)

    knob_q = {(t, L, K): float(q) for (t, L, K, *_ ), q in zip(knobs, v)}
    out = []
    for it in base_items:                          # locked levels: keep config actions verbatim
        if it["level"] in lock and (it.get("qty") or 0) > 1e-9:
            out.append(dict(it))
    for (t, L, K), q in knob_q.items():            # unlocked levels: optimised from the universe
        if q > 1e-9:
            out.append({"type": t, "level": L, "qty": q,
                        "strike": None if t == "long_future" else K})
    return out

# ---------------- verification against the REAL model ----------------
def verify(items, shaped, peak=80000, lock_levels=None):
    COVER = _cover(); CUR = _cur(); ok_all = True; lines = []
    lock = set(lock_levels or [])   # frozen lines are excluded from ok-gating below
    for X in shaped:
        xs = sorted(set(_grid(floor_of(X))) | {peak, COVER - STEP})
        y = {P: W.equity(P, X, items) for P in xs}
        plat = [y[P] for P in xs if peak <= P <= COVER - STEP]
        pk = max(xs, key=lambda P: y[P])
        # T1 is now an OBJECTIVE (maximise plateau height), not a pass/fail. We keep
        # this boolean only as info ("does $80k sit at the very top?"); it does NOT
        # gate ok -- the line is allowed to keep rising past $80k.
        t1 = y[peak] >= y[pk] - 0.003
        t2 = y[COVER - STEP] >= y[peak] - 1e-6
        ok_all &= t2
        lines.append({"line": W.scen_name(X), "t1": bool(t1), "t2": bool(t2),
                      "e_peak": round(y[peak], 4), "e_cover": round(y[COVER - STEP], 4),
                      "plat_lo": round(min(plat), 4), "plat_hi": round(max(plat), 4)})
    t3l = [(W.equity(P, X, items) - W.USABLE, W.scen_name(X), P)
           for X in W.W_SCEN if not _frozen_line(X, lock)
           for P in range(T3_LO + STEP, COVER, STEP) if P >= floor_of(X)]
    t3w = min(t3l) if t3l else (0.0, "", 0)
    t45l = [(W.equity(P, X, items) - W.min_at(P), W.scen_name(X), P)
            for X in W.W_SCEN if not _frozen_line(X, lock) for P in _grid(floor_of(X))]
    t45w = min(t45l) if t45l else (0.0, "", 0)
    # GAP: gap(X,P>$80k) >= gap(X,$80k), where gap = eq(X) - eq(reference line)
    cl = W.CFG.get("current_level"); X_REF = None if cl is None else cl
    cmax = 60000 if cl is None else cl
    gapw = (float("inf"), "", 0)
    for X in W.W_SCEN:
        if X == X_REF or floor_of(X) > cmax or _frozen_line(X, lock): continue
        g80 = W.equity(GAP_LO, X, items) - W.equity(GAP_LO, X_REF, items)
        for P in range(GAP_LO + STEP, PMAX + 1, STEP):
            d = (W.equity(P, X, items) - W.equity(P, X_REF, items)) - g80
            if d < gapw[0]: gapw = (d, W.scen_name(X), P)
    if gapw[0] == float("inf"): gapw = (0.0, "", 0)
    # MONO: deeper line >= shallower line for P >= MONO_LO (skip pairs both frozen)
    ORD = [X for X in (None, 60000, 55000, 50000, 45000, 40000) if floor_of(X) <= cmax]
    monow = (float("inf"), "", 0)
    for i in range(len(ORD) - 1):
        Xs, Xd = ORD[i], ORD[i + 1]
        if _frozen_line(Xs, lock) and _frozen_line(Xd, lock): continue
        for P in range(MONO_LO, PMAX + 1, STEP):
            d = W.equity(P, Xd, items) - W.equity(P, Xs, items)
            if d < monow[0]: monow = (d, "%s>=%s" % (W.scen_name(Xd), W.scen_name(Xs)), P)
    if monow[0] == float("inf"): monow = (0.0, "", 0)
    ok_all &= (t3w[0] >= -0.004 and t45w[0] >= -0.004
               and gapw[0] >= -0.004 and monow[0] >= -0.004)
    changes = []
    bk = {(it["type"], it["level"], it.get("strike") or it["level"]): it["qty"] for it in W.CFG["items"]}
    nk = {(it["type"], it["level"], it.get("strike") or it["level"]): it["qty"] for it in items}
    for k in sorted(set(bk) | set(nk), key=lambda k: (-k[1], k[0], k[2])):
        b = bk.get(k, 0); n = nk.get(k, 0)
        if abs(b - n) > 1e-9:
            tag = "new" if k not in bk else ("remove" if n == 0 else "adj")
            changes.append({"tag": tag, "type": k[0], "level": k[1], "strike": k[2],
                            "from": round(b, 2), "to": round(n, 2)})
    return {"ok": bool(ok_all), "peak": peak,
            "lines": lines,
            "t3_worst": round(t3w[0], 4), "t3_at": [t3w[1], t3w[2]],
            "t45_worst": round(t45w[0], 4), "t45_at": [t45w[1], t45w[2]],
            "gap_worst": round(gapw[0], 4), "gap_at": [gapw[1], gapw[2]],
            "mono_worst": round(monow[0], 4), "mono_at": [monow[1], monow[2]],
            "changes": changes}

def save_scenario(items, name, shaped):
    cfg = copy.deepcopy(W.CFG); cfg["items"] = items
    for fld in ("min_btc", "min_curve", "min_flat_price", "hidden_scenarios",
                "cover_price", "level_dates", "current_level"):
        cfg.pop(fld, None)
    snap = {"config": cfg, "price_table": W.PT, "data": W.D,
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "note": "Auto-optimised; shaped " + ",".join(W.scen_name(X) for X in shaped)}
    path = os.path.join(HERE, "wheel_snapshots.json")
    snaps = json.load(open(path)) if os.path.exists(path) else {}
    snaps[name] = snap
    json.dump(snaps, open(path, "w"), indent=2)
    return snap

def run_and_save(cfg, data, pt, lines, peak=80000, starts=20, name=None, lock_levels=None):
    """Server entry point: configure state, optimise, verify, save. Returns
    {name, verify}. `lines` is a list like ['low50'] or ['low50','low55'].
    lock_levels: levels to freeze (keep their current buy actions unchanged)."""
    W.configure(cfg, data, pt)
    shaped = [parse_scen(s) for s in lines]
    items = optimize(shaped, peak, starts, lock_levels=lock_levels)
    v = verify(items, shaped, peak, lock_levels=lock_levels)
    name = name or auto_name(shaped)
    save_scenario(items, name, shaped)
    return {"name": name, "verify": v}

# ---------------- CLI ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lines", nargs="?", default="low50",
                    help="which line(s) to shape, comma-separated, e.g. low50 or low50,low55")
    ap.add_argument("--peak", type=int, default=80000)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--name", default=None)
    ap.add_argument("--starts", type=int, default=80)
    ap.add_argument("--lock", default="", help="comma-separated levels to freeze, e.g. 60000,55000")
    args = ap.parse_args()
    shaped = [parse_scen(s) for s in args.lines.split(",")]
    lock_levels = [int(x) for x in args.lock.split(",") if x.strip()]
    print("params: usable=%.4f current=$%d cover=$%d shaping=%s peak=$%d lock=%s"
          % (W.USABLE, _cur(), _cover(), [W.scen_name(X) for X in shaped], args.peak, lock_levels))
    items = optimize(shaped, args.peak, args.starts, lock_levels=lock_levels)
    v = verify(items, shaped, args.peak, lock_levels=lock_levels)
    print("\n=== VERIFY (real model) ===")
    for L in v["lines"]:
        print("  [%s] T1:%s T2:%s  plateau %.4f-%.4f  e@peak=%.4f e@cover-=%.4f"
              % (L["line"], "OK" if L["t1"] else "X", "OK" if L["t2"] else "X",
                 L["plat_lo"], L["plat_hi"], L["e_peak"], L["e_cover"]))
    print("  T3 worst %+.4f (%s @$%d)" % (v["t3_worst"], *v["t3_at"]))
    print("  T4+T5 worst %+.4f (%s @$%d)" % (v["t45_worst"], *v["t45_at"]))
    print("  GAP worst %+.4f (%s @$%d)" % (v["gap_worst"], *v["gap_at"]))
    print("  MONO worst %+.4f (%s @$%d)" % (v["mono_worst"], *v["mono_at"]))
    print("  ALL TARGETS:", "PASS" if v["ok"] else "NOT FULLY MET")
    print("\nAction changes vs current config:")
    for c in v["changes"] or []:
        print("  [%-6s] %-11s L%-5d K%-7d : %.2f -> %.2f"
              % (c["tag"], c["type"], c["level"], c["strike"], c["from"], c["to"]))
    if not v["changes"]: print("  (no changes)")
    if args.save:
        nm = args.name or auto_name(shaped)
        save_scenario(items, nm, shaped)
        print('\n[saved] "%s"' % nm)

if __name__ == "__main__":
    main()
