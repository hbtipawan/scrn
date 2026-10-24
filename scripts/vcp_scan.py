"""VCP scanner (Scanners -> VCP scanner): the data the browser needs to run the scanner live.

The scanner itself is docs/vcp-engine.js, an exact JavaScript port of vcp_core.analyze_vcp from the VCP breakout
scanner in github.com/hbtipawan/VCP-REVERSAL (the reversal scanner is not used). It runs in the browser so every
setting of the original app works instantly. Checked bar by bar against the original Python: identical results.

This module sends, for every stock that traded on the last session and could pass the scanner under SOME setting:
  daily bars   the last 260 sessions (the scanner reads at most 257: a 252-session high/low window + 5)
  weekly bars  the last 80 weeks (the high-tight-flag search reads 77), built like the app: daily -> W-FRI -> clean
  chart closes 140 older daily closes / 40 older weekly closes, only so the chart can draw its long moving averages
and the Nifty 50 momentum return the scanner's relative strength subtracts (126 sessions / 26 weeks).

"Could pass under some setting" is a superset of every slider position: the loosest trend gate (Strict or Relaxed,
Standard is inside Relaxed) and within 40% of the 52-period high (the slider's maximum), OR a day that the loosest
episodic-pivot settings could flag, OR a recent listing (too short for the full windows; scanned only when the user
ticks "Include recent listings"). Small tolerances keep a stock on the list when a test is a tie.

Prices are sent as whole paise and volumes as whole shares, so the browser rebuilds exactly the numbers in the data.
"""
import numpy as np
import pandas as pd

DAILY_BARS, WEEKLY_BARS = 260, 80
CHART_EXTRA_D, CHART_EXTRA_W = 140, 40
NIFTY = "NIFTY 50"
EPS = 1e-9


def clean_df(df):
    """screener_core.clean_df from the VCP app, unchanged: last bar per date, positive OHLC, high/low clamped to
    open/close, no bar wider than 50% of its close (a data error, beyond any NSE circuit band)."""
    if df is None or not len(df):
        return df
    d = df.drop_duplicates(subset="date", keep="last").copy()
    for col in ("open", "high", "low", "close"):
        d = d[d[col] > 0]
    if not len(d):
        return None
    d["high"] = d[["high", "open", "close"]].max(axis=1)
    d["low"] = d[["low", "open", "close"]].min(axis=1)
    d = d[(d["high"] - d["low"]) <= 0.50 * d["close"]]
    return d.reset_index(drop=True) if len(d) else None


def to_weekly(df):
    """upstox_data.to_weekly from the VCP app, unchanged (weeks end on Friday; the last week may be in progress)."""
    if df is None or df.empty:
        return df
    s = df.set_index("date").sort_index()
    w = s.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"}).dropna(subset=["close"])
    return w.reset_index()


def _could_pass(d, weekly):
    """True when some slider position could let the scanner keep this stock on its last bar."""
    n = len(d)
    maf_n, mam_n, mal_n, win = (10, 30, 40, 52) if weekly else (50, 150, 200, 252)
    if n < max(mal_n, win) + 5:
        return n >= (40 if weekly else 60)             # recent listing: scanned with "Include recent listings"
    c = d["close"]
    maf, mam, mal = (c.rolling(k).mean().to_numpy() for k in (maf_n, mam_n, mal_n))
    i = n - 1
    C = float(c.iloc[i])
    if not (np.isfinite(maf[i]) and np.isfinite(mam[i]) and np.isfinite(mal[i])) or C <= 0:
        return False
    lo = 1 - EPS
    strict = C > maf[i] * lo and maf[i] > mam[i] * lo and mam[i] > mal[i] * lo and mal[i] > mal[i - 20] * lo
    relaxed = C > mam[i] * lo and maf[i] > mam[i] * lo and maf[i] > maf[i - 10] * lo
    hi52 = float(d["high"].iloc[i - win + 1:i + 1].max())
    near = hi52 > 0 and (hi52 - C) / hi52 <= 0.40 + EPS
    if (strict or relaxed) and near:
        return True
    # episodic pivot (bypasses the trend and near-high gates): loosest slider positions, 4% day on 1.5x volume
    v = d["volume"].to_numpy(float)
    v50 = float(pd.Series(v).rolling(50).mean().iloc[i])
    pc = float(c.iloc[i - 1])
    return pc > 0 and np.isfinite(v50) and v50 > 0 and C / pc - 1 >= 0.04 - EPS and v[i] / v50 >= 1.5 - EPS


def _paise(x):
    return np.rint(np.asarray(x, dtype=float) * 100).astype(np.int64)


def _enc(d, pos, extra):
    """bars -> compact integer lists: first calendar slot, missing slots, close as differences, open/high/low as
    offsets from the close (all in paise), volume in shares; `extra` = older closes for the chart's averages."""
    p = [pos[x] for x in d["date"]]
    gaps = sorted(set(range(p[0], p[-1] + 1)) - set(p))
    c = _paise(d["close"])
    out = {"k": int(p[0]), "c": np.diff(c, prepend=0).tolist(), "o": (_paise(d["open"]) - c).tolist(),
           "h": (_paise(d["high"]) - c).tolist(), "l": (_paise(d["low"]) - c).tolist(),
           "v": np.rint(d["volume"].to_numpy(float)).astype(np.int64).tolist()}
    if gaps:
        out["x"] = [int(g) for g in gaps]
    if len(extra):
        out["pc"] = np.diff(_paise(extra), prepend=0).tolist()
    return out


