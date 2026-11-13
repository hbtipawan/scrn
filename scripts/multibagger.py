"""Multibagger checks: seven yes/no checks that, in a 2016-23 test on NSE, about doubled the odds of a stock
rising 5x within 3 years (config/multibagger_evidence.json has the record and its limits).

  1 size        market cap between 300 and 5,000 Cr
  2 rs          RS rating 80 or more
  3 volume      volume on up days >= 1.2 x volume on down days, last 50 sessions
  4 forgotten   no new all-time high for 2 years (504 sessions) or more
  5 cheap       price to book under 1.5, or price to sales under 1
  6 cash        operating cash flow of the last financial year >= 8% of market cap
  7 sales       sales growth of the last financial year at least 10 points above the year before

A check with no data counts as not passed (as in the test). It ranks odds; it does not predict.
Called from compute.py after the fundamentals are attached to the rows; never breaks the daily run."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

CHECKS = ["size", "rs", "volume", "forgotten", "cheap", "cash", "sales"]


def _annual(cfg: Path, last: str):
    """latest financial-year operating cash flow, and annual sales growth this year and the year before (NSE filings)."""
    f = cfg / "fund_results.csv"
    if not f.exists():
        return {}, {}
    r = pd.read_csv(f, dtype={"symbol": str}, usecols=["symbol", "qe", "basis", "ytd_rev", "ocf"])
    r = r[r.qe.str[5:7] == "03"]                                   # March year-ends (as in fundamentals.py)
    r = r.sort_values(["symbol", "qe", "basis"]).drop_duplicates(["symbol", "qe"], keep="first")   # consolidated ("C") first
    fresh = (pd.Timestamp(last) - pd.to_datetime(r.qe)).dt.days <= 640       # year end + filing time + a year in use
    ocf, acc = {}, {}
    for s, g in r.groupby("symbol"):
        g = g.sort_values("qe")
        o = g[g.ocf.notna() & fresh.reindex(g.index)]
        if len(o):
            ocf[s] = float(o.ocf.iloc[-1])
        v = g[g.ytd_rev.notna()]
        if len(v) >= 3 and bool(fresh.reindex(v.index).iloc[-1]):
            a, b, c = (float(x) for x in v.ytd_rev.iloc[-3:])
            y = [int(q[:4]) for q in v.qe.iloc[-3:]]
            if a > 0 and b > 0 and c > 0 and y[2] - y[1] == 1 and y[1] - y[0] == 1:
                acc[s] = ((c / b - 1) - (b / a - 1)) * 100, (c / b - 1) * 100
    return ocf, acc


def build(PFULL, rows, ath_prior, last, cfg: Path):
    """-> (multibagger.json content, {symbol: checks passed}) for the liquid stocks of the last session."""
    liq = [r["s"] for r in rows if r.get("lq") != 0 and r.get("px")]
    P = PFULL[PFULL.symbol.isin(set(liq))]
    C = P.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    V = P.pivot_table(index="date", columns="symbol", values="volume", aggfunc="last").reindex_like(C)
    H = P.pivot_table(index="date", columns="symbol", values="high", aggfunc="last").reindex_like(C)
    C, V, H = C.loc[:last], V.loc[:last], H.loc[:last]
    # 3 - up-day volume against down-day volume, last 50 sessions
    d = C.pct_change(fill_method=None).iloc[-50:]
    v = V.iloc[-50:]
    upv, dnv, nobs = v.where(d > 0, 0).sum(), v.where(d < 0, 0).sum(), d.notna().sum()
    ud = (upv / dnv.where(dnv > 0)).where(nobs >= 30)
    # 4 - sessions since the last all-time high (highs in the price file; older highs from config/ath.csv via compute.py)
    hmax = H.max()
    ath = np.fmax(hmax, ath_prior.reindex(H.columns)) if ath_prior is not None else hmax
    at_ath = H.ge(ath * 0.9999, axis=1)
    n = len(H)
    pos = pd.Series(np.arange(n), index=H.index)
    last_at = at_ath.mul(pos, axis=0).where(at_ath).max()          # row number of the last session at the all-time high
    since = (n - 1 - last_at).where(last_at.notna(), n)            # never inside the file: at least the file's length
    hist = C.notna().sum()
    # market state: share of these stocks above their 200-day average
    s200 = C.rolling(200, min_periods=160).mean().iloc[-1]
    ab = (C.iloc[-1] > s200)[s200.notna() & C.iloc[-1].notna()]
    ab200 = round(float(ab.mean() * 100), 1) if len(ab) else None
    ocf, acc = _annual(cfg, last)
    out, by = [], {}
    num = lambda x: x is not None and isinstance(x, (int, float)) and np.isfinite(x)
    for r in rows:
        s = r["s"]
        if s not in C.columns or r.get("lq") == 0:
            continue
        mc, rs, pb, ps = r.get("mc"), r.get("rs"), r.get("pb"), r.get("ps")
        u = float(ud[s]) if s in ud.index and np.isfinite(ud[s]) else None
        sn = int(since[s]) if s in since.index and np.isfinite(since[s]) else None
        cy = ocf[s] / mc * 100 if s in ocf and num(mc) and mc > 0 else None
        ac = acc.get(s)
        c = [bool(num(mc) and 300 <= mc < 5000),
             bool(num(rs) and rs >= 80),
             bool(u is not None and u >= 1.2),
             bool(sn is not None and sn >= 504 and (hist[s] >= 504 or (ath_prior is not None and np.isfinite(ath_prior.get(s, np.nan))))),
             bool((num(pb) and 0 < pb < 1.5) or (num(ps) and 0 < ps < 1)),
             bool(cy is not None and cy >= 8),
             bool(ac is not None and ac[0] >= 10)]
        pts = int(sum(c))
        row = {"s": s, "k": pts, "c": [int(x) for x in c],
               "ud": None if u is None else round(u, 2),
               "ay": None if sn is None else round(sn / 252, 1), "ao": bool(sn is not None and sn >= n),   # ao: older than the price file
               "cy": None if cy is None else round(cy, 1),
               "sa": None if ac is None else round(ac[0], 1), "sg": None if ac is None else round(ac[1], 1)}
        out.append(row)
        by[s] = pts
    out.sort(key=lambda x: (-x["k"], x["s"]))
    ev = cfg / "multibagger_evidence.json"
    return ({"asof": last, "n": len(out), "ab200": ab200, "hi": sum(1 for x in out if x["k"] >= 5), "checks": CHECKS, "rows": out,
             "evidence": json.loads(ev.read_text(encoding="utf-8")) if ev.exists() else None}, by)
