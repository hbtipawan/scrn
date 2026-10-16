"""NSE index data for the site (config/nse/idx, from NSE's daily ind_close_all files): official closes and returns,
valuations (P/E, P/B, dividend yield) against their own history, India VIX, and a relative rotation graph (RRG) of
sector and theme indices against NIFTY 500.

Valuation history: NSE switched index P/E, P/B and dividend yield to consolidated earnings and book value on
31 Mar 2021 (Nifty 50 P/E went from 40.4 to 33.2 overnight with the index flat), so a valuation is compared only
with readings since that date — older readings are on a different basis.

RRG: Julius de Kempenaer's RS-Ratio and RS-Momentum formulas are not published; this is a smoothed approximation on
weekly closes: RS = 100 x index / NIFTY 500; RS-Ratio = 100 x (10-week EMA of RS) / (30-week EMA of RS), i.e. where
relative strength sits against its own trend; RS-Momentum = 100 x RS-Ratio / (10-week EMA of RS-Ratio), i.e.
whether that is still rising. Above 100 on both = leading; ratio above / momentum below = weakening; both below =
lagging; ratio below / momentum above = improving, so indices move clockwise. (A z-score version, as in several
open-source RRG tools, jumps around too much week to week to read.)
"""
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IDX = ROOT / "config" / "nse" / "idx"
BASIS = "2021-03-31"           # first day of consolidated-earnings valuations
BENCH = "Nifty 500"
SHORT, LONG = 10, 30           # weeks (RRG)
TAIL = 10                      # weeks of tail shown on the RRG

BROAD = ["Nifty 50", "Nifty Next 50", "Nifty 100", "Nifty 500", "Nifty Midcap 150", "Nifty Smallcap 250",
         "Nifty Microcap 250", "Nifty Total Market", "Nifty MidSmallcap 400"]
SECTORS = ["Nifty Auto", "Nifty Bank", "Nifty Cement", "Nifty Chemicals", "Nifty Consumer Durables",
           "Nifty Financial Services", "Nifty FMCG", "Nifty Healthcare Index", "Nifty IT", "Nifty Media",
           "Nifty Metal", "Nifty Oil & Gas", "Nifty Pharma", "Nifty Private Bank", "Nifty PSU Bank", "Nifty Realty"]
THEMES = ["Nifty Capital Markets", "Nifty Capital Goods", "Nifty Commodities", "Nifty Construction", "Nifty CPSE",
          "Nifty Energy", "Nifty EV & New Age Automotive", "Nifty Housing", "Nifty India Consumption",
          "Nifty India Defence", "Nifty India Digital", "Nifty India Manufacturing", "Nifty India Railways PSU",
          "Nifty India Tourism", "Nifty Infrastructure", "Nifty Insurance", "Nifty MNC", "Nifty NBFC", "Nifty Power",
          "Nifty PSE", "Nifty Hospitals", "Nifty Retail", "Nifty Rural", "Nifty Services Sector",
          "Nifty Telecommunications", "Nifty Transportation & Logistics"]
SIZE = ["Nifty 50", "Nifty Next 50", "Nifty Midcap 150", "Nifty Smallcap 250", "Nifty Microcap 250"]
PE_HIST = ["Nifty 50", "Nifty 500", "Nifty Midcap 150", "Nifty Smallcap 250"]
PERIODS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}


def load(asof=None):
    files = sorted(glob.glob(str(IDX / "*.csv.gz")))
    if not files:
        return None
    I = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    I = I.drop_duplicates(["date", "index"], keep="last")
    if asof:
        I = I[I.date <= asof]
    return I


def r1(v, nd=1):
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


def pctile(series, now):
    """Share of readings (since BASIS) below today's value, 0–100."""
    s = series.dropna()
    if len(s) < 250 or not np.isfinite(now):
        return None
    return round(float((s < now).mean() * 100))


