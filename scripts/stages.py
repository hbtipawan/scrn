"""Weinstein stage (1 base, 2 advance, 3 top, 4 decline) for every stock, from WEEKLY bars.

Stan Weinstein reads a weekly chart against its 30-week moving average; this module does the same and keeps a memory
of the stage a stock is in, so that a flat average after a decline is a base (Stage 1) and a flat average after an
advance is a top (Stage 3). (The site's earlier rule looked only at today's close against the 150-day average and
its 20-day slope; it could not tell a base from a top and flipped between stages many times a year.)

Weekly bars: Monday-Friday weeks, dated by the week's last session; the current, unfinished week is the latest bar,
as on a live weekly chart. A week's close is the last traded price (a stock that has not traded for 25 sessions has
no close; after such a gap, e.g. a suspension, the stage is read afresh once 30 weeks of prices are back).
MA = 30-week simple average of weekly closes. The line is RISING when it is more than 1.5% above its value 6 weeks
earlier, FALLING when more than 1.5% below, otherwise FLAT. Price is ABOVE the line when the weekly close is more
than 2% over it, BELOW when more than 2% under it. A stage's RANGE is the highest weekly high and lowest weekly low
since the stage began.

  1 -> 2  close above the line, the line not falling, close above the base's high, and the base at least 6 weeks old
  1 -> 4  close below a falling line and below the base's low
  2 -> 1  a failed breakout: back below the line before the line ever turned up -> the same base continues
  2 -> 3  after the line has risen: the line stops rising and price closes under it, or the line stays flat 4 weeks;
          or two weekly closes in a row more than 5% under the line even while it still rises (a sharp break)
  2 -> 4  close below a falling line
  3 -> 2  close above a rising line and above the top's high, or above a rising line 4 weeks in a row
  3 -> 4  close below the line and below the top's low, or below a falling line 2 weeks in a row
  4 -> 3  a failed breakdown: back above the line before it ever turned down -> the same top continues
  4 -> 1  after the line has fallen: it stops falling and price is back at it 2 weeks in a row, or flat 4 weeks;
          or two weekly closes in a row more than 8% over the line even while it still falls
  4 -> 2  close above a rising line and above the highest high since the decline began (a V-turn)
  first reading: above a rising line 2, below a falling line 4, otherwise 3 if higher than a year earlier, else 1

Group indices (group_index.py) use the same machine with one more way out of a base (PG below): 1 -> 2 also after two
weekly closes in a row above a rising line, before the base's high is cleared. Groups turn earlier than single
stocks: on 20 years of NSE group indices the weeks a group spent above a rising line while still under its base's
high did better than the rest of its Stage 2 (for single stocks the opposite was true, so stocks keep the rule).

Tested on NSE 2006-2026 against the earlier rule (config/stage_evidence.json, shown on the website): see README.
Called from compute.py; if it fails the daily run falls back to the earlier rule."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from numba import njit
except ImportError:                                   # works without numba, just slower
    def njit(*a, **k):
        return (lambda f: f) if not (len(a) == 1 and callable(a[0])) else a[0]

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"
P = dict(ma=30, slope_w=6, s_up=0.015, s_dn=0.015, band=0.02, f23=4, f41=4, cross=0.02, min_base=6, p41=2, r32=4, init_lb=52,
         b23=2, d23=0.05, b41=2, d41=0.08, r12=0)
PG = dict(P, r12=2)                                   # group indices (see above)
NEW_DAYS, LATE_DAYS = 40, 250                         # zones of a Stage 2 run, from the 20-year test (see the evidence)


@njit(cache=True)
def machine(WC, WH, WL, MA, SL, s_up, s_dn, band, f23, f41, cross, min_base, p41, r32, init_lb, b23, d23, b41, d41, r12):
    """Runs the stage machine over every week; returns, for the last week of each stock: stage, the week it began,
    the stage before it, how a Stage 2 began (1 base breakout, 3 resumed from a top, 4 V-turn, 5 four weeks above a
    rising line, 6 two weekly closes above a rising line out of a base (groups), 0 first reading), the level that a
    Stage 2 broke (or a Stage 1 base's high), the base / top length in weeks before the breakout (or the base's age
    for Stage 1), the base's low (Stage 1), and the stage at the end of every week (rows = weeks)."""
    T, N = WC.shape
    hist = np.zeros((T, N), np.int8)
    out_st = np.zeros(N, np.int8); out_t0 = np.full(N, -1, np.int64); out_prev = np.zeros(N, np.int8)
    out_how = np.zeros(N, np.int8); out_lvl = np.full(N, np.nan); out_bw = np.full(N, -1, np.int64); out_lo = np.full(N, np.nan)
    for j in range(N):
        cur = 0; t0 = -1; rhi = np.nan; rlo = np.nan; below_dn = 0; nflat = 0; seen = False; ok41 = 0; ok32 = 0; nbel = 0; nabv = 0
        ok12 = 0; pst = 0; pt0 = -1; prhi = np.nan; prlo = np.nan
        prev = 0; how = 0; lvl = np.nan; bw = -1
        for t in range(T):
            c = WC[t, j]; m = MA[t, j]; s = SL[t, j]
            if not np.isfinite(c):
                if cur != 0:                          # no trade for 5+ weeks (suspended): read the stage afresh later
                    cur = 0; t0 = -1; rhi = np.nan; rlo = np.nan; below_dn = 0; nflat = 0; seen = False; ok41 = 0; ok32 = 0; nbel = 0; nabv = 0
                    ok12 = 0; pst = 0; pt0 = -1; prhi = np.nan; prlo = np.nan; prev = 0; how = 0; lvl = np.nan; bw = -1
                continue
            if not (np.isfinite(m) and np.isfinite(s)):
                hist[t, j] = cur
                continue
            up = s > s_up; dn = s < -s_dn
            above = c > m * (1 + band); below = c < m * (1 - band)
            hi_ref = WH[t, j] if np.isfinite(WH[t, j]) else c
            lo_ref = WL[t, j] if np.isfinite(WL[t, j]) else c
            new = cur; revert = False; nhow = 0
            if cur == 0:
                past = WC[max(0, t - init_lb), j]
                if above and up:
                    new = 2
                elif below and dn:
                    new = 4
                elif np.isfinite(past) and c >= past:
                    new = 3
                else:
                    new = 1
            elif cur == 1:
                if above and up:
                    ok12 += 1
                else:
                    ok12 = 0
                if above and (not dn) and c > rhi and (t - t0) >= min_base:
                    new = 2; nhow = 1
                elif below and dn and c < rlo:
                    new = 4
                elif r12 > 0 and ok12 >= r12:
                    new = 2; nhow = 6                             # groups: two weekly closes above a rising line
            elif cur == 2:
                if up:
                    seen = True; nflat = 0
                elif seen:
                    nflat += 1
                if c < m * (1 - d23):
                    nbel += 1
                else:
                    nbel = 0
                if below and dn:
                    new = 4
                elif (not seen) and below and pst == 1:
                    new = 1; revert = True
                elif seen and (not up) and c < m * (1 - cross):
                    new = 3
                elif f23 > 0 and seen and nflat >= f23:
                    new = 3
                elif b23 > 0 and nbel >= b23:
                    new = 3                                   # well under a line that still rises: a sharp break
            elif cur == 3:
                if below and c < rlo:
                    new = 4
                elif below and dn:
                    below_dn += 1
                    if below_dn >= 2:
                        new = 4
                elif above and up and c > rhi:
                    new = 2; nhow = 3
                if above and up:
                    ok32 += 1
                else:
                    ok32 = 0
                if new == 3 and r32 > 0 and ok32 >= r32:
                    new = 2; nhow = 5
                if not (below and dn):
                    below_dn = 0
            elif cur == 4:
                if c > m * (1 + d41):
                    nabv += 1
                else:
                    nabv = 0
                if dn:
                    seen = True; nflat = 0
                elif seen:
                    nflat += 1
                if not (seen and (not dn) and c >= m * (1 - band)):
                    ok41 = 0
                if above and up and c > rhi:
                    new = 2; nhow = 4
                elif (not seen) and above and pst == 3:
                    new = 3; revert = True
                elif seen and (not dn) and c >= m * (1 - band):
                    ok41 += 1
                    if ok41 >= p41:
                        new = 1
                elif f41 > 0 and seen and nflat >= f41:
                    new = 1
                elif b41 > 0 and seen and nabv >= b41:
                    new = 1                                   # well over a line that still falls: a base begins
            if new != cur:
                if revert:
                    hi2 = rhi if rhi > prhi else prhi
                    lo2 = rlo if rlo < prlo else prlo
                    cur = new; t0 = pt0; rhi = hi2 if hi_ref <= hi2 else hi_ref; rlo = lo2 if lo_ref >= lo2 else lo_ref
                    pst = 0; how = 0; lvl = np.nan; bw = -1
                    prev = 2 if new == 1 else 4
                else:
                    if new == 2:
                        how = nhow; lvl = rhi if nhow != 5 and nhow != 6 else np.nan; bw = t - t0 if cur != 0 else -1
                    prev = cur
                    pst = cur; pt0 = t0; prhi = rhi; prlo = rlo
                    cur = new; t0 = t; rhi = hi_ref; rlo = lo_ref
                below_dn = 0; nflat = 0; seen = False; ok41 = 0; ok32 = 0; nbel = 0; nabv = 0; ok12 = 0
            else:
                if hi_ref > rhi or not np.isfinite(rhi):
                    rhi = hi_ref
                if lo_ref < rlo or not np.isfinite(rlo):
                    rlo = lo_ref
            hist[t, j] = cur
        out_st[j] = cur; out_t0[j] = t0; out_prev[j] = prev
        if cur == 2:
            out_how[j] = how; out_lvl[j] = lvl; out_bw[j] = bw
        elif cur == 1:
            out_lvl[j] = rhi; out_lo[j] = rlo; out_bw[j] = T - 1 - t0
    return out_st, out_t0, out_prev, out_how, out_lvl, out_bw, out_lo, hist


