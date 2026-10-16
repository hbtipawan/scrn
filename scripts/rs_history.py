"""RS rating history and the RS line's new highs ("blue dots").

RS rating (1–99) is the site's IBD-style rating: 40% weight on the last quarter's return, 20% on each of the three
quarters before, ranked across the liquid universe (stocks outside it are placed among the liquid ones). Here it is
computed for every session of the last year, so a stock rated 90 today can be told apart: climbing from 70, or
slipping from 99.

The RS line is the stock's close divided by NIFTY 500. A "blue dot" (William O'Neil / MarketSmith) marks a session
on which the RS line closed at a 52-week high — the stock beating the market by more than at any time in a year.
When the dot comes while price is still below its own high, the strength is showing before the breakout.

build() returns per-stock fields for stocks.json, rs.json for the website (weekly RS ratings + blue-dot positions
in the closes.json window) and the frames the scanners need. scans() adds four scanners.
"""
import numpy as np
import pandas as pd

W = (0.4, 0.2, 0.2, 0.2)
N = (63, 126, 189, 252)
WINDOW = 260            # sessions kept for the site (same window as closes.json)
PATH = 60               # sessions looked back for "coming from" (12 weeks)
MOVE = 10               # rating points that count as a move


def score_frame(C):
    """IBD-style RS score for every session (same formula as compute.rs_score, vectorised)."""
    part = avail = None
    for w, n in zip(W, N):
        r = C / C.shift(n)
        part = (r.fillna(0) * w) if part is None else part + r.fillna(0) * w
        a = r.notna() * w
        avail = a if avail is None else avail + a
    return part / avail.replace(0, np.nan)


def ratings(C, U, A, window=WINDOW):
    """RS rating 1–99 per session for every stock in A. Stocks in U are ranked among themselves (as compute.py
    does for today); the others are placed where their score falls among U's scores that day."""
    sc = score_frame(C[A]).iloc[-window:]
    su = sc[U]
    R = (su.rank(axis=1, pct=True) * 98 + 1).round()
    uset = set(U)
    others = [s for s in A if s not in uset]
    if others:
        so = sc[others].to_numpy()
        ref = np.sort(su.to_numpy(), axis=1)               # NaN sorts last
        cnt = su.notna().sum(axis=1).to_numpy()
        out = np.full(so.shape, np.nan)
        for i in range(len(sc)):
            n = cnt[i]
            if not n:
                continue
            r, v = ref[i, :n], so[i]
            ok = ~np.isnan(v)
            lo, hi = np.searchsorted(r, v[ok], "left"), np.searchsorted(r, v[ok], "right")
            out[i, ok] = np.round(np.clip((lo + hi) / 2 / n, 1 / n, 1) * 98 + 1)
        R = pd.concat([R, pd.DataFrame(out, index=sc.index, columns=others)], axis=1)
    return R[A]


def blue_dots(C, bench):
    """True where the RS line (close ÷ benchmark) closes at its 52-week high (needs 200+ sessions of history)."""
    rsl = C.div(bench.reindex(C.index), axis=0)
    hi = rsl.rolling(252, min_periods=200).max()
    return (rsl >= hi * (1 - 1e-9)) & hi.notna() & rsl.notna()


def path_of(r):
    """Where today's rating is coming from over the last PATH sessions (12 weeks).
    Rising from the 12-week low when it is MOVE+ points below today, falling from the 12-week high when that is MOVE+
    points above; when both are, the more recent of the two decides (99 → 60 → 85 is 'rising from 60').
    Returns (direction +1 / -1 / 0 steady, rating then, sessions ago)."""
    x = r.iloc[-PATH:].to_numpy(dtype=float)
    now = x[-1]
    if np.isnan(now) or np.isnan(x).all():
        return 0, None, None
    lo, hi = np.nanmin(x), np.nanmax(x)
    ilo = len(x) - 1 - int(np.flatnonzero(x == lo)[-1])     # sessions ago (latest time it was there)
    ihi = len(x) - 1 - int(np.flatnonzero(x == hi)[-1])
    up, down = now - lo >= MOVE, hi - now >= MOVE
    if up and (not down or ilo < ihi):
        return 1, int(lo), ilo
    if down:
        return -1, int(hi), ihi
    return 0, None, None


