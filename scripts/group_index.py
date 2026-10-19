"""A daily price series for every group on the site — theme, sector, NSE index and industry — plus the group's
breadth, money flow, RS line and RS rating, and signals that tend to come early in a sector rotation.

Price series
  * NSE Index groups use NSE's official index (open/high/low/close from config/nse/idx) whenever NSE's file covers
    the group's whole history; otherwise, and for every theme, sector and industry, the site builds an
    equal-weight index of the member stocks: each day the index moves by the average of the members' daily
    returns (rebalanced daily, base 100). Open, high and low are the averages of each member's open, high and low
    against its previous close, so every bar is a real bar (the high is never below the open or close).
  * A member counts on a day only if it traded that day. A daily move larger than ±40% is treated as a data error
    and left out of that day's average (it happens a handful of times in six years).
  * Two versions: every member stock, and only members in the liquid universe (when 3 or more).
  * Membership is today's list for the whole history (stocks join when they list).

Per day, per group: open/high/low/close, turnover of the members (Rs Cr), % of members above their 50- and 200-day
averages, members at 52-week highs and lows, members counted, and the group RS rating (1–99, the IBD formula on
the group's own index, ranked among the groups of the same kind: themes against themes, industries against
industries ...).

Written for the website (docs/data/grp/): one file per group (loaded when its chart opens), _common.json (dates and
NIFTY 500) and the summary in grp.json (latest numbers, signals, sparklines, rotation-map tails).
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MIN_MEMBERS = 3
CLIP = 0.40
RS_W, RS_N = (0.4, 0.2, 0.2, 0.2), (63, 126, 189, 252)
KIND_CODE = {"Themes": "t", "Sector": "s", "NSE Index": "x", "Industry": "i"}
# the site's NSE-index group names that differ from NSE's own spelling
OFFICIAL_ALIAS = {"Nifty Fin Services": "Nifty Financial Services", "Nifty Healthcare": "Nifty Healthcare Index",
                  "Nifty Infra": "Nifty Infrastructure", "Nifty Consumption": "Nifty India Consumption",
                  "Nifty Railways PSU": "Nifty India Railways PSU",
                  "Nifty New Age Consumption": "Nifty India New Age Consumption"}


def slug(kind, name, used):
    s = KIND_CODE.get(kind, "g") + "-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    base, k = s, 2
    while s in used:
        s = f"{base}-{k}"
        k += 1
    used.add(s)
    return s


# ═════════════════════════════════════════════ per-stock inputs (computed once, shared by all groups)
class Stocks:
    def __init__(self, P, cal):
        piv = lambda f: P.pivot_table(index="date", columns="symbol", values=f, aggfunc="last").reindex(cal).astype("float64")
        O, H, L, C, V = (piv(f) for f in ("open", "high", "low", "close", "volume"))
        self.cal = cal
        traded = C.notna() & (V.fillna(0) > 0)          # a bar with no trades is not a session for the stock
        prev = C.ffill(limit=3).shift(1)
        rel = lambda X: X / prev - 1
        r, ro, rh, rl = rel(C), rel(O), rel(H), rel(L)
        bad = (r.abs() > CLIP) | (ro.abs() > CLIP) | (rh.abs() > CLIP) | (rl.abs() > CLIP)
        self.clipped = int(bad.sum().sum())
        ok = traded & prev.notna() & ~bad
        self.r, self.ro, self.rh, self.rl = r.where(ok), ro.where(ok), rh.where(ok), rl.where(ok)
        self.to = (C * V / 1e7).where(C.notna())                       # turnover, Rs Cr
        Cf = C.ffill(limit=3)
        s50, s200 = Cf.rolling(50, min_periods=50).mean(), Cf.rolling(200, min_periods=200).mean()
        valid = C.notna()
        self.a50 = ((Cf > s50) & valid).where(s50.notna() & valid)
        self.a200 = ((Cf > s200) & valid).where(s200.notna() & valid)
        hi, lo = Cf.rolling(252, min_periods=200).max(), Cf.rolling(252, min_periods=200).min()
        self.nh = ((Cf >= hi) & valid & hi.notna()).astype(float)
        self.nl = ((Cf <= lo) & valid & lo.notna()).astype(float)
        self.valid = valid


def build_series(S, members):
    """Equal-weight OHLC index and member statistics for one group. Returns a DataFrame on S.cal or None."""
    m = [s for s in members if s in S.r.columns]
    if len(m) < MIN_MEMBERS:
        return None
    r = S.r[m]
    cnt = r.notna().sum(axis=1)
    ok = cnt >= MIN_MEMBERS
    if not ok.any():
        return None
    mean = lambda X: X[m].mean(axis=1).where(ok)
    mr, mo, mh, ml = mean(S.r), mean(S.ro), mean(S.rh), mean(S.rl)
    first = ok.idxmax()
    mr[:first] = np.nan
    growth = (1 + mr.fillna(0))
    growth[:first] = 1.0
    c = 100 * growth.cumprod()
    c[c.index < first] = np.nan
    pc = c.shift(1)
    df = pd.DataFrame({"o": pc * (1 + mo), "h": pc * (1 + mh), "l": pc * (1 + ml), "c": c})
    df.loc[df.index == first, ["o", "h", "l"]] = np.nan
    df["o"] = df["o"].fillna(df["c"])
    df["h"] = np.fmax(df["h"].fillna(df["c"]), df[["o", "c"]].max(axis=1))
    df["l"] = np.fmin(df["l"].fillna(df["c"]), df[["o", "c"]].min(axis=1))
    v = S.valid[m].sum(axis=1)
    df["v"] = S.to[m].sum(axis=1, min_count=1)
    df["b50"] = S.a50[m].mean(axis=1) * 100
    df["b200"] = S.a200[m].mean(axis=1) * 100
    df["nh"], df["nl"], df["n"] = S.nh[m].sum(axis=1), S.nl[m].sum(axis=1), v
    df.loc[df.c.isna(), ["v", "b50", "b200", "nh", "nl", "n"]] = np.nan
    return df


def official_ohlc(name, cal):
    """NSE's own OHLC for an index (config/nse/idx), on the calendar, or None."""
    files = sorted((ROOT / "config" / "nse" / "idx").glob("*.csv.gz"))
    if not files:
        return None
    want = OFFICIAL_ALIAS.get(name, name)
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    rows = []
    for f in files:
        d = pd.read_csv(f)
        d = d[d["index"].map(norm) == norm(want)]
        if len(d):
            rows.append(d)
    if not rows:
        return None
    d = pd.concat(rows).drop_duplicates("date", keep="last").set_index("date").sort_index()
    d = d.reindex(cal)
    for k in ("open", "high", "low"):
        d[k] = d[k].fillna(d["close"])
    return d[["open", "high", "low", "close"]].rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"})


