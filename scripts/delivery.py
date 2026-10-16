"""Delivery: how much of each day's volume was actually taken into demat accounts (NSE's security-wise
delivery position, stored in config/nse/dlv by fetch_nse_daily.py).

Intraday traders square off the same day; delivery volume is shares that changed hands for keeps. A burst of
delivered shares on an up day, repeated over weeks, is the footprint of accumulation; the same on down days is
distribution.

NSE's quantities are raw (not adjusted for later splits or bonuses). The site's price file has split-adjusted
volume, so every delivered quantity is put on the same basis: delivered shares = NSE delivery % x adjusted volume.
Value per trade (Rs) = close x volume / number of trades, which needs no adjustment at all.
BE/BZ-series stocks trade for delivery only (every trade is delivered), so their delivery % carries no information
and they are left out of the delivery-% measures.

build() -> per-stock fields for stocks.json, dlv.json for the stock window (last 60 sessions) and the scanners.
"""
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DLV = ROOT / "config" / "nse" / "dlv"
SPIKE = 3.0          # delivered shares vs the 50-session average
ACC_X = 1.5          # an accumulation / distribution day: delivered shares this many times the average
SHOW = 60            # sessions of history kept for the stock window


def renames(path=ROOT / "config" / "nse" / "symbol_changes.json"):
    """[(old, new, effective date)] from NSE's symbol-change list."""
    try:
        return [tuple(r) for r in json.loads(Path(path).read_text())["rows"]]
    except (OSError, ValueError, KeyError):
        return []


def load(since, folder=DLV, changes=None):
    """Delivery rows since a date, with old symbols mapped to today's (before each change's effective date)."""
    files = [f for f in sorted(glob.glob(str(Path(folder) / "*.csv.gz"))) if Path(f).name[:7] >= since[:7]]
    if not files:
        return None
    d = pd.concat([pd.read_csv(f, dtype={"symbol": str, "series": str, "date": str}) for f in files], ignore_index=True)
    d = d[(d.date >= since) & d.series.isin(["EQ", "BE", "BZ"])]
    for old, new, eff in (changes if changes is not None else renames()):
        m = (d.symbol == old) & (d.date < eff)
        if m.any():
            d.loc[m, "symbol"] = new
    d["t2t"] = d.series.isin(["BE", "BZ"])
    g = d.groupby(["date", "symbol"], as_index=False).agg(volume=("volume", "sum"), trades=("trades", "sum"),
                                                          dlv=("dlv", "sum"), t2t=("t2t", "max"))
    return g


def frames(g, dates, C, V):
    """Wide frames on the price calendar. C, V: the site's split-adjusted close and volume (same columns)."""
    piv = lambda col: g.pivot_table(index="date", columns="symbol", values=col, aggfunc="last").reindex(index=dates, columns=C.columns)
    vol_n, dlv_n, trd = piv("volume"), piv("dlv"), piv("trades")
    t2t = piv("t2t").fillna(0).astype(bool)
    dp = (dlv_n / vol_n.where(vol_n > 0)).clip(upper=1) * 100            # delivery % (NSE)
    dq = dp / 100 * V.where(V > 0)                                         # delivered shares, split-adjusted
    vpt = (C * V / trd.where(trd > 0))                                     # Rs per trade
    return {"dp": dp, "dq": dq, "vpt": vpt, "t2t": t2t, "have": dlv_n.notna() & vol_n.gt(0)}


def measures(F, C):
    dq, dp, vpt, t2t = F["dq"], F["dp"], F["vpt"], F["t2t"]
    avg_dq = dq.rolling(50, min_periods=30).mean().shift(1)
    x = dq / avg_dq                                                         # delivered shares vs average
    up, dn = C > C.shift(1), C < C.shift(1)
    acc = ((x >= ACC_X) & up).rolling(20, min_periods=10).sum()
    dist = ((x >= ACC_X) & dn).rolling(20, min_periods=10).sum()
    # volume-weighted delivery % over 20 and 120 sessions (shares delivered / shares traded), not for BE/BZ
    vol = (dq / (dp / 100)).where(dp > 0)
    dp20 = dq.rolling(20, min_periods=15).sum() / vol.rolling(20, min_periods=15).sum() * 100
    dp120 = dq.rolling(120, min_periods=60).sum() / vol.rolling(120, min_periods=60).sum() * 100
    tsx = vpt / vpt.rolling(50, min_periods=30).median().shift(1)          # Rs per trade vs its usual
    return {"x": x, "acc": acc, "dist": dist, "dp20": dp20.where(~t2t), "dp120": dp120.where(~t2t), "tsx": tsx,
            "up": up, "dn": dn}


def signals(M, C, sma50, d1):
    """Boolean frames for the five delivery scanners (all dates; the site uses the last row)."""
    x, acc, dist, dp20, dp120, tsx = M["x"], M["acc"], M["dist"], M["dp20"], M["dp120"], M["tsx"]
    rng20 = C.rolling(20).max() / C.rolling(20).min() - 1
    return {
        "dlv_spike": (x >= SPIKE) & (d1 >= 0.02) & (C > sma50),
        "dlv_accum": (acc >= 4) & (dist <= 1) & (C > sma50),
        "dlv_quiet": (dp20 >= 1.25 * dp120) & (dp20 >= 40) & (rng20 <= 0.12) & (C > sma50),
        "dlv_bigticket": (tsx >= 3) & (d1 >= 0.01) & (x >= 1.5),
        "dlv_dist": (x >= SPIKE) & (d1 <= -0.02) & (C < sma50),
    }