def _sma(x, n):
    return pd.DataFrame(x).rolling(n, min_periods=n).mean().to_numpy()


def _run(WC, WH, WL, MA, SL, prm):
    return machine(WC, WH, WL, MA, SL, prm["s_up"], prm["s_dn"], prm["band"], prm["f23"], prm["f41"], prm["cross"], prm["min_base"],
                   prm["p41"], prm["r32"], prm["init_lb"], prm["b23"], prm["d23"], prm["b41"], prm["d41"], prm["r12"])


def stage_table(close, high, low, cal, prm=PG):
    """Stages of many daily price series at once (group indices). close / high / low: arrays (sessions x series) on
    the calendar `cal`, NaN before a series starts. Returns per series the stage now (0 = not enough history), the
    sessions since it began, the session index it began, how a Stage 2 began, whether the count is a minimum, and the
    weekly history: `hist` (weeks x series, the stage at the end of each week; the last row is this week so far) with
    `ends` (the session index that closes each week)."""
    close = np.asarray(close, dtype=float)
    dt = pd.to_datetime(pd.Series(list(cal)))
    wk = (dt - pd.to_timedelta(dt.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d").to_numpy()
    starts = np.flatnonzero(np.r_[True, wk[1:] != wk[:-1]])
    ends = np.r_[starts[1:] - 1, len(cal) - 1]
    WC = pd.DataFrame(close).ffill().to_numpy()[ends]
    hi = np.where(np.isfinite(high), high, -np.inf)
    lo_ = np.where(np.isfinite(low), low, np.inf)
    WH = np.maximum.reduceat(hi, starts, axis=0)
    WL = np.minimum.reduceat(lo_, starts, axis=0)
    WH[~np.isfinite(WH)] = np.nan
    WL[~np.isfinite(WL)] = np.nan
    MA = _sma(WC, prm["ma"])
    SL = np.full_like(MA, np.nan)
    SL[prm["slope_w"]:] = MA[prm["slope_w"]:] / MA[:-prm["slope_w"]] - 1
    st, t0, prev, how, lvl, bw, lo, hist = _run(WC, WH, WL, MA, SL, prm)
    nsess = len(cal) - 1
    d0 = np.full(close.shape[1], -1, np.int64)
    for j in range(close.shape[1]):
        if st[j] == 0 or t0[j] < 0:
            continue
        a, b = int(starts[t0[j]]), int(ends[t0[j]])
        d0[j] = b
        if st[j] == 2 and np.isfinite(lvl[j]):                      # the session that crossed the level
            hit = np.flatnonzero(close[a:b + 1, j] > lvl[j])
            if len(hit):
                d0[j] = a + int(hit[0])
    days = np.where(d0 >= 0, nsess - d0, -1)
    return {"st": st, "days": days, "d0": d0, "how": how, "cap": (prev == 0) & (st > 0), "hist": hist, "ends": ends}


def _r(v, nd=1):
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


def build(PFULL, symbols, bench, last):
    """Stage of every stock in `symbols` as of `last`, plus the details the RS tab's Stage 2 view shows."""
    import time
    t_0 = time.time()
    p = PFULL[PFULL.date <= last]
    cal = sorted(p.loc[p.symbol == bench, "date"].unique())
    if not cal or cal[-1] != last:
        raise ValueError(f"benchmark calendar does not end on {last}")
    want = sorted(set(symbols) | {bench})
    q = p[p.symbol.isin(set(want))]
    wide = {f: q.pivot_table(index="date", columns="symbol", values=f, aggfunc="last").reindex(index=cal, columns=want)
            for f in ("close", "high", "low", "volume")}
    raw = wide["close"]
    C = raw.ffill(limit=3).to_numpy(dtype=float)                     # daily closes as compute.py uses them
    # a week's close is the last traded price, if the stock traded in the last 25 sessions (thinly traded stocks
    # skip days; a longer gap is a suspension and the stage is read afresh after it)
    seen_at = pd.DataFrame(np.where(raw.notna().to_numpy(), np.arange(len(cal))[:, None], np.nan)).ffill().to_numpy()
    CW = np.where(np.arange(len(cal))[:, None] - seen_at <= 25, raw.ffill().to_numpy(dtype=float), np.nan)
    H, L, V = (wide[f].to_numpy(dtype=float) for f in ("high", "low", "volume"))
    dt = pd.to_datetime(pd.Series(cal))
    wk = (dt - pd.to_timedelta(dt.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d").to_numpy()
    starts = np.flatnonzero(np.r_[True, wk[1:] != wk[:-1]])
    ends = np.r_[starts[1:] - 1, len(cal) - 1]
    WC = CW[ends]
    WH = np.maximum.reduceat(np.where(np.isfinite(H), H, -np.inf), starts, axis=0)
    WL = np.minimum.reduceat(np.where(np.isfinite(L), L, np.inf), starts, axis=0)
    WH[~np.isfinite(WH)] = np.nan
    WL[~np.isfinite(WL)] = np.nan
    WV = np.add.reduceat(np.nan_to_num(V), starts, axis=0)
    MA = _sma(WC, P["ma"])
    SL = np.full_like(MA, np.nan)
    SL[P["slope_w"]:] = MA[P["slope_w"]:] / MA[:-P["slope_w"]] - 1
    st, t0, prev, how, lvl, bw, lo, _ = _run(WC, WH, WL, MA, SL, P)
    bi = want.index(bench)
    rel = WC / WC[:, [bi]]
    mrs = (rel / _sma(rel, 52) - 1) * 100                              # Mansfield relative strength vs NIFTY 500
    vavg = pd.DataFrame(WV).rolling(10, min_periods=8).mean().shift(1).to_numpy()
    Wn = len(ends) - 1
    nsess = len(cal) - 1
    fv = np.where(np.isfinite(WC).any(axis=0), np.argmax(np.isfinite(WC), axis=0), 0)   # each stock's first weekly close
    stage, days, det, capped = {}, {}, {}, set()
    for j, s in enumerate(want):
        if s == bench or st[j] == 0 or t0[j] < 0:
            continue
        w0 = int(t0[j])
        a, b = int(starts[w0]), int(ends[w0])
        d0 = b
        if st[j] == 2 and np.isfinite(lvl[j]):                          # the session that crossed the level
            hit = np.flatnonzero(C[a:b + 1, j] > lvl[j])
            if len(hit):
                d0 = a + int(hit[0])
        stage[s] = int(st[j])
        days[s] = int(nsess - d0)
        c = WC[Wn, j]
        rec = {"st": int(st[j]), "d0": cal[d0], "days": int(nsess - d0), "prev": int(prev[j]) or None,
               "ext": _r((c / MA[Wn, j] - 1) * 100), "slope": _r(SL[Wn, j] * 100), "mrs": _r(mrs[Wn, j])}
        if not prev[j]:
            rec["cap"] = True          # in this stage since its first reading: the days are a minimum
            rec["ipo"] = bool(w0 - fv[j] <= P["ma"] + P["slope_w"] + 2)    # first reading soon after its first price
            capped.add(s)
        if st[j] == 2:
            rec.update({"how": int(how[j]), "lvl": _r(lvl[j], 2), "basew": int(bw[j]) if bw[j] >= 0 else None,
                        "bvol": _r(WV[w0, j] / vavg[w0, j], 1) if np.isfinite(vavg[w0, j]) and vavg[w0, j] > 0 else None,
                        "gain": _r((CW[nsess, j] / lvl[j] - 1) * 100) if np.isfinite(lvl[j]) and lvl[j] > 0 else None})
        elif st[j] == 1:
            rec.update({"lvl": _r(lvl[j], 2), "lo": _r(lo[j], 2), "basew": int(bw[j]),
                        "dist": _r((CW[nsess, j] / lvl[j] - 1) * 100) if np.isfinite(lvl[j]) and lvl[j] > 0 else None,
                        "notdn": bool(np.isfinite(SL[Wn, j]) and SL[Wn, j] >= -P["s_dn"])})
        det[s] = rec
    cnt = pd.Series(stage).value_counts().to_dict() if stage else {}
    print(f"stages (weekly, Weinstein): {len(stage)} stocks — stage 1 {cnt.get(1, 0)}, 2 {cnt.get(2, 0)}, 3 {cnt.get(3, 0)}, "
          f"4 {cnt.get(4, 0)}; {len(ends)} weeks, {time.time() - t_0:.1f}s")
    return {"stage": stage, "days": days, "capped": capped, "detail": det, "weeks": len(ends)}


def site_json(R, last, uset):
    """stages.json: every Stage 2 stock with its days in Stage 2 and how the run began, the counts, the zones of
    the run (from the age test) and the test results."""
    s2 = [{"s": s, **{k: v for k, v in d.items() if k != "st"}} for s, d in R["detail"].items() if d["st"] == 2]
    s2.sort(key=lambda r: (r["days"], r["s"]))
    ev_f = CFG / "stage_evidence.json"
    ev = json.loads(ev_f.read_text(encoding="utf-8")) if ev_f.exists() else None
    cnt = {k: sum(1 for d in R["detail"].values() if d["st"] == k) for k in (1, 2, 3, 4)}
    cnt_l = {k: sum(1 for s, d in R["detail"].items() if d["st"] == k and s in uset) for k in (1, 2, 3, 4)}
    return {"asof": last, "params": P, "zones": {"new": NEW_DAYS, "late": LATE_DAYS}, "counts": cnt, "counts_liquid": cnt_l,
            "s2": s2, "evidence": ev}
