"""Ready-made lists (update 20): broad, one-click starting lists for the Scanners tab.

They are lists of stocks in a state (strong RS, big movers, new listings, large and liquid, F&O), not trading signals,
so they are not part of the confluence count. Everything comes from numbers the daily run already has:

  rows    the stocks.json rows of the liquid universe (RS, returns, market cap, turnover, price)
  C, V    daily closes and volumes of the liquid universe (the usual ~2-year window)
  LONG    the full price download (symbol, date, close, volume) since Jul 2020
  fno     set of symbols with stock futures and options on NSE (config/nse/fo_list.csv), may be empty
"""
import numpy as np
import pandas as pd

CAT = "Ready-made lists"


def build(rows, C, V, LONG, fno, asof):
    hits, metric, meta = {}, {}, []
    R = {r["s"]: r for r in rows}
    syms = [s for s in C.columns if s in R]
    c, v = C.iloc[-1], V.iloc[-1]
    d1 = c / C.iloc[-2] - 1

    def col(k):
        return pd.Series({s: R[s].get(k) for s in syms}, dtype=float)

    def ret(p):
        return pd.Series({s: (R[s].get("r") or {}).get(p) for s in syms}, dtype=float)

    def add(id_, name, desc, mask, m_label=None, m_vals=None, m_fmt="num", sort="rs"):
        mask = mask.reindex(syms).fillna(False).astype(bool)
        ss = sorted(mask.index[mask])
        hits[id_] = ss
        if m_label is not None:
            mv = m_vals.reindex(ss)
            metric[id_] = {s: (None if pd.isna(mv[s]) else round(float(mv[s]), 2)) for s in ss}
        meta.append({"id": id_, "name": name, "cat": CAT, "desc": desc, "metric": m_label, "fmt": m_fmt, "sort": sort})

    rs, mc, to, px = col("rs"), col("mc"), col("to"), col("px")
    traded = (v.reindex(syms) > 0)

    # RS 80: strong relative strength above a rising long-term average, big and liquid enough to trade
    n_bars = C[syms].notna().sum()
    e200 = C[syms].ewm(span=200, adjust=False, min_periods=200).mean().iloc[-1]
    e_young = C[syms].ewm(span=200, adjust=False, min_periods=20).mean().iloc[-1]   # new listings: EMA of what exists
    ema_ok = (c[syms] > e200) | ((n_bars < 200) & (c[syms] > e_young))
    add("rs80", "RS 80+ leaders",
        "RS rating 80 or higher, close above the 200-day EMA (new listings: above the EMA of the sessions they have), "
        "market cap ₹500 Cr+, turnover ₹10 Cr+ a day, price ₹10+. New listings are included on their provisional RS.",
        (rs >= 80) & ema_ok & (mc >= 500) & (to >= 10) & (px >= 10) & traded, "RS", rs, "int", "metric")

    r1, r3 = ret("1M"), ret("3M")
    add("gain1m", "1-month gainers (+15%)", "Up 15% or more over the last month (21 sessions).",
        (r1 >= 15) & traded, "1-month %", r1, "pct", "metric")
    add("gain3m", "3-month gainers (+30%)", "Up 30% or more over the last three months (63 sessions).",
        (r3 >= 30) & traded, "3-month %", r3, "pct", "metric")

    # highest volume on record: the full download (since Jul 2020, or since listing)
    L = LONG[LONG.symbol.isin(syms)]
    vmax = L.groupby("symbol")["volume"].max().reindex(syms)
    nlong = L.groupby("symbol")["volume"].count().reindex(syms)
    first = L.groupby("symbol")["date"].min().reindex(syms)
    avg50 = V[syms].iloc[-51:-1].mean()
    add("hve", "Highest volume on record (up day)",
        f"Today's volume is the largest in the whole price history the site holds — since {str(LONG.date.min())[:7]} or "
        "since listing — and the stock closed up. Needs 60+ sessions of history.",
        (v[syms] >= vmax) & (d1[syms] > 0) & (nlong >= 60) & traded, "Vol ×", v[syms] / avg50.replace(0, np.nan), "x", "metric")

    # new listings: first session within the last 365 days (the download starts years earlier, so these are true listings)
    cut = (pd.Timestamp(asof) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    lstart = str(LONG.date.min())
    young = (first >= cut) & (first > lstart)
    f0 = L.sort_values("date").groupby("symbol")["close"].first().reindex(syms)
    since = (c[syms] / f0 - 1) * 100
    add("ipo1y", "New on NSE, last 12 months",
        "First traded on NSE's main board within the last 365 days: IPOs, plus companies that moved over from BSE or "
        "the SME platform. Return is from the first day's close (the IPO price is not in the data).",
        young & traded, "Since 1st close %", since, "pct", "metric")

    # large and liquid: top 100 by market cap among all NSE stocks, turnover ₹50 Cr+ a day
    allmc = pd.Series({r["s"]: r.get("mc") for r in rows}, dtype=float)
    top100 = set(allmc.dropna().sort_values(ascending=False).index[:100])
    add("liq_large", "Liquid large caps",
        "Among the 100 biggest companies by market cap (SEBI's large-cap line) with turnover of ₹50 Cr or more a day.",
        pd.Series({s: s in top100 for s in syms}) & (to >= 50) & traded, "Turnover ₹Cr", to, "num", "metric")

    if fno:
        add("fno", "F&O stocks",
            "Stocks with futures and options on NSE (NSE's market-lot file, refreshed daily).",
            pd.Series({s: s in fno for s in syms}) & traded, "RS", rs, "int", "metric")
    return meta, hits, metric