def _mom(close, n):
    c = np.asarray(close, dtype=float)
    return float(c[-1] / c[-1 - n] - 1) if len(c) >= n + 2 else 0.0      # vcp_core.nifty_mom


def _clean_all(d):
    """clean_df applied to every stock at once (same rules, same order)"""
    d = d.drop_duplicates(subset=["symbol", "date"], keep="last")
    d = d[(d["open"] > 0) & (d["high"] > 0) & (d["low"] > 0) & (d["close"] > 0)].copy()
    d["high"] = d[["high", "open", "close"]].max(axis=1)
    d["low"] = d[["low", "open", "close"]].min(axis=1)
    return d[(d["high"] - d["low"]) <= 0.50 * d["close"]]


def _weekly_all(d):
    """to_weekly for every stock at once: the W-FRI bin of a date is the Friday on or after it"""
    dt = pd.to_datetime(d["date"])
    lab = (dt + pd.to_timedelta((4 - dt.dt.weekday) % 7, unit="D")).dt.strftime("%Y-%m-%d")
    w = d.assign(date=lab).groupby(["symbol", "date"], sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
    return w.dropna(subset=["close"]).reset_index()


def _split(d):
    """{symbol: frame} without a per-stock groupby (rows are sorted by symbol, then date)"""
    sy = d["symbol"].to_numpy()
    cut = np.flatnonzero(sy[1:] != sy[:-1]) + 1
    starts, ends = np.r_[0, cut], np.r_[cut, len(sy)]
    return {sy[a]: d.iloc[a:b].reset_index(drop=True) for a, b in zip(starts, ends)}


def build(PFULL, A, U, last, evidence=None):
    uset = set(U)
    P = PFULL[PFULL.symbol.isin(set(A) | {NIFTY})][["symbol", "date", "open", "high", "low", "close", "volume"]]
    P = P.sort_values(["symbol", "date"], kind="mergesort").reset_index(drop=True)
    allcal = sorted(PFULL["date"].unique())
    dpos = {x: k for k, x in enumerate(allcal)}
    nif = P[P.symbol == NIFTY].assign(date=lambda x: pd.to_datetime(x["date"]))
    n50 = {"d": _mom(nif["close"], 126), "w": _mom(to_weekly(nif)["close"], 26)} if len(nif) else {"d": 0.0, "w": 0.0}
    P = P[P.symbol != NIFTY]
    live = set(P.loc[P["date"] == last, "symbol"])          # no bar on the last session: its signal would be stale
    P = P[P.symbol.isin(live)]
    DL = _split(_clean_all(P))                               # app: clean_df(daily)
    WK = _split(_clean_all(_weekly_all(P)))                  # app: clean_df(to_weekly(daily))
    rows, wk_rows, scanned = [], {}, {"d": [0, 0], "w": [0, 0]}
    for sym in sorted(live):
        row = {"s": sym}
        dly = DL.get(sym)
        if dly is not None and len(dly) >= 60 and dly["date"].iloc[-1] == last:
            scanned["d"][0] += 1
            scanned["d"][1] += sym in uset
            d = dly.iloc[-DAILY_BARS:]
            if _could_pass(d, False):
                ex = dly["close"].iloc[max(0, len(dly) - DAILY_BARS - CHART_EXTRA_D):max(0, len(dly) - DAILY_BARS)]
                row["d"] = _enc(d, dpos, ex)
        wkl = WK.get(sym)
        if wkl is not None and len(wkl) >= 40:
            scanned["w"][0] += 1
            scanned["w"][1] += sym in uset
            w = wkl.iloc[-WEEKLY_BARS:]
            if _could_pass(w, True):
                ex = wkl["close"].iloc[max(0, len(wkl) - WEEKLY_BARS - CHART_EXTRA_W):max(0, len(wkl) - WEEKLY_BARS)]
                wk_rows[sym] = (w, ex)
        if "d" in row or sym in wk_rows:
            rows.append(row)
    # daily calendar: from the earliest exported bar (a stock with missing sessions reaches further back)
    k0 = min((r["d"]["k"] for r in rows if "d" in r), default=len(allcal) - 1)
    for r in rows:
        if "d" in r:
            r["d"]["k"] -= k0
            if "x" in r["d"]:
                r["d"]["x"] = [g - k0 for g in r["d"]["x"]]
    cal = allcal[k0:]
    wcal = sorted({x for w, _ in wk_rows.values() for x in w["date"]})
    wpos = {x: k for k, x in enumerate(wcal)}
    weekly = []
    for row in rows:
        if row["s"] in wk_rows:
            w, ex = wk_rows[row["s"]]
            weekly.append(dict(s=row["s"], **_enc(w, wpos, ex)))
    daily = [dict(s=r["s"], **r["d"]) for r in rows if "d" in r]
    head = {"asof": last, "n50": n50, "scanned": scanned, "sent": {"d": len(daily), "w": len(weekly)}}
    out_d = dict(head, cal=cal, rows=daily)
    if evidence:
        out_d["evidence"] = evidence
    out_w = dict(head, cal=wcal, rows=weekly)
    print(f"vcp: {scanned['d'][0]} stocks scanned daily, {scanned['w'][0]} weekly; sent {len(daily)} daily and "
          f"{len(weekly)} weekly candidates (every setting is applied in the browser); "
          f"Nifty 50 momentum {n50['d'] * 100:.1f}% (126 sessions), {n50['w'] * 100:.1f}% (26 weeks)")
    return out_d, out_w