def rs_score(c):
    part = avail = None
    for w, n in zip(RS_W, RS_N):
        r = c / c.shift(n)
        part = r.fillna(0) * w if part is None else part + r.fillna(0) * w
        a = r.notna() * w
        avail = a if avail is None else avail + a
    return part / avail.replace(0, np.nan)


# ═════════════════════════════════════════════ signals
SIG = {
    # id: (name, direction, plain description)
    "g_high": ("Fresh 52-week high", 1, "The group index closed at a 52-week high for the first time in 4+ weeks."),
    "g_base": ("Base breakout", 1, "The group index broke above a 6-week range that was no wider than 10%, above its 200-day average."),
    "g_rsfirst": ("RS line high before price", 1, "The group's RS line (index ÷ NIFTY 500) is at a 6-month high while the index is still 3%+ below its 52-week high — strength showing before the price breakout."),
    "g_thrust": ("Breadth thrust", 1, "% of members above their 50-day average jumped from 30% or less to 60% or more within 10 sessions."),
    "g_rank": ("RS rating climbing", 1, "Group RS rating 70 or higher and at least 20 points higher than 4 weeks ago — the group is moving up the leaderboard."),
    "g_stage2": ("Stage 2 start", 1, "The index crossed above its rising 150-day (30-week) average in the last 5 sessions after spending most of the prior 3 months below it."),
    "g_money": ("Money flowing in", 1, "Members' turnover over the last 20 sessions is 1.5× its 120-session average, with the index up over the 20 sessions."),
    "g_stage2m": ("Stage 2 start with money", 1, "A Stage 2 start — the index crosses above its rising 150-day (30-week) average after 3 months mostly below it — while members' turnover over 20 sessions is at least 1.2× its 120-session average."),
    "g_nhx": ("New highs expanding", 1, "20%+ of members at 52-week highs (5+ members), up from under 10% in the prior 4 weeks."),
    "g_coil": ("Coiling near the high", 1, "20-session range no wider than 5%, within 3% of the 52-week high and above a rising 50-day average."),
    "g_low": ("Fresh 52-week low", -1, "The group index closed at a 52-week low for the first time in 4+ weeks."),
    "g_bcollapse": ("Breadth collapse", -1, "% of members above their 50-day average fell from 70%+ to 30% or less within 10 sessions."),
    "g_rslow": ("RS line breakdown", -1, "The group's RS line is at a 6-month low and the index is below its 200-day average."),
}


