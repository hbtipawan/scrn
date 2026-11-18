"""Candle chart data for every stock (the Chart button on each stock).

Writes docs/data/sc/_common.json (the session calendar and NIFTY 500 closes, for the RS line) and one small file per
stock, docs/data/sc/<name>.json, with:
  daily   the last DAYS sessions: open, high, low, close, volume
  weekly  the last WEEKS weeks (Monday-Friday, dated by the week's last session): open, high, low, close, volume
  seeds   the state of EMA 21 / 50 / 200 just before the first bar shipped, computed on the stock's FULL price history,
          so the browser continues each EMA exactly as if it had every bar (no warm-up error, nothing approximated)

EMA: seeded with the simple average of the first n closes, then e = e + 2/(n+1) * (close - e) on every bar (the way
TradingView's ta.ema starts). A stock with fewer than n bars has no EMA n yet.
File name: the NSE symbol with every character other than A-Z / 0-9 written as _XX (its hex code), e.g. M&M -> M_26M.
Called from compute.py; never breaks the daily run."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

DAYS = 500                 # about 2 years of daily bars
WEEKS = 160                # about 3 years of weekly bars
EMAS = (21, 50, 200)


def fname(sym):
    return re.sub(r"[^A-Za-z0-9]", lambda m: "_%02X" % ord(m.group(0)), sym)


def ema_state(c, n):
    """state after the closes c (in order): [count, value]; value is the running sum while count < n, then the EMA"""
    k = len(c)
    if k < n:
        return [k, float(np.sum(c)) if k else 0.0]
    e = float(np.mean(c[:n]))
    a = 2.0 / (n + 1)
    for x in c[n:]:
        e += a * (x - e)
    return [k, e]


def ema_full(c, n):
    """EMA n over every close (None before the n-th bar) - used only to check the seeds"""
    out = [None] * len(c)
    if len(c) < n:
        return out
    e = float(np.mean(c[:n]))
    out[n - 1] = e
    a = 2.0 / (n + 1)
    for i in range(n, len(c)):
        e += a * (c[i] - e)
        out[i] = e
    return out


def rd(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 2)


def weekly(d):
    """Monday-Friday weeks from daily bars (DataFrame date/open/high/low/close/volume, sorted); dated by the last session"""
    dt = pd.to_datetime(d["date"])
    wk = (dt - pd.to_timedelta(dt.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    g = d.assign(wk=wk.values).groupby("wk", sort=True)
    return pd.DataFrame({"date": g["date"].last(), "open": g["open"].first(), "high": g["high"].max(),
                         "low": g["low"].min(), "close": g["close"].last(), "volume": g["volume"].sum()}).reset_index(drop=True)


def pack(w, cal_pos):
    return {"t": [cal_pos[x] for x in w["date"]], "o": [rd(x) for x in w.open], "h": [rd(x) for x in w.high],
            "l": [rd(x) for x in w.low], "c": [rd(x) for x in w.close], "v": [int(x) for x in w.volume]}


def build(PFULL, symbols, bench, last, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.json"):
        f.unlink()
    cal_all = sorted(PFULL.loc[PFULL.symbol == bench, "date"].unique()) if (PFULL.symbol == bench).any() \
        else sorted(PFULL["date"].unique())
    cal_all = [d for d in cal_all if d <= last]
    # the calendar shipped: enough sessions for WEEKS weeks
    first_wk = (pd.Timestamp(last) - pd.Timedelta(weeks=WEEKS)).strftime("%Y-%m-%d")
    cal = [d for d in cal_all if d >= first_wk]
    pos = {d: i for i, d in enumerate(cal)}
    dstart = cal[max(0, len(cal) - DAYS)]
    b = PFULL[PFULL.symbol == bench].drop_duplicates("date").set_index("date")["close"].reindex(cal)
    (out_dir / "_common.json").write_text(json.dumps({"asof": last, "d": cal, "b": [rd(x) for x in b], "days": DAYS,
                                                      "weeks": WEEKS, "emas": list(EMAS)}, separators=(",", ":")))
    want = set(symbols)
    P = PFULL[PFULL.symbol.isin(want)][["symbol", "date", "open", "high", "low", "close", "volume"]]
    P = P[P.date <= last].sort_values(["symbol", "date"])
    n_ok, n_short, files, worst = 0, 0, {}, 0.0
    for sym, g in P.groupby("symbol", sort=True):
        d = g.dropna(subset=["open", "high", "low", "close"])
        d = d[(d.close > 0) & (d.low > 0) & (d.high >= d.low)].drop_duplicates("date").reset_index(drop=True)
        d["volume"] = d["volume"].fillna(0).clip(lower=0)
        if len(d) < 2:
            n_short += 1
            continue
        c = d.close.to_numpy(dtype=float)
        k0 = int(np.searchsorted(d.date.to_numpy(), dstart))          # first daily bar shipped
        dd = d.iloc[k0:]
        dd = dd[dd.date.isin(pos)]
        w = weekly(d)
        wc = w.close.to_numpy(dtype=float)
        j0 = int(np.searchsorted(w.date.to_numpy(), cal[0]))            # first weekly bar shipped (its last session in the calendar)
        ww = w.iloc[j0:]
        ww = ww[ww.date.isin(pos)]
        if not len(dd):
            n_short += 1
            continue
        rec = {"s": sym, "d": pack(dd, pos), "w": pack(ww, pos),
               "sd": {str(n): ema_state(c[:k0], n) for n in EMAS},
               "sw": {str(n): ema_state(wc[:j0], n) for n in EMAS}}
        # self-check on a sample: continuing the seed must give the full-history EMA on the last bar
        if n_ok % 97 == 0:
            for n in EMAS:
                full = ema_full(c, n)[-1]
                kk, e = rec["sd"][str(n)]
                for x in c[k0:]:
                    kk += 1
                    if kk < n:
                        e += x
                    elif kk == n:
                        e = (e + x) / n
                    else:
                        e += 2.0 / (n + 1) * (x - e)
                if full is not None:
                    worst = max(worst, abs(e / full - 1))
        f = fname(sym)
        (out_dir / f"{f}.json").write_text(json.dumps(rec, separators=(",", ":"), allow_nan=False))
        files[sym] = f
        n_ok += 1
    size = sum(p.stat().st_size for p in out_dir.glob("*.json"))
    print(f"stock charts: {n_ok} stocks ({n_short} without bars), {size / 1e6:.1f} MB, "
          f"EMA seed check worst error {worst:.1e}")
    if worst > 1e-9:
        raise ValueError(f"EMA seed check failed ({worst})")
    return {"n": n_ok, "asof": last, "mb": round(size / 1e6, 1)}
