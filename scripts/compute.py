"""Turn cache/prices.csv.gz into the small JSON files the website reads.

Writes docs/data/:
  meta.json     date, source, universe counts
  stocks.json   one row per stock: returns for every period (now and 1 week ago),
                RS rating, 52W distance, DMA flags, trend template, stage, turnover, volume ratio
  groups.json   membership lists for Themes / Sectors / NSE Indices
  breadth.json  daily market-breadth history
  scans.json    today's scanner hits

Theme/sector averages are computed in the browser from stocks.json, so every
period x grouping x (mean/median) combination is available without extra files.

Run:  python scripts/compute.py
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import scanners as SC

ROOT = Path(__file__).resolve().parents[1]
CACHE, CFG, OUT = ROOT / "cache", ROOT / "config", ROOT / "docs" / "data"
S = json.loads((CFG / "settings.json").read_text())
PERIODS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252}
LAG = 5  # "1 week ago" snapshot for rank-change arrows


def r2(x, nd=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return None
    return round(float(x), nd)


LONG = None  # full download (about 6 years) for the long-base identifier
PFULL = None  # the same with open/high/low, for the group charts (group_index.py)


def load():
    global LONG
    p = pd.read_csv(CACHE / "prices.csv.gz", dtype={"symbol": str, "date": str})
    u = pd.read_csv(CACHE / "universe.csv", dtype={"symbol": str})
    # a date on which only a handful of stocks have a bar is not an NSE session (e.g. 66 stray bars on Saturday
    # 26 Apr 2025, a day NSE was shut): drop it everywhere
    cnt = p.groupby("date").size()
    stray = set(cnt.index[cnt < 0.2 * cnt.median()])
    if stray:
        p = p[~p.date.isin(stray)]
        print(f"dropped {len(stray)} non-session date(s): {', '.join(sorted(stray)[:5])}")
    LONG = p[["symbol", "date", "close", "volume"]]
    global PFULL
    bcal_full = set(p.loc[p.symbol == S["benchmark"], "date"])
    PFULL = p[p.date.isin(bcal_full)] if bcal_full else p             # full OHLC history for the group charts
    # everything except bases.py works on the usual window, exactly as before the longer download
    cut = (datetime.now(timezone(timedelta(hours=5, minutes=30))).date() - timedelta(days=S["history_calendar_days"])).isoformat()
    p = p[p.date >= cut]
    bench = S["benchmark"]
    cal = sorted(p.loc[p.symbol == bench, "date"].unique()) or sorted(p.date.unique())
    # Use the benchmark's trading calendar; drop stray non-session dates.
    p = p[p.date.isin(set(cal))]
    wide = {f: p.pivot_table(index="date", columns="symbol", values=f, aggfunc="last").reindex(cal)
            for f in ["open", "high", "low", "close", "volume"]}
    return wide, u


def period_return(C, n, end=-1):
    """Return over n sessions ending at row `end` (negative index)."""
    if len(C) < n + 1 - end:
        return pd.Series(np.nan, index=C.columns)
    return C.iloc[end] / C.iloc[end - n] - 1


def ytd_return(C, end=-1):
    d = C.index[end]
    prev = C.index[C.index < f"{d[:4]}-01-01"]
    if not len(prev):
        return pd.Series(np.nan, index=C.columns)
    return C.iloc[end] / C.loc[prev[-1]] - 1


def rs_score(C, end=-1):
    """IBD-style: 40% weight on last quarter, 20% each on the three before."""
    parts, w = [], [0.4, 0.2, 0.2, 0.2]
    for n in (63, 126, 189, 252):
        parts.append(period_return(C, n, end) + 1)
    sc = sum(wi * pi for wi, pi in zip(w, parts))
    # Young listings (<1y): use what exists, renormalised.
    avail = sum(wi * pi.notna() for wi, pi in zip(w, parts))
    part_sum = sum(wi * pi.fillna(0) for wi, pi in zip(w, parts))
    sc = sc.fillna(part_sum / avail.replace(0, np.nan))
    return sc


def nse_mcap(asof):
    """Official NSE market cap (Rs crore) per symbol from the daily PR bundle (mcapDDMMYYYY.csv).

    Display only - it does not filter the universe. Tries the as-of date and four days before;
    if NSE can't be reached, the last saved copy (config/mcap_nse.csv) is used.
    """
    import io
    import zipfile
    import requests
    saved = CFG / "mcap_nse.csv"
    d0 = datetime.strptime(asof, "%Y-%m-%d").date()
    for back in range(5):
        d = d0 - timedelta(days=back)
        url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{d:%d%m%y}.zip"
        try:
            r = None
            for _ in range(3):
                try:
                    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
                    break
                except requests.RequestException:
                    continue
            if r is None or r.status_code != 200 or r.content[:2] != b"PK":
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            name = next(n for n in z.namelist() if n.lower().startswith("mcap"))
            m = pd.read_csv(z.open(name))
            m.columns = [c.strip() for c in m.columns]
            m["Symbol"], m["Series"] = m["Symbol"].str.strip(), m["Series"].str.strip()
            m = m[m["Series"].isin(S["include_series"])]
            close_col = next(c for c in m.columns if c.startswith("Close Price"))
            out = pd.DataFrame({"Symbol": m["Symbol"], "MarketCapCr": (m["Market Cap(Rs.)"] / 1e7).round(2),
                                "Close": m[close_col], "Date": d.isoformat()}).drop_duplicates("Symbol")
            out.to_csv(saved, index=False)
            print(f"NSE market cap: {len(out)} symbols for {d}")
            return out.set_index("Symbol")
        except Exception as e:  # network or format problem - try an earlier day
            print(f"  mcap {d}: {type(e).__name__}")
    if saved.exists():
        print("NSE market cap: using saved copy")
        return pd.read_csv(saved).set_index("Symbol")
    return None


def pct_rank(s):
    return (s.rank(pct=True) * 98 + 1).round()


def rank_vs(sc, U):
    """RS rating 1–99. Stocks in the liquid universe U are ranked among themselves exactly as before; every other
    stock is placed where its score would fall among them (so a rating means the same thing for both)."""
    out = pct_rank(sc.reindex(U)).reindex(sc.index)
    ref = np.sort(sc.reindex(U).dropna().to_numpy())
    other = sc.index.difference(pd.Index(U))
    v = sc.reindex(other).dropna()
    if len(ref) and len(v):
        lo, hi = np.searchsorted(ref, v.to_numpy(), "left"), np.searchsorted(ref, v.to_numpy(), "right")
        out[v.index] = np.round(np.clip((lo + hi) / 2 / len(ref), 1 / len(ref), 1) * 98 + 1)
    return out


def breadth_frame(C, raw, sma, idx_from):
    """Daily breadth of the stocks in C (columns). A stock counts on a day only if it traded that day."""
    valid = raw.notna()
    dchg = C.pct_change(fill_method=None)
    hiC = C.rolling(252, min_periods=200).max()
    loC = C.rolling(252, min_periods=200).min()

    def pct(mask, base):
        return mask.sum(axis=1) / base.sum(axis=1).replace(0, np.nan) * 100
    adv, dec = ((dchg > 0) & valid).sum(axis=1), ((dchg < 0) & valid).sum(axis=1)
    # McClellan oscillator, ratio-adjusted (net advances per 1,000 issues, so a growing list of stocks
    # does not inflate it): 10% trend (19-day EMA) minus 5% trend (39-day EMA)
    rana = ((adv - dec) / (adv + dec).replace(0, np.nan) * 1000).fillna(0)
    mco = rana.ewm(alpha=0.10, adjust=False).mean() - rana.ewm(alpha=0.05, adjust=False).mean()
    b = pd.DataFrame({
        "a20": pct((C > sma[20]) & valid, sma[20].notna() & valid),
        "a50": pct((C > sma[50]) & valid, sma[50].notna() & valid),
        "a200": pct((C > sma[200]) & valid, sma[200].notna() & valid),
        "adv": adv, "dec": dec, "n": valid.sum(axis=1),
        "nh": ((C >= hiC) & hiC.notna() & valid).sum(axis=1),
        "nl": ((C <= loC) & loC.notna() & valid).sum(axis=1),
        "up4": ((dchg >= 0.04) & valid).sum(axis=1), "dn4": ((dchg <= -0.04) & valid).sum(axis=1),
        "mco": mco,
    }).iloc[idx_from:]
    b["adl"] = (b.adv - b.dec).cumsum()            # advance/decline line over the window shown
    out = {}
    for col in b.columns:
        out[col] = [r2(x, 1) for x in b[col]] if col in ("a20", "a50", "a200", "mco") else [int(x) for x in b[col]]
    return out, b.index


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    W, u = load()
    bench = S["benchmark"]
    stocks = u[u.kind == "stock"].set_index("symbol")
    syms = [s for s in stocks.index if s in W["close"].columns]
    C = W["close"][syms].ffill(limit=3)
    H, L, V = W["high"][syms], W["low"][syms], W["volume"][syms].fillna(0)
    raw_close = W["close"][syms]
    dates = C.index
    last = dates[-1]

    # ---------------- universe filter (as of today)
    bars = raw_close.notna().sum()
    turnover = (raw_close * V / 1e7)  # Rs crore
    med_to = turnover.iloc[-50:].median()
    traded_recently = raw_close.iloc[-3:].notna().any()
    keep = (C.iloc[-1] >= S["min_price"]) & (med_to >= S["min_median_turnover_cr"]) \
        & (bars >= S["min_bars"]) & traded_recently
    # Optional industry + market cap from BSE (made on your PC by pc_bse_industry.py)
    ind = pd.Series(dtype=str)
    mcap = None
    bse = CFG / "industry_bse.csv"
    if bse.exists() and "isin" in stocks.columns:
        b = pd.read_csv(bse).drop_duplicates("ISIN").set_index("ISIN")
        isin = stocks["isin"].reindex(syms)
        ind = isin.map(b["Industry"]).dropna()
        mc = isin.map(b["MarketCapCr"])
        if mc.notna().sum() > 0.5 * len(syms):
            mcap = mc
    mcap_file = CFG / "mcap.csv"  # optional manual override: Symbol,MarketCapCr
    if mcap_file.exists():
        mcap = pd.read_csv(mcap_file).set_index("Symbol")["MarketCapCr"]
    if mcap is not None:
        # stocks missing from the file are kept (new listings), only known small caps are dropped
        keep &= mcap.reindex(C.columns).fillna(1e12) >= S["min_market_cap_cr"]
    U = [s for s in syms if keep.get(s, False)]
    # every stock trading now (no price, turnover or market-cap filter): breadth and sector rotation use these
    A = [s for s in syms if traded_recently.get(s, False)]
    uset = set(U)
    print(f"{len(syms)} stocks with data -> {len(U)} pass the liquidity filters, {len(A)} traded in the last 3 sessions "
          f"(as of {last})")

    Cu, Hu, Lu, Vu = C[U], H[U], L[U], V[U]
    Ou = W["open"][syms][U].fillna(C[U])
    Ca = C[A]

    # ---------------- indicators (every stock; the liquid universe uses the same numbers)
    sma_all = {n: C.rolling(n, min_periods=n).mean() for n in (20, 50, 150, 200)}
    sma = {n: v[U] for n, v in sma_all.items()}
    sma_a = {n: v[A] for n, v in sma_all.items()}
    ema20, ema50 = SC.ema(Cu, 20), SC.ema(Cu, 50)
    hi52_a = H[A].rolling(252, min_periods=60).max()
    lo52_a = L[A].rolling(252, min_periods=60).min()
    hi52, lo52 = hi52_a[U], lo52_a[U]
    avgv50_a = V[A].rolling(50, min_periods=20).mean().shift(1)
    avgv50 = avgv50_a[U]

    rets = {k: (ytd_return(Ca) if n is None else period_return(Ca, n)) for k, n in PERIODS.items()}
    rets_prev = {k: (ytd_return(Ca, -1 - LAG) if n is None else period_return(Ca, n, -1 - LAG))
                 for k, n in PERIODS.items()}
    rs_all, rs_prev_all = rank_vs(rs_score(Ca), U), rank_vs(rs_score(Ca, -1 - LAG), U)
    rs_now, rs_prev = rs_all.reindex(U), rs_prev_all.reindex(U)

    sma200_up = sma_a[200].iloc[-1] > sma_a[200].iloc[-22]
    slope150 = sma_a[150].iloc[-1] / sma_a[150].iloc[-21] - 1
    c_all = Ca.iloc[-1]
    tt_all = ((c_all > sma_a[150].iloc[-1]) & (c_all > sma_a[200].iloc[-1]) & (sma_a[150].iloc[-1] > sma_a[200].iloc[-1])
              & sma200_up & (sma_a[50].iloc[-1] > sma_a[150].iloc[-1]) & (sma_a[50].iloc[-1] > sma_a[200].iloc[-1])
              & (c_all > sma_a[50].iloc[-1]) & (c_all >= 1.3 * lo52_a.iloc[-1]) & (c_all >= 0.75 * hi52_a.iloc[-1])
              & (rs_all >= 70))
    c, tt = c_all.reindex(U), tt_all.reindex(U)

    def stage(s):
        sl, px, m = slope150.get(s), c_all.get(s), sma_a[150].iloc[-1].get(s)
        if pd.isna(sl) or pd.isna(m):
            return None
        if px > m and sl > 0.01:
            return 2
        if px < m and sl < -0.01:
            return 4
        return 3 if px >= m else 1

    # sectors / names
    sec = pd.read_csv(CFG / "sectors.csv").set_index("Symbol")["Sector"] if (CFG / "sectors.csv").exists() else pd.Series(dtype=str)
    # industry for every stock (Yahoo's classification, NSE's where Yahoo has none; fund_info.csv from fetch_fundamentals.py)
    info_f = CFG / "fund_info.csv"
    if not len(ind) and info_f.exists():
        fi = pd.read_csv(info_f, dtype={"symbol": str}).set_index("symbol")
        ind = fi["industry"].fillna(fi.get("nse_industry")).dropna()
        ind = ind[ind.map(lambda x: isinstance(x, str))]
    # NSE's sector lists cover only the ~750 stocks of its broad indices. Every other stock gets the NSE sector that
    # its industry falls in among the stocks where both are known (only when 60%+ of them agree, from 3+ stocks).
    sec_x = pd.Series(dtype=str)
    sec_check = None
    if len(sec) and len(ind):
        both = pd.DataFrame({"i": ind, "s": sec}).dropna()
        votes = both.groupby("i")["s"].agg(lambda x: (x.value_counts().index[0], x.value_counts().iloc[0] / len(x), len(x)))
        mp = {i: v[0] for i, v in votes.items() if v[1] >= 0.6 and v[2] >= 3}
        sec_x = pd.Series({s: mp[ind[s]] for s in A if s not in sec.index and ind.get(s) in mp})
        agree = (both["i"].map(mp) == both["s"])[both["i"].isin(mp)]
        sec_check = {"derived": len(sec_x), "agree": r2(agree.mean() * 100, 1), "tested": int(len(agree))}
        print(f"sectors: {int(sec.index.isin(A).sum())} from NSE lists, {len(sec_x)} from their industry "
              f"(industry → sector agrees for {sec_check['agree']}% of {sec_check['tested']} stocks with both)")
    sec_all = pd.concat([sec, sec_x])

    rows = []
    vr_a = V[A].iloc[-1] / avgv50_a.iloc[-1]
    vr = vr_a.reindex(U)
    if mcap is not None:
        mc_show = mcap
    else:
        # NSE figure, rolled forward to today's close if the file is from an earlier day
        m = nse_mcap(last)
        mc_show = pd.Series(dtype=float) if m is None else \
            (m["MarketCapCr"] * (c_all.reindex(m.index) / m["Close"]).fillna(1.0)).dropna()
    for s in A:
        row = {
            "s": s, "n": str(stocks.loc[s, "name"])[:40], "sec": sec_all.get(s), "ind": ind.get(s),
            "px": r2(c_all[s]), "r": {k: r2(v[s] * 100) for k, v in rets.items()},
            "rp": {k: r2(v[s] * 100) for k, v in rets_prev.items()},
            "rs": None if pd.isna(rs_all[s]) else int(rs_all[s]),
            "rs1w": None if pd.isna(rs_prev_all.get(s)) else int(rs_prev_all[s]),
            "h52": r2((c_all[s] / hi52_a.iloc[-1][s] - 1) * 100, 1),
            "l52": r2((c_all[s] / lo52_a.iloc[-1][s] - 1) * 100, 1),
            "a20": bool(c_all[s] > sma_a[20].iloc[-1][s]) if pd.notna(sma_a[20].iloc[-1][s]) else None,
            "a50": bool(c_all[s] > sma_a[50].iloc[-1][s]) if pd.notna(sma_a[50].iloc[-1][s]) else None,
            "a200": bool(c_all[s] > sma_a[200].iloc[-1][s]) if pd.notna(sma_a[200].iloc[-1][s]) else None,
            "tt": bool(tt_all[s]), "st": stage(s),
            "to": r2(med_to[s], 1), "vr": r2(vr_a[s], 1),
            "mc": r2(mc_show.get(s), 0),
        }
        if s not in uset:
            row["lq"] = 0                       # outside the liquid universe: breadth and rotation only
        if s in sec_x.index:
            row["secx"] = 1                     # sector taken from the industry, not an NSE list
        rows.append(row)

    # ---------------- groups (membership only; maths happens in the browser) — every trading stock;
    # the site can narrow any group to the liquid universe
    aset = set(A)

    def load_groups(path, key):
        if not path.exists():
            return {}
        g = pd.read_csv(path)
        return {r[key]: [x for x in str(r["Symbols"]).split() if x in aset] for _, r in g.iterrows()}

    groups = {
        "Themes": load_groups(CFG / "themes.csv", "Theme"),
        "Sector": {k: [s for s in sec_all.index[sec_all == k] if s in aset] for k in sorted(sec_all.dropna().unique())},
        "NSE Index": load_groups(CFG / "indices.csv", "Index"),
    }
    if len(ind):
        ia = ind[ind.index.isin(aset)]
        groups["Industry"] = {k: list(ia.index[ia == k]) for k in sorted(ia.unique())}

    # ---------------- breadth history: every stock with prices (no liquidity filter), and the liquid universe
    nb = S["breadth_history_days"]
    breadth, bidx = breadth_frame(C, raw_close, sma_all, -nb)
    lq, _ = breadth_frame(Cu, raw_close[U], sma, -nb)
    bench_close = W["close"][bench].reindex(bidx) if bench in W["close"] else pd.Series(np.nan, index=bidx)
    breadth.update({"dates": list(bidx), "bench": [r2(x) for x in bench_close], "bench_name": bench, "lq": lq,
                    "universe": {"all": len(A), "lq": len(U)}})

    indices = {}
    for name in [bench] + S["extra_indices"]:
        if name in W["close"]:
            ci = W["close"][name].ffill()
            indices[name] = {"px": r2(ci.iloc[-1]),
                             "r": {k: r2(((ytd_return(ci.to_frame()) if n is None else period_return(ci.to_frame(), n)).iloc[0]) * 100)
                                   for k, n in PERIODS.items()}}

    # ---------------- scanners (library in scanners.py)
    bench_s = W["close"][bench].reindex(Cu.index).ffill() if bench in W["close"] else Cu.mean(axis=1)
    # All-time high before today: monthly history (config/ath.csv, from fetch_ath.py) + daily highs since.
    ath_prior = None
    if (CFG / "ath.csv").exists():
        a = pd.read_csv(CFG / "ath.csv", dtype={"symbol": str}).drop_duplicates("symbol").set_index("symbol")
        cutoff = str(a["cutoff"].iloc[0]) if len(a) else last
        since = Hu.loc[(Hu.index >= cutoff) & (Hu.index < last)].max()
        ath_prior = pd.Series(np.fmax(a["ath_before"].reindex(U).to_numpy(dtype=float), since.reindex(U).to_numpy(dtype=float)), index=U)
        # stocks missing from the file: only trust the daily data if the whole listed life is inside it
        first = raw_close[U].apply(lambda s_: s_.first_valid_index())
        inside = first > dates[5]
        miss = ath_prior.index[a["ath_before"].reindex(U).isna()]
        ath_prior[miss] = np.where(inside[miss], Hu[miss].iloc[:-1].max(), np.nan)
        print(f"ATH reference: {int(ath_prior.notna().sum())} of {len(U)} stocks")
    sc_meta, sc_hits, sc_metric, per_stock = SC.run_all({
        "O": Ou, "H": Hu, "L": Lu, "C": Cu, "V": Vu, "bench": bench_s, "sma": sma,
        "ema20": ema20, "ema50": ema50, "rs_now": rs_now, "rs_prev": rs_prev.reindex(U),
        "hi52": hi52, "lo52": lo52, "avgv50": avgv50, "vr": vr, "tt": tt, "ath_prior": ath_prior})
    for r in rows:
        if r["s"] in uset:
            for k, ser in per_stock.items():
                r[k] = r2(ser.get(r["s"]), 1)
    cats = list(SC.CATS)

    # ---------------- fundamentals (NSE filings, from fetch_fundamentals.py)
    FR = None
    try:
        import fundamentals as FD
        st_series = pd.Series({s: stage(s) for s in U})
        a_of = lambda n: pd.Series({s: (bool(c[s] > sma[n].iloc[-1][s]) if pd.notna(sma[n].iloc[-1][s]) else None) for s in U})
        FR = FD.build(U, {"mcap": mc_show.reindex(U), "c": c, "rs": rs_now, "st": st_series, "tt": tt, "a200": a_of(200),
                          "a50": a_of(50), "h52": (c / hi52.iloc[-1] - 1) * 100, "vr": vr, "C": Cu, "dates": list(dates),
                          "sector": sec.reindex(U)})
    except Exception as e:  # fundamentals are optional - never break the daily run
        import traceback
        traceback.print_exc()
        print(f"fundamentals skipped: {e}")
    if FR:
        for r in rows:
            r.update(FR["per_stock"].get(r["s"], {}))
            if not r.get("ind") and FR["industry"].get(r["s"]):
                r["ind"] = FR["industry"][r["s"]]
        sc_meta += FR["meta"]
        sc_hits.update(FR["hits"])
        sc_metric.update(FR["metric"])
        cats = [k for k in cats if k != "Weakness"] + FR["cats"][:3] + ["Weakness", FR["cats"][3]]
        if "Industry" not in groups and FR["industry"]:
            iu = pd.Series(FR["industry"])
            groups["Industry"] = {k: sorted(iu.index[iu == k]) for k in sorted(iu.unique())}
        dump_later = {"fund.json": FR["detail"]}
        filed = [v.get("filed") for v in FR["per_stock"].values() if v.get("filed")]
        fund_meta = {"stocks": sum(1 for v in FR["per_stock"].values() if "fr" in v), "latest_filing": max(filed) if filed else None}
        print(f"fundamentals: {fund_meta['stocks']} stocks rated, latest filing {fund_meta['latest_filing']}")
    else:
        dump_later, fund_meta = {}, None
    # ---------------- RS rating history and RS-line blue dots (rs_history.py)
    rs_meta = None
    try:
        import rs_history as RH
        cal_l = sorted(LONG.loc[LONG.symbol == bench, "date"].unique())[-(RH.WINDOW + 280):]
        lp = LONG[LONG.date.isin(set(cal_l)) & LONG.symbol.isin(set(A) | {bench})]
        CLw = lp.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").reindex(cal_l)
        CLa = CLw.reindex(columns=A).ffill(limit=3)
        per_rs, rs_json, R_rs, dot_rs = RH.build(CLa, CLw[bench].ffill(), U, A, rs_all, list(Ca.index[-260:]))
        for r in rows:
            r.update(per_rs.get(r["s"], {}))
        rm, rh, rmet = RH.scans(U, rs_now, per_rs, R_rs, dot_rs, bars, c, hi52.iloc[-1])
        sc_meta += rm
        sc_hits.update(rh)
        sc_metric.update(rmet)
        dump_later["rs.json"] = rs_json
        rs_meta = {"stocks": len(rs_json["rows"]), "dots": len(rh.get("rs_bluedot", [])), "weeks": len(rs_json["weeks"])}
    except Exception as e:  # never break the daily run
        import traceback
        traceback.print_exc()
        print(f"RS history skipped: {e}")
    # ---------------- delivery (NSE security-wise delivery, config/nse/dlv; delivery.py)
    dlv_meta = None
    try:
        import delivery as DLV
        DR = DLV.build(Ca, V[A], list(dates), U, A, sma_a[50], list(Ca.index[-260:]), dates[max(0, len(dates) - 200)])
        if DR:
            for r in rows:
                r.update(DR["per_stock"].get(r["s"], {}))
            sc_meta += DR["meta"]
            sc_hits.update(DR["hits"])
            sc_metric.update(DR["metric"])
            at = cats.index("Volume") + 1 if "Volume" in cats else len(cats)
            cats = cats[:at] + ["Delivery"] + cats[at:]
            dump_later["dlv.json"] = DR["detail"]
            dlv_meta = {"stocks": len(DR["per_stock"]), "asof": DR["detail"]["asof"]}
    except Exception as e:  # never break the daily run
        import traceback
        traceback.print_exc()
        print(f"delivery skipped: {e}")
    # ---------------- NSE index valuations, India VIX, RRG (indices.py) + corporate actions and holidays
    idx_meta = None
    try:
        import indices as IX
        IR = IX.build(last)
        if IR:
            dump_later["indices.json"] = IR
            p50 = next((x for x in IR["rows"] if x["n"] == "Nifty 50"), {})
            idx_meta = {"asof": IR["asof"], "vix": {k: IR["vix"][k] for k in ("v", "d1", "p1y")} if IR["vix"] else None,
                        "pe50": {"pe": p50.get("pe"), "p": p50.get("pe_p"), "m": p50.get("pe_m")}, "basis": IR["basis"]}
    except Exception as e:  # never break the daily run
        import traceback
        traceback.print_exc()
        print(f"index valuations skipped: {e}")
    corp_meta = None
    try:
        ca = json.loads((CFG / "nse" / "corp_actions.json").read_text())
        keep_ca = [r for r in ca.get("rows", []) if r.get("symbol") in aset and r.get("ex", "") >= dates[-10]]
        dump_later["corp.json"] = {"fetched": ca.get("fetched"), "rows": keep_ca}
        hol = json.loads((CFG / "nse" / "holidays.json").read_text()).get("trading", []) if (CFG / "nse" / "holidays.json").exists() else []
        nxt = [h for h in hol if h["date"] > last][:2]
        corp_meta = {"n": len(keep_ca), "holidays": nxt}
    except (OSError, ValueError) as e:
        print(f"corporate actions skipped: {e}")
    # ---------------- group charts and group signals (group_index.py): a price series for every theme, sector,
    # NSE index and industry, with breadth, money flow, RS line and group RS rating
    grp_meta = None
    try:
        import group_index as GI
        bench_full = PFULL.loc[PFULL.symbol == bench].set_index("date")["close"].sort_index()
        ev_f = CFG / "group_evidence.json"
        GS, gtoday, gfiles = GI.build(PFULL, groups, U, bench_full, OUT / "grp", last,
                                      json.loads(ev_f.read_text()) if ev_f.exists() else None)
        dump_later["grp.json"] = GS
        grp_meta = {"groups": len(GS["rows"]), "today": {u: {k: v for k, v in t.items() if v} for u, t in gtoday.items()}}
    except Exception as e:  # never break the daily run
        import traceback
        traceback.print_exc()
        print(f"group charts skipped: {e}")
    # ---------------- long-base identifier (bases.py; checked on 20 years of NSE data)
    base_meta = None
    try:
        import bases as BS
        BR = BS.build(LONG, U, rs_now)
        for r in rows:
            r.update(BR["per_stock"].get(r["s"], {}))
        bm, bh, bmet = BS.scans(BR)
        sc_meta += bm
        sc_hits.update(bh)
        sc_metric.update(bmet)
        cats = cats[:cats.index("Breakouts") + 1] + ["Bases"] + cats[cats.index("Breakouts") + 1:] if "Breakouts" in cats else cats + ["Bases"]
        dump_later["bases.json"] = {"asof": last, "rows": BR["rows"], "charts": BR["charts"], "evidence": BR["evidence"],
                                    "params": {"d_max": BS.D_MAX, "zone": BS.ZONE, "min_len": BS.MIN_LEN, "recent": BS.RECENT}}
        base_meta = {"stocks": len(BR["rows"]), "history_from": str(LONG.date.min())}
    except Exception as e:  # never break the daily run
        import traceback
        traceback.print_exc()
        print(f"bases skipped: {e}")

    # ---------------- Stage 2 phase: early / mid / late (stage2.py; checked on 20 years of NSE data)
    s2_meta = None
    try:
        import stage2 as S2
        SR = S2.build(LONG, [r["s"] for r in rows if r.get("st") == 2 and r["s"] in uset], rs_now)
        for r in rows:
            r.update(SR["per_stock"].get(r["s"], {}))
        sm, sh, smet = S2.scans(SR)
        sc_meta += sm
        sc_hits.update(sh)
        sc_metric.update(smet)
        at = cats.index("Bases") + 1 if "Bases" in cats else len(cats)
        cats = cats[:at] + ["Stage 2"] + cats[at:]
        dump_later["stage2.json"] = {"asof": last, "rows": SR["rows"], "evidence": SR["evidence"]}
        s2_meta = {"stocks": len(SR["rows"])}
    except Exception as e:  # never break the daily run
        import traceback
        traceback.print_exc()
        print(f"stage 2 phases skipped: {e}")
    # ---------------- quarterly results: this season's results, Result Quality and PEAD scores (results.py)
    res_meta = None
    try:
        import results as RES
        RB = RES.build(W, U, {"bench": bench, "names": {r["s"]: r.get("n", "") for r in rows}, "mcap": mc_show.reindex(U)})
        for r in rows:
            r.update(RB["per_stock"].get(r["s"], {}))
        rm, rh, rmet = RES.scans(RB)
        sc_meta += rm
        sc_hits.update(rh)
        sc_metric.update(rmet)
        at = cats.index("Stage 2") + 1 if "Stage 2" in cats else len(cats)
        cats = cats[:at] + ["Results"] + cats[at:]
        dump_later["results.json"] = {k: RB[k] for k in ("asof", "seasons", "rows", "due", "evidence")}
        res_meta = {"season": RB["seasons"][0]["label"], "main": RB["seasons"][0]["main"],
                    "n": sum(1 for x in RB["rows"] if x["sn"] == RB["seasons"][0]["id"])}
    except Exception as e:  # never break the daily run
        import traceback
        traceback.print_exc()
        print(f"results skipped: {e}")
    # ---------------- mutual-fund flows (monthly fund portfolios; mf_flows.py writes docs/data/mf.json)
    mf_meta = None
    try:
        import mf_scans as MS
        MR = MS.build(CFG / "mf" / "site" / "mf.json", {r["s"]: r for r in rows if r["s"] in uset})
        if MR:
            import shutil
            OUT.mkdir(parents=True, exist_ok=True)
            for f_ in ("mf.json", "mf_detail.json"):
                shutil.copyfile(CFG / "mf" / "site" / f_, OUT / f_)
            for r in rows:
                r.update(MR["per_stock"].get(r["s"], {}))
            sc_meta += MR["meta"]
            sc_hits.update(MR["hits"])
            sc_metric.update(MR["metric"])
            at = cats.index("Ownership") + 1 if "Ownership" in cats else len(cats)
            cats = cats[:at] + [MS.CAT] + cats[at:]
            mf_meta = MR["info"]
    except Exception as e:  # never break the daily run
        import traceback
        traceback.print_exc()
        print(f"fund flows skipped: {e}")
    # detailed documentation for every scanner (shown in a collapsible panel on the site)
    try:
        import scan_docs as SD
        for m_ in sc_meta:
            if m_["id"] in SD.DOCS:
                m_["doc"] = SD.DOCS[m_["id"]]
        missing = [m_["id"] for m_ in sc_meta if "doc" not in m_]
        if missing:
            print(f"scanner docs missing for: {', '.join(missing)}")
    except Exception as e:  # docs are optional
        print(f"scanner docs skipped: {e}")
    scans = {"cats": cats, "meta": sc_meta, "hits": sc_hits, "metric": sc_metric}

    ist = timezone(timedelta(hours=5, minutes=30))
    fm = json.loads((CACHE / "fetch_meta.json").read_text()) if (CACHE / "fetch_meta.json").exists() else {}
    meta = {"asof": last, "generated": datetime.now(ist).strftime("%Y-%m-%d %H:%M IST"),
            "source": fm.get("source"), "stocks_with_data": len(syms), "universe": len(U), "all_stocks": len(A),
            "sector_from_industry": sec_check,
            "failed": fm.get("failed_count"), "indices": indices,
            "filters": {"min_price": S["min_price"], "min_median_turnover_cr": S["min_median_turnover_cr"],
                        "min_market_cap_cr": S["min_market_cap_cr"] if mcap is not None else None},
            "min_group_size": S["min_group_size"], "fund": fund_meta, "bases": base_meta, "stage2": s2_meta, "results": res_meta, "mf": mf_meta, "rs": rs_meta, "dlv": dlv_meta, "idx": idx_meta, "corp": corp_meta, "grp": grp_meta}

    def dump(name, obj):
        (OUT / name).write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False))
    dump("meta.json", meta)
    dump("stocks.json", rows)
    dump("groups.json", groups)
    dump("breadth.json", breadth)
    dump("scans.json", scans)
    for name, obj in dump_later.items():
        dump(name, obj)

    # ---------------- last ~1 year of closes for watchlists (sparklines, since-added, stock-card chart)
    def rd(v):
        if v is None or not np.isfinite(v):
            return None
        v = round(float(v), 0 if v >= 1000 else 1 if v >= 100 else 2)
        return int(v) if v == int(v) else v
    tail = Ca.iloc[-260:]
    closes = {"dates": list(tail.index), "c": {s: [rd(v) for v in tail[s].tolist()] for s in A}}
    if bench in W["close"]:
        closes["c"][bench] = [rd(v) for v in W["close"][bench].reindex(tail.index).ffill().tolist()]
    dump("closes.json", closes)
    # instrument keys for the live Telegram alerts (telegram_alerts.py --live); changes rarely
    if "key" in u.columns:
        u.loc[u.kind == "stock", ["symbol", "key"]].dropna().sort_values("symbol").to_csv(CFG / "upstox_keys.csv", index=False)
    print("scans: " + ", ".join(f"{k}={len(v)}" for k, v in scans["hits"].items()))
    print(f"breadth today: >50DMA {breadth['a50'][-1]}%  >200DMA {breadth['a200'][-1]}%  "
          f"A/D {breadth['adv'][-1]}/{breadth['dec'][-1]}")


if __name__ == "__main__":
    main()
