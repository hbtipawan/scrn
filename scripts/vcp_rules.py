"""VCP scanner, rule-based (Scanners -> VCP scanner): Mark Minervini's volatility contraction pattern, as written in
"Trade Like a Stock Market Wizard" (2013) and "Think & Trade Like a Champion" (2017), turned into exact rules and tested
on NSE daily data 2005-2026 (config/vcp_rules_evidence.json has the results and their limits).

A stock is listed when, on the last session:
  trend     the Trend Template: close > 50-day > 150-day > 200-day average, the 200-day average higher than 22 sessions
            ago, close at least 30% above the 52-week low and within 25% of the 52-week high;
            RS rating 70+ (the browser can ask for 80+ or 90+; 80+ is the default);
  base      the left-side high = the highest high of the last 250 sessions, at least 10 sessions back; the stock rose
            30%+ into it (from the lowest low of the 126 sessions before it);
  contractions  a zigzag inside the base: a pullback counts when price then rises 5%+ off its low, a new pullback starts
            when price falls 5%+ off a high. The contraction still forming at the right edge counts too. Needed:
            2 to 6 contractions, each shallower than the one before, the first at most 35% deep, the last at most 10%;
  optional  (browser) each contraction's low at or above the previous one's ("higher lows", default on) and volume of
            the last 5 sessions at most 0.8x its 50-day average ("dry-up", default on).
Status:
  setting up   the close is inside the last contraction (at or under its high, the pivot, and above its low);
  breakout     yesterday's base passed every rule, today closed above its pivot, at most 5% above it, on 1.4x+ the
               50-day average volume (O'Neil's 40-50% rule).
Most bases found are short (median 14 sessions): counting every 5% swing and asking each to be shallower than the last
is strict, and long bases rarely pass. Looser counting (7% swings, or swings confirmed by a close) found longer bases but a
much smaller edge (see "robust" in the evidence file).
Plan shown: buy above the pivot (up to 5% over it); stop 8% under the entry (tested better than the contraction low);
no fixed target (targets of 2R or +20% halved the result in testing).

The detector is the one used in the backtest (scratch numba code, ported line by line); compute.py calls build()."""
import numpy as np
import pandas as pd

ZZ = 0.05            # zigzag reversal
WMAX = 250           # longest base (sessions)
MAX_T = 6
D1_MAX, DK_MAX = 0.35, 0.10
ADV_MIN = 0.30
RS_MIN = 70
BO_VOL, BO_EXT = 1.4, 1.05


def _sma(a, n):
    return pd.Series(a).rolling(n, min_periods=n).mean().to_numpy()


def base_at(H, L, t):
    """the base ending at bar t: (s, adv, depths, troughs, points, pivot, low) or None. Same steps as the backtest."""
    a = max(0, t - WMAX + 1)
    seg = H[a:t + 1]
    if not np.isfinite(seg).any():
        return None
    s = a + int(np.nanargmax(seg))           # first bar of the highest high (np.argmax keeps the first, like the loop)
    hh = H[s]
    if t - s < 10:
        return None
    lo = np.nanmin(L[max(0, s - 126):s + 1])
    adv = hh / lo - 1.0
    dep, tro, pts = [], [], [(s, hh, "H")]
    P, mode, trough, ti, peak, pi = hh, 0, 1e18, s, hh, s
    for k in range(s + 1, t + 1):
        h, l = H[k], L[k]
        if h != h:
            continue
        if mode == 0:
            if l < trough:
                trough, ti = l, k
            if h >= trough * (1 + ZZ) and trough < 1e17:
                dep.append((P - trough) / P); tro.append(trough); pts.append((ti, trough, "L"))
                mode, peak, pi = 1, h, k
        else:
            if h > peak:
                peak, pi = h, k
            if l <= peak * (1 - ZZ):
                pts.append((pi, peak, "H"))
                P, mode, trough, ti = peak, 0, l, k
    if mode == 0:
        piv, low, li = P, trough, ti
    else:
        piv = peak
        w = L[pi:t + 1]
        li = pi + int(np.nanargmin(w)); low = L[li]
        pts.append((pi, peak, "H"))
    dep.append((piv - low) / piv); tro.append(low); pts.append((li, low, "L"))
    return s, adv, dep, tro, pts, piv, low


def check(dep, tro, adv):
    """the rules every listed base passes; returns (passes, shrinking ratio max, higher lows)"""
    k = len(dep)
    mx = max((dep[q] / dep[q - 1] if dep[q - 1] > 0 else 9.0) for q in range(1, k)) if k > 1 else 0.0
    hl = all(tro[q] >= tro[q - 1] * 0.999 for q in range(1, k))
    ok = (2 <= k <= MAX_T) and mx < 1.0 and dep[0] <= D1_MAX and dep[-1] <= DK_MAX and adv >= ADV_MIN
    return ok, mx, hl