def signals(df, bench, rk):
    """Boolean Series per signal on the group's calendar."""
    c, b = df["c"], bench.reindex(df.index)
    out = {}
    hi252 = c.rolling(252, min_periods=200).max()
    lo252 = c.rolling(252, min_periods=200).min()
    at_hi = c >= hi252.shift(1)
    at_lo = c <= lo252.shift(1)
    out["g_high"] = at_hi & ~at_hi.shift(1).rolling(20, min_periods=1).max().fillna(0).astype(bool)
    out["g_low"] = at_lo & ~at_lo.shift(1).rolling(20, min_periods=1).max().fillna(0).astype(bool)
    s50, s150, s200 = (c.rolling(n, min_periods=n).mean() for n in (50, 150, 200))
    bh, bl = c.shift(1).rolling(30).max(), c.shift(1).rolling(30).min()
    out["g_base"] = (bh / bl - 1 <= 0.10) & (c > bh) & (c > s200)
    rsl = c / b
    out["g_rsfirst"] = (rsl >= rsl.rolling(126, min_periods=100).max()) & (c < 0.97 * hi252)
    out["g_rslow"] = (rsl <= rsl.rolling(126, min_periods=100).min()) & (c < s200)
    b50 = df["b50"]
    out["g_thrust"] = (b50 >= 60) & (b50.shift(1).rolling(10, min_periods=5).min() <= 30)
    out["g_bcollapse"] = (b50 <= 30) & (b50.shift(1).rolling(10, min_periods=5).max() >= 70)
    out["g_rank"] = (rk >= 70) & (rk - rk.shift(20) >= 20)
    above = c > s150
    out["g_stage2"] = above & (s150 > s150.shift(20)) & (~above).shift(1).rolling(5, min_periods=1).max().fillna(0).astype(bool) \
        & ((~above).astype(float).shift(5).rolling(60, min_periods=40).mean() >= 0.5)
    v = df["v"]
    mr = v.rolling(20, min_periods=15).mean() / v.shift(20).rolling(120, min_periods=80).mean()
    out["g_money"] = (mr >= 1.5) & (c > c.shift(20))
    out["g_stage2m"] = out["g_stage2"] & (mr >= 1.2)
    share = df["nh"] / df["n"].where(df["n"] >= 5)
    out["g_nhx"] = (share >= 0.20) & (share.shift(1).rolling(20, min_periods=10).max() < 0.10)
    out["g_coil"] = (c.rolling(20).max() / c.rolling(20).min() - 1 <= 0.05) & (c >= 0.97 * hi252) & (c > s50) & (s50 > s50.shift(10))
    return {k: v_.fillna(False).astype(bool) for k, v_ in out.items()}