def build(CL, bench, U, A, rs_all, closes_dates):
    """CL: closes (ffilled like compute.py) for 520+ sessions on the benchmark calendar."""
    R = ratings(CL, U, A)
    dates = list(R.index)
    a_, b_ = R.iloc[-1], rs_all.reindex(R.columns)
    both = a_.notna() & b_.notna()
    agree = float((a_[both] == b_[both]).mean()) if both.any() else float("nan")
    # weekly points: the last session of each week, 53 weeks, the latest session last
    dt = pd.to_datetime(pd.Index(dates))
    wk = pd.Series(np.arange(len(dates)), index=dt).groupby(dt.to_period("W")).last()
    pos = [int(p) for p in wk.values[-53:]]
    if pos[-1] != len(dates) - 1:
        pos.append(len(dates) - 1)
    dot = blue_dots(CL[A], bench)
    # dot positions are indices into closes.json's dates
    cpos = {d: i for i, d in enumerate(closes_dates)}
    dotw = dot.loc[[d for d in closes_dates if d in dot.index]]
    per, rows = {}, {}
    n = len(dates)
    for s in A:
        r = R[s]
        if r.isna().all():
            continue
        di = [cpos[d] for d in dotw.index[dotw[s].to_numpy()]]
        g = lambda k: None if n <= k or pd.isna(r.iloc[-1 - k]) else int(r.iloc[-1 - k])
        dr, frm, ago = path_of(r)
        p = {"rs4w": g(20), "rs12w": g(60), "rsmx": int(r.max()), "rsmn": int(r.min()),
             "rsnh": 1 if (di and di[-1] == len(closes_dates) - 1) else 0}
        if di:
            p["rsnhd"] = len(closes_dates) - 1 - di[-1]      # sessions since the last blue dot
            p["rsn20"] = sum(1 for i in di if i >= len(closes_dates) - 20)
        if dr:
            p.update({"rsdir": dr, "rsfrom": frm, "rsago": ago})
        per[s] = p
        rows[s] = {"h": [None if pd.isna(r.iloc[q]) else int(r.iloc[q]) for q in pos], "d": di}
    out = {"asof": dates[-1], "weeks": [dates[q] for q in pos], "rows": rows,
           "params": {"path": PATH, "move": MOVE}}
    print(f"RS history: {len(rows)} stocks, {len(pos)} weekly points; today's rating matches the main rating for "
          f"{agree:.1%}; blue dots today: {sum(v['rsnh'] for s, v in per.items() if s in set(U))} liquid stocks")
    return per, out, R, dot


def scans(U, rs_now, per, R, dot, bars, c, hi52):
    """RS-history scanners on the liquid universe."""
    rs = rs_now.reindex(U)
    rs4 = pd.Series({s: per.get(s, {}).get("rs4w") for s in U}, dtype=float)
    pk8 = R[U].iloc[-40:].max()                                 # best rating in the last 8 weeks
    blue = dot[U].iloc[-1] & (bars.reindex(U) >= 200)
    from_hi = (c.reindex(U) / hi52.reindex(U) - 1) * 100
    hits, metric, meta = {}, {}, []

    def add(id_, name, cat, desc, mask, label, vals, fmt="num", sort="metric"):
        mask = mask.reindex(U).fillna(False).astype(bool)
        syms = sorted(mask.index[mask])
        hits[id_] = syms
        metric[id_] = {s: (None if pd.isna(vals.get(s)) else round(float(vals[s]), 1)) for s in syms}
        meta.append({"id": id_, "name": name, "cat": cat, "desc": desc, "metric": label, "fmt": fmt, "sort": sort})

    add("rs_bluedot", "RS line at a 52-week high (blue dot)", "Relative strength",
        "The RS line (stock ÷ NIFTY 500) closed at its highest level in 52 weeks today — the stock is beating the market "
        "by more than at any time in a year (MarketSmith's blue dot). Price may or may not be at a high.",
        blue, "From 52W high %", from_hi, "pct", "metric")
    add("rs_climb", "RS rating climbing", "Relative strength",
        "RS rating 80+ today and at least 20 points higher than 4 weeks ago — a stock moving up the leaderboard "
        "(say 65 → 90), not one sliding down from 99.",
        (rs >= 80) & (rs - rs4 >= 20), "RS Δ 4 weeks", rs - rs4, "int", "metric")
    add("rs_top_hold", "RS 90+ for 8 weeks", "Relative strength",
        "RS rating 90 or higher on every session of the last 8 weeks — persistent leadership, not a one-week spike.",
        R[U].iloc[-40:].min() >= 90, "RS rating", rs, "int", "metric")
    add("rs_fade", "Leader losing RS", "Weakness",
        "RS rating was 95+ within the last 8 weeks and is now 80 or lower — a former leader losing ground to the "
        "market. Check it if you hold it.",
        (pk8 >= 95) & (rs <= 80), "RS drop from 8-week peak", rs - pk8, "int", "metric_asc")
    return meta, hits, metric