def build(PFULL, symbols, rs_today, last, ev=None):
    """-> vcp2.json content for the liquid stocks of the last session. rs_today: Series symbol -> RS rating."""
    P = PFULL[PFULL.symbol.isin(set(symbols))].sort_values(["symbol", "date"])
    rows, scanned = [], 0
    for sym, g in P.groupby("symbol", sort=True):
        g = g.drop_duplicates("date")
        if len(g) < 260 or g["date"].iloc[-1] != last:
            continue
        rs = rs_today.get(sym)
        if rs is None or not np.isfinite(rs) or rs < RS_MIN:
            continue
        scanned += 1
        D = g["date"].to_numpy()
        H, L, C, V = (g[k].to_numpy(dtype=float) for k in ("high", "low", "close", "volume"))
        V = np.nan_to_num(V, nan=0.0)
        s50, s150, s200 = _sma(C, 50), _sma(C, 150), _sma(C, 200)
        v50 = pd.Series(V).rolling(50, min_periods=40).mean().to_numpy()
        hi52 = pd.Series(H).rolling(252, min_periods=200).max().to_numpy()
        lo52 = pd.Series(L).rolling(252, min_periods=200).min().to_numpy()
        n = len(C)

        def tt(t):
            return (t >= 22 and C[t] > s50[t] > s150[t] > s200[t] and s200[t] > s200[t - 22]
                    and C[t] >= 1.3 * lo52[t] and C[t] >= 0.75 * hi52[t])

        def feat(t):
            if not tt(t):
                return None
            b = base_at(H, L, t)
            if b is None:
                return None
            s, adv, dep, tro, pts, piv, low = b
            ok, mx, hl = check(dep, tro, adv)
            if not ok:
                return None
            vs = V[max(0, t - 4):t + 1]
            dry = float(vs.mean() / v50[t]) if v50[t] > 0 else 9.0
            return dict(s=s, adv=adv, dep=dep, tro=tro, pts=pts, piv=piv, low=low, hl=hl, dry=dry)

        t = n - 1
        st, f = None, None
        fy = feat(t - 1)                      # a breakout comes first: yesterday's base, cleared today
        vr0 = V[t] / v50[t - 1] if v50[t - 1] > 0 else 0.0
        if fy and fy["piv"] < C[t] <= fy["piv"] * BO_EXT and vr0 >= BO_VOL:
            st, f = "bo", fy
        else:
            f = feat(t)
            if f and low_ok(C[t], f):
                st = "setup"
        if not st:
            continue
        vr = V[t] / v50[t - 1] if v50[t - 1] > 0 else None
        r2 = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 2)
        rows.append({"s": sym, "st": st, "piv": r2(f["piv"]), "low": r2(f["low"]), "c": r2(C[t]),
                     "dist": r2((C[t] / f["piv"] - 1) * 100), "k": len(f["dep"]),
                     "dep": [round(d * 100, 1) for d in f["dep"]], "hl": bool(f["hl"]), "dry": r2(f["dry"]),
                     "vr": r2(vr), "adv": round(f["adv"] * 100), "blen": int(t - f["s"]), "rs": int(rs),
                     "pts": [[str(D[i]), r2(p), k] for i, p, k in f["pts"]]})
    rows.sort(key=lambda r: (r["st"] != "bo", -r["rs"]))
    # market check used in the test: the equal-weight average of these stocks against its 200-day average
    mkt = None
    try:
        W = P.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index().iloc[-300:]
        r = W.pct_change(fill_method=None).clip(-0.4, 0.4).mean(axis=1).fillna(0)
        ew = (1 + r).cumprod()
        m200 = ew.rolling(200).mean().iloc[-1]
        mkt = {"up": bool(ew.iloc[-1] > m200), "vs200": round(float((ew.iloc[-1] / m200 - 1) * 100), 1)}
    except Exception:
        pass
    return {"asof": last, "scanned": scanned, "rules": {"zz": ZZ, "wmax": WMAX, "max_t": MAX_T, "d1": D1_MAX, "dk": DK_MAX,
            "adv": ADV_MIN, "rs": RS_MIN, "bo_vol": BO_VOL, "bo_ext": BO_EXT}, "market": mkt, "rows": rows, "evidence": ev}


def low_ok(c, f):
    """setting up: the close inside the last contraction"""
    return f["low"] <= c <= f["piv"]
