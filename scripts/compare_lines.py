"""Data for the Rotation tab's "Compare lines" pop-up: the Bars view drawn day by day.

For every group (theme, sector, NSE index, industry) and every window, the line is the mean (or median) % change of
the group's stocks since the window's first session - the same stocks, the same closes (ffill of up to 3 sessions)
and the same start day that the Bars view's return uses. So on the last day each line ends exactly on its bar, and
the pop-up's ranks and thirds are the Bars view's ranks and thirds.

Windows: 1M 3M 6M YTD 1Y on daily closes; 3Y 5Y on week-end closes (Monday-Friday weeks, dated by the week's last
session). A stock counts in a window only if it has a close on the first and the last day; a group needs
min_group_size such stocks (the Bars view's rule). Inside a window a missing day carries the last close forward.

Writes docs/data/cmp/<type>.<u>.<agg>.json - type = themes / sector / nseindex / industry, u = a (every stock) or
l (liquid universe), agg = mean / median - so the browser loads only the one file that matches the toolbar:
  {asof, kind, u, agg, bench_name, pers, dd, wd,
   be: {window: NIFTY 500 % change},  b: {window: [NIFTY 500 path]},
   g:  {group: {window: [path]}},     s: {group: {window: [stocks, stocks up, end % x 100]}}}
Paths are % x 10 as integers (one decimal). Called from compute.py; never breaks the daily run."""
import json
import re
import statistics as stt
from pathlib import Path

import numpy as np
import pandas as pd

DAILY = {"1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252}
WEEKLY = {"3Y": 156, "5Y": 260}
BARS = ("1M", "3M", "6M", "YTD", "1Y")          # windows the Bars view also shows (checked against stocks.json)


def slug(kind):
    return re.sub(r"[^a-z0-9]", "", kind.lower())


def _i10(a):
    return [int(round(float(x) * 1000)) if np.isfinite(x) else None for x in a]


def build(PFULL, rows, groups, bench, last, min_size, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.json"):
        f.unlink()
    P = PFULL[PFULL.date <= last]
    cal = sorted(P.loc[P.symbol == bench, "date"].unique())
    if not cal or cal[-1] != last:
        raise ValueError(f"benchmark calendar does not end on {last}")
    syms = sorted({r["s"] for r in rows} | {bench})
    W = (P[P.symbol.isin(set(syms))].pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
         .reindex(cal))
    C = W.ffill(limit=3)                                   # what compute.py's returns use
    CF = W.ffill()                                         # inside a window only
    col = {s: i for i, s in enumerate(C.columns)}
    Cv, CFv = C.to_numpy(dtype=float), CF.to_numpy(dtype=float)
    L = len(cal) - 1
    prev_year = [i for i, d in enumerate(cal) if d < cal[-1][:4] + "-01-01"]
    wins = {}
    for per, n in DAILY.items():
        s = (prev_year[-1] if prev_year else None) if n is None else L - n
        if s is not None and s >= 0:
            wins[per] = list(range(s, L + 1))
    dt = pd.to_datetime(pd.Series(cal))
    wk = (dt - pd.to_timedelta(dt.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    wend = pd.Series(range(len(cal))).groupby(wk.values).max().sort_values().tolist()     # last session of each week
    for per, n in WEEKLY.items():
        if len(wend) > n:
            wins[per] = wend[-(n + 1):]
    if not wins:
        raise ValueError("not enough price history")
    pers = [p for p in list(DAILY) + list(WEEKLY) if p in wins]
    d0 = min(wins[p][0] for p in pers if p in DAILY)
    dd = cal[d0:]
    wd = [cal[i] for i in wend[-(WEEKLY["5Y"] + 1):]]
    bi = col[bench]
    b_path, b_end = {}, {}
    for per in pers:
        r = wins[per]
        b_path[per] = _i10(CFv[r, bi] / Cv[r[0], bi] - 1.0)
        b_end[per] = round(float(Cv[r[-1], bi] / Cv[r[0], bi] - 1.0) * 100, 2)
    everyone = {r["s"] for r in rows}
    liquid = {r["s"] for r in rows if r.get("lq") != 0}
    rets = {r["s"]: r.get("r") or {} for r in rows}
    files, sizes, worst, checked = 0, 0, 0.0, 0
    kinds = {}
    for kind, gs in groups.items():
        for u, uset in (("a", everyone), ("l", liquid)):
            for agg in ("mean", "median"):
                f_agg = np.nanmean if agg == "mean" else np.nanmedian
                out = {"asof": last, "kind": kind, "u": u, "agg": agg, "bench_name": bench, "pers": pers, "dd": dd, "wd": wd,
                       "be": b_end, "b": b_path, "g": {}, "s": {}}
                for name, members in gs.items():
                    idx = [col[s] for s in members if s in uset and s in col]
                    if len(idx) < min_size:
                        continue
                    g, st = {}, {}
                    for per in pers:
                        r = wins[per]
                        c0, c1 = Cv[r[0], idx], Cv[r[-1], idx]
                        ok = np.isfinite(c0) & np.isfinite(c1) & (c0 > 0)
                        if ok.sum() < min_size:
                            continue
                        k = np.asarray(idx)[ok]
                        m = CFv[np.ix_(r, k)] / Cv[r[0], k] - 1.0
                        m[-1] = Cv[r[-1], k] / Cv[r[0], k] - 1.0          # the last day exactly as the bar
                        with np.errstate(all="ignore"):
                            v = f_agg(m, axis=1)
                        g[per] = _i10(v)
                        st[per] = [int(len(k)), int((m[-1] > 0).sum()), int(round(float(v[-1]) * 10000))]
                        if per in BARS:                                      # same number as the Bars view?
                            vals = [rets[s].get(per) for s in members if s in uset and rets.get(s, {}).get(per) is not None]
                            if len(vals) >= min_size:
                                bar = stt.mean(vals) if agg == "mean" else stt.median(vals)
                                worst = max(worst, abs(bar - float(v[-1]) * 100))
                                checked += 1
                    if g:
                        out["g"][name], out["s"][name] = g, st
                fn = out_dir / f"{slug(kind)}.{u}.{agg}.json"
                fn.write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
                files += 1
                sizes += fn.stat().st_size
                if u == "a" and agg == "mean":
                    kinds[kind] = len(out["g"])
    print(f"compare lines: {files} files ({sizes / 1e6:.1f} MB), groups {kinds}; "
          f"line ends vs the Bars view: {checked} checked, worst gap {worst:.3f} points")
    if worst > 0.06:
        print("compare lines: WARNING - some line ends differ from the Bars view by more than rounding")
    return {"asof": last, "pers": pers, "kinds": kinds, "files": files, "check": {"n": checked, "worst": round(worst, 3)}}