# ═════════════════════════════════════════════ build everything for the site
def _r(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def _arr(s, nd):
    a = s.to_numpy(dtype=float)
    return [None if not np.isfinite(v) else (int(round(v)) if nd == 0 else round(float(v), nd)) for v in a]


def build(P, groups, U, bench, out_dir, asof, evidence=None):
    """P: prices (symbol, date, open, high, low, close, volume) on the benchmark calendar, full history.
    groups: {kind: {name: [symbols]}} as on the site. U: liquid universe. bench: NIFTY 500 close on the calendar.
    Writes docs/data/grp/*.json and returns the summary (also written as grp.json) and per-group signals today."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.json"):
        f.unlink()
    cal = list(bench.index)
    syms = sorted({s for g in groups.values() for m in g.values() for s in m})
    S = Stocks(P[P.symbol.isin(syms)], cal)
    uset = set(U)
    used, rows, files = set(), [], {}
    series = {}                                   # (kind, name) -> {"a": df, "l": df|None, "src": ...}
    for kind, gs in groups.items():
        for name, mem in gs.items():
            a = build_series(S, mem)
            if a is None or a.c.notna().sum() < 60:
                continue
            liq = [s for s in mem if s in uset]
            l = build_series(S, liq) if len(liq) >= MIN_MEMBERS else None
            src = "ew"
            if kind == "NSE Index":
                off = official_ohlc(name, cal)
                if off is not None:
                    have = off.c.notna() & a.c.notna()
                    if have.sum() >= 0.95 * a.c.notna().sum():
                        for df in (a, l):
                            if df is not None:
                                df[["o", "h", "l", "c"]] = off[["o", "h", "l", "c"]].where(df.c.notna())
                        src = "nse"
            series[(kind, name)] = {"a": a, "l": l, "src": src, "m": len(mem), "ml": len(liq)}
    # group RS rating within each kind and universe
    for kind in groups:
        for u in ("a", "l"):
            keys = [k for k in series if k[0] == kind and series[k][u] is not None]
            if len(keys) < 5:
                for k in keys:
                    series[k][u]["rk"] = np.nan
                continue
            sc = pd.DataFrame({k[1]: rs_score(series[k][u].c) for k in keys})
            rk = (sc.rank(axis=1, pct=True) * 98 + 1).round()
            for k in keys:
                series[k][u]["rk"] = rk[k[1]]
    today = {}
    for (kind, name), g in series.items():
        sl = slug(kind, name, used)
        rec = {"n": name, "k": kind, "id": sl, "src": g["src"], "m": g["m"], "ml": g["ml"]}
        file = {"n": name, "k": kind, "src": g["src"], "m": g["m"], "ml": g["ml"]}
        i0 = int(np.flatnonzero(g["a"].c.notna().to_numpy())[0])
        file["i0"] = i0
        file["ev"] = {}
        for u in ("a", "l"):
            df = g[u]
            if df is None:
                file[u] = None
                continue
            d = df.iloc[i0:]
            file[u] = {"o": _arr(d.o, 2), "h": _arr(d.h, 2), "l": _arr(d.l, 2), "c": _arr(d.c, 2), "v": _arr(d.v, 1),
                       "b50": _arr(d.b50, 0), "b200": _arr(d.b200, 0), "nh": _arr(d.nh, 0), "nl": _arr(d.nl, 0),
                       "cnt": _arr(d.n, 0), "rk": _arr(d.rk, 0)}
            sig = signals(df, bench, df["rk"])
            ev = []                                   # first day of each run of a signal, for chart markers
            for k, on in sig.items():
                fresh = on & ~on.shift(1, fill_value=False)
                ev += [(int(i) - i0, k) for i in np.flatnonzero(fresh.to_numpy()) if i >= i0]
            file["ev"][u] = [[i, k] for i, k in sorted(ev)]
            c = df.c
            last = c.last_valid_index()
            L = c.index.get_loc(last)
            ret = lambda n: _r((c.iloc[L] / c.iloc[L - n] - 1) * 100) if L - n >= 0 and np.isfinite(c.iloc[L - n]) else None
            y0 = c[c.index < f"{last[:4]}-01-01"].dropna()
            hi52 = c.iloc[max(0, L - 251):L + 1].max()
            rsl = c / bench.reindex(c.index)
            rhi = rsl.iloc[max(0, L - 251):L + 1].max()
            s150 = c.rolling(150, min_periods=150).mean()
            sl150 = s150.iloc[L] / s150.iloc[L - 20] - 1 if L >= 170 else np.nan
            stage = None
            if np.isfinite(s150.iloc[L]) and np.isfinite(sl150):
                px = c.iloc[L]
                stage = 2 if px > s150.iloc[L] and sl150 > 0.01 else 4 if px < s150.iloc[L] and sl150 < -0.01 else 3 if px >= s150.iloc[L] else 1
            v = df.v
            mr = v.iloc[max(0, L - 19):L + 1].mean() / v.iloc[max(0, L - 139):max(1, L - 19)].mean() if L > 60 else np.nan
            wk = pd.Series(c.values, index=pd.to_datetime(c.index)).groupby(pd.to_datetime(c.index).to_period("W")).last().dropna()
            rkw = pd.Series(df.rk.values, index=pd.to_datetime(c.index)).groupby(pd.to_datetime(c.index).to_period("W")).last()
            fired = {k: int(L - np.flatnonzero(sig[k].iloc[:L + 1].to_numpy())[-1]) for k in sig if sig[k].iloc[max(0, L - 19):L + 1].any()}
            share = df.nh.iloc[L] / df.n.iloc[L] if df.n.iloc[L] else np.nan
            rec[u] = {"r": {"1D": ret(1), "1W": ret(5), "1M": ret(21), "3M": ret(63), "6M": ret(126), "1Y": ret(252),
                            "YTD": _r((c.iloc[L] / y0.iloc[-1] - 1) * 100) if len(y0) else None},
                      "rk": _r(df.rk.iloc[L], 0), "rk4": _r(df.rk.iloc[L - 20], 0) if L >= 20 else None,
                      "rk12": _r(df.rk.iloc[L - 60], 0) if L >= 60 else None,
                      "h52": _r((c.iloc[L] / hi52 - 1) * 100, 1), "rh52": _r((rsl.iloc[L] / rhi - 1) * 100, 1),
                      "st": stage, "b50": _r(df.b50.iloc[L], 0), "b200": _r(df.b200.iloc[L], 0),
                      "nh": _r(df.nh.iloc[L], 0), "nl": _r(df.nl.iloc[L], 0), "cnt": _r(df.n.iloc[L], 0),
                      "nhp": _r(share * 100, 0), "mr": _r(mr, 2), "to": _r(v.iloc[max(0, L - 19):L + 1].mean(), 1),
                      "sp": [_r(x, 2) for x in wk.iloc[-26:]], "rkp": [_r(x, 0) for x in rkw.iloc[-26:]],
                      "sig": sorted(fired, key=lambda k: fired[k]), "ago": fired}
            today.setdefault(u, {})[sl] = [k for k in fired if fired[k] == 0]
        rows.append(rec)
        (out_dir / f"{sl}.json").write_text(json.dumps(file, separators=(",", ":"), allow_nan=False))
        files[(kind, name)] = sl
    common = {"dates": cal, "bench": [_r(x, 2) for x in bench], "bench_name": "NIFTY 500", "asof": asof}
    (out_dir / "_common.json").write_text(json.dumps(common, separators=(",", ":"), allow_nan=False))
    meta = {k: {"name": v[0], "dir": v[1], "desc": v[2]} for k, v in SIG.items()}
    summary = {"asof": asof, "sig": meta, "evidence": evidence, "rows": rows, "clipped": S.clipped,
               "kinds": {k: [files[(k, n)] for n in groups[k] if (k, n) in files] for k in groups}}
    print(f"group charts: {len(rows)} groups ({', '.join(f'{k} {len(v)}' for k, v in summary['kinds'].items())}); "
          f"official NSE price for {sum(1 for r in rows if r['src'] == 'nse')}; {S.clipped} member bars left out as "
          f"data errors (moves over ±{int(CLIP * 100)}%); signals today: "
          + ", ".join(f"{k} {sum(1 for v in today.get('l', {}).values() if k in v)}" for k in SIG))
    return summary, today, files