META = [
    ("dlv_spike", "Delivery spike on an up day", "Delivery",
     "Shares taken into delivery today were 3× or more their 50-session average, on a day the stock rose 2%+ "
     "and closed above its 50-day average — buyers keeping what they bought.", "Delivered × avg", "x", "metric"),
    ("dlv_accum", "Delivery accumulation", "Delivery",
     "4 or more accumulation days in the last 20 sessions (up close with delivered shares 1.5× average or more) "
     "and at most 1 distribution day, price above the 50-day average.", "Accumulation days", "int", "metric"),
    ("dlv_quiet", "Quiet delivery build-up", "Delivery",
     "Delivery % over the last 20 sessions is 25%+ above its 6-month level (and at least 40%) while the price "
     "has stayed within a 12% range above its 50-day average — holders stepping in without chasing.",
     "Delivery % (20d)", "num", "metric"),
    ("dlv_bigticket", "Big-ticket trades", "Delivery",
     "Average value per trade today was 3× or more its usual level on an up day with heavy delivery — larger "
     "orders than the stock normally sees.", "₹ per trade × usual", "x", "metric"),
    ("dlv_dist", "Heavy delivery selling", "Weakness",
     "Delivered shares 3× or more their average on a day the stock fell 2%+ and closed below its 50-day "
     "average — holders leaving, not just traders.", "Delivered × avg", "x", "metric"),
]


def build(C, V, dates, U, A, sma50, closes_dates, since, folder=None):
    """C, V: split-adjusted close / volume for the stocks in A (calendar = dates). Returns None without data."""
    g = load(since, folder or DLV)
    if g is None or g.empty:
        return None
    F = frames(g, dates, C, V)
    M = measures(F, C)
    d1 = C / C.shift(1) - 1
    S = signals(M, C, sma50, d1)
    # the latest session with NSE's delivery file (NSE can publish after the evening run: then the day before is
    # used, up to 3 sessions back, and the site says which day it is)
    cover = F["have"].sum(axis=1) >= 0.5 * C.notna().sum(axis=1)
    ok = [i for i in range(len(dates) - 1, max(-1, len(dates) - 5), -1) if cover.iloc[i]]
    if not ok:
        print(f"delivery: no NSE delivery file for the last 4 sessions to {dates[-1]} — delivery measures skipped")
        return None
    k = ok[0]
    last = dates[k]
    have_today = F["have"].iloc[k]
    per = {}
    r1 = lambda v, nd=1: None if v is None or not np.isfinite(v) else round(float(v), nd)
    row = {key: M[key].iloc[k] for key in ("x", "acc", "dist", "dp20", "dp120", "tsx")}
    dp_t, t2t_t = F["dp"].iloc[k], F["t2t"].iloc[k]
    for s in A:
        if not have_today.get(s, False):
            continue
        p = {"dp": None if t2t_t[s] else r1(dp_t[s], 0), "dq": r1(row["x"][s]), "acc": int(row["acc"][s]) if np.isfinite(row["acc"][s]) else None,
             "dist": int(row["dist"][s]) if np.isfinite(row["dist"][s]) else None, "dp20": r1(row["dp20"][s], 0),
             "dp6m": r1(row["dp120"][s], 0), "tsx": r1(row["tsx"][s])}
        if t2t_t[s]:
            p["t2t"] = 1
        per[s] = {k: v for k, v in p.items() if v is not None}
    # scanners: liquid universe only
    hits, metric, meta = {}, {}, []
    vals = {"dlv_spike": row["x"], "dlv_accum": row["acc"], "dlv_quiet": row["dp20"], "dlv_bigticket": row["tsx"], "dlv_dist": row["x"]}
    for id_, name, cat, desc, label, fmt, sort in META:
        m = S[id_].iloc[k].reindex(U).fillna(False).astype(bool)
        syms = sorted(m.index[m])
        hits[id_] = syms
        metric[id_] = {s: r1(vals[id_].get(s)) for s in syms}
        meta.append({"id": id_, "name": name, "cat": cat, "desc": desc, "metric": label, "fmt": fmt, "sort": sort})
    # stock window: last SHOW sessions of delivery % and delivered value (Rs lakh)
    tail = [d for d in closes_dates if d <= last][-SHOW:]
    dpw, dvw = F["dp"].reindex(tail), (F["dq"] * C).reindex(tail) / 1e5
    rows = {}
    for s in per:
        rows[s] = {"p": [None if not np.isfinite(v) else int(round(v)) for v in dpw[s].to_numpy()],
                   "v": [None if not np.isfinite(v) else int(round(v)) for v in dvw[s].to_numpy()]}
        if per[s].get("t2t"):
            rows[s]["t2t"] = 1
    detail = {"asof": last, "dates": tail, "rows": rows}
    print(f"delivery: {len(per)} stocks with NSE delivery data on {last}; " + ", ".join(f"{k}={len(v)}" for k, v in hits.items()))
    return {"per_stock": per, "detail": detail, "meta": meta, "hits": hits, "metric": metric}