def rrg(close, names, bench):
    """Weekly RS-Ratio / RS-Momentum tails for the given indices."""
    wk = close.copy()
    wk.index = pd.to_datetime(wk.index)
    wk = wk.groupby(wk.index.to_period("W")).last()
    out = []
    # week label = the last trading day of that week
    last_day = close.copy()
    last_day.index = pd.to_datetime(last_day.index)
    lab = last_day.groupby(last_day.index.to_period("W")).apply(lambda x: x.index.max().strftime("%Y-%m-%d"))
    dates = list(lab.iloc[-TAIL:])
    b = wk[bench]
    for n in names:
        if n not in wk:
            continue
        rs = (100 * wk[n] / b).dropna()          # from the index's first week
        if len(rs) < LONG + TAIL + 5 or rs.index[-1] != wk.index[-1]:   # averages need time to settle
            continue
        # relative trend: the 10-week average of RS against its 30-week average (above 100 = RS above its trend)
        rsr = 100 * rs.ewm(span=SHORT, adjust=False).mean() / rs.ewm(span=LONG, adjust=False).mean()
        # momentum of that trend: RS-Ratio against its own 10-week average (above 100 = still rising)
        rsm = 100 * rsr / rsr.ewm(span=SHORT, adjust=False).mean()
        pts = [[r1(a, 2), r1(m, 2)] for a, m in zip(rsr.iloc[-TAIL:], rsm.iloc[-TAIL:])]
        if any(p[0] is None or p[1] is None for p in pts):
            continue
        x, y = pts[-1]
        q = "leading" if x >= 100 and y >= 100 else "weakening" if x >= 100 else "lagging" if y < 100 else "improving"
        out.append({"n": n, "p": pts, "q": q})
    return {"bench": bench, "weeks": dates, "short": SHORT, "long": LONG, "series": out}


def build(asof):
    I = load(asof)
    if I is None or I.empty:
        return None
    last = I.date.max()
    close = I.pivot_table(index="date", columns="index", values="close", aggfunc="last").sort_index()
    val = {k: I.pivot_table(index="date", columns="index", values=k, aggfunc="last").sort_index() for k in ("pe", "pb", "dy")}
    rows = []
    for grp, names in (("Broad market", BROAD), ("Sector", SECTORS), ("Theme", THEMES)):
        for n in names:
            if n not in close or pd.isna(close[n].iloc[-1]):
                continue
            c = close[n].dropna()
            r = {k: r1((c.iloc[-1] / c.iloc[-1 - p] - 1) * 100, 2) if len(c) > p else None for k, p in PERIODS.items()}
            ytd = c[c.index < f"{last[:4]}-01-01"]
            r["YTD"] = r1((c.iloc[-1] / ytd.iloc[-1] - 1) * 100, 2) if len(ytd) else None
            row = {"n": n, "g": grp, "px": r1(c.iloc[-1], 2), "r": r}
            for k in ("pe", "pb", "dy"):
                if n not in val[k]:                  # never published for this index
                    row[k] = None
                    if k != "dy":
                        row[k + "_p"] = row[k + "_m"] = None
                    continue
                s = val[k][n]
                now = s.dropna().iloc[-1] if s.notna().any() else np.nan
                row[k] = r1(now, 2)
                if k != "dy":
                    h = s[s.index >= BASIS]
                    row[k + "_p"] = pctile(h, now)
                    row[k + "_m"] = r1(h.median(), 2) if h.notna().sum() >= 250 else None
            rows.append(row)
    # India VIX: level, change, where it sits in its last year
    vix = None
    if "India VIX" in close:
        v = close["India VIX"].dropna()
        y = v.iloc[-252:]
        vix = {"v": r1(v.iloc[-1], 2), "d1": r1((v.iloc[-1] / v.iloc[-2] - 1) * 100, 1), "lo": r1(y.min(), 2),
               "hi": r1(y.max(), 2), "p1y": round(float((y < v.iloc[-1]).mean() * 100)), "med": r1(y.median(), 2),
               "hist": [r1(x, 2) for x in v.iloc[-260:]], "dates": list(v.index[-260:])}
    # P/E history (weekly, since the consolidated basis) for the main indices
    pe_hist = {}
    pe = val["pe"][val["pe"].index >= BASIS]
    wk = pe.copy()
    wk.index = pd.to_datetime(wk.index)
    wk = wk.groupby(wk.index.to_period("W")).last()
    wdates = [str(p.start_time.date()) for p in wk.index]
    for n in PE_HIST:
        if n in wk:
            pe_hist[n] = [r1(x, 2) for x in wk[n]]
    R = {"sector": rrg(close, SECTORS, BENCH), "theme": rrg(close, THEMES, BENCH), "size": rrg(close, SIZE, BENCH)} \
        if BENCH in close else None
    print(f"indices: {len(rows)} with valuations to {last}; VIX {vix['v'] if vix else '–'}; RRG "
          + (", ".join(f"{k} {len(v['series'])}" for k, v in R.items()) if R else "–"))
    return {"asof": last, "basis": BASIS, "rows": rows, "vix": vix,
            "pe_hist": {"weeks": wdates, "series": pe_hist}, "rrg": R}
