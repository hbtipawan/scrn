"""Upside score: which liquid stocks have the best odds of beating the average stock over the next 3 months.

Built from numbers the site already computes - price and volume technicals, the RS rating, the RS line against
Nifty 500, stage and trend template, sector and industry rotation (equal-weight group indices, group RS rating,
group breadth) and market breadth. Two equal halves:

  1. a LightGBM model (config/upside_model.txt, 88 inputs) giving the chance that the stock finishes the next
     63 sessions in the top 20% of the liquid universe;
  2. a plain leadership score: the average percentile of the RS rating, closeness to the 52-week high and the
     industry's RS rating.

Upside rank = percentile (1-99) of the average of the two percentiles, among liquid stocks with a year of history.

How it was tested (Nov 2026, config/upside_evidence.json): NSE daily data 2006-2026, every 5th session, signal at
the close, outcome from the next session's open. The model was retrained each year on data whose 3-month outcome
was known before that year began. The design was fixed on 2010-2018 and then read once on 2019-2026: the top 10%
beat the average stock by +4.4% over 3 months (RS rating alone: +2.7%), in every calendar year 2010-2026.

Every input below is an exact port of the research code (features.py), so the live score matches the test.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HIST = 900            # sessions used (the longest look-back is 252 + 252 for the RS line's 52-week high)
FAMILY = [            # model inputs grouped into the reasons shown on the site
    ("sec_", "sector"), ("ind_", "industry"), ("m_", "market")]
NEAR = {"from_hi", "since_hi", "rsl_from_hi", "since_blue"}
TREND = {"stage", "tt", "tt_count", "above50_frac", "c_ema21", "from_lo"}
VOLA = {"atr_pct", "adr20", "vol63", "rng10", "rng63", "tight10_63", "pos20", "dd63", "maxgain20", "maxloss20",
        "updays20", "r1d"}


def family(f):
    for pre, k in FAMILY:
        if f.startswith(pre):
            return k
    if f in NEAR:
        return "near_high"
    if f.startswith(("rs", "r1", "r3", "r6")):
        return "rs"
    if f in TREND or f.startswith(("c_sma", "sma")):
        return "trend"
    if f in VOLA:
        return "volatility"
    return "volume"


def _wide(PFULL, syms):
    p = PFULL[PFULL.symbol.isin(set(syms))]
    cal = sorted(PFULL.date.unique())[-HIST:]
    p = p[p.date >= cal[0]].drop_duplicates(["date", "symbol"], keep="last")
    W = {f: p.pivot(index="date", columns="symbol", values=f).reindex(index=cal, columns=syms).astype(float)
         for f in ("open", "high", "low", "close", "volume")}
    O, H, L, C, V = W["open"], W["high"], W["low"], W["close"], W["volume"]
    ok = (C > 0) & np.isfinite(C)
    C = C.where(ok)
    O = O.where(O > 0, C).where(ok); H = H.where(H > 0, C).where(ok); L = L.where(L > 0, C).where(ok)
    H = pd.DataFrame(np.fmax.reduce([H.to_numpy(), O.to_numpy(), C.to_numpy()]), index=C.index, columns=C.columns)
    L = pd.DataFrame(np.fmin.reduce([L.to_numpy(), O.to_numpy(), C.to_numpy()]), index=C.index, columns=C.columns)
    return O, H, L, C, V.where(ok)


def features(PFULL, syms, bench, groups):
    """Inputs for the last session (and the ranks they need), exactly as in the research panel."""
    O, H, L, C, V = _wide(PFULL, syms)
    dates = C.index
    nD, nS = C.shape
    traded = C.notna()
    Cf = C.ffill(limit=10)
    bars = traded.cumsum()
    TO = C * V / 1e7
    med50 = TO.rolling(50, min_periods=20).median()
    liquid = (Cf >= 20) & (med50 >= 1.0) & (bars >= 60) & traded.rolling(3, min_periods=1).max().astype(bool)
    t = nD - 1
    lags = [t - 5 * k for k in range(13)]                  # the research sampled every 5th session
    f = {}
    ret = lambda n: Cf / Cf.shift(n) - 1

    # RS rating (site formula), ranked among the liquid stocks of each sampled day
    parts = [(ret(n) + 1) for n in (63, 126, 189, 252)]
    w = [0.4, 0.2, 0.2, 0.2]
    sc = sum(wi * pp for wi, pp in zip(w, parts))
    avail = sum(wi * pp.notna() for wi, pp in zip(w, parts))
    psum = sum(wi * pp.fillna(0) for wi, pp in zip(w, parts))
    sc = sc.fillna(psum / avail.replace(0, np.nan))
    rs_at = {i: (sc.iloc[i].where(liquid.iloc[i]).rank(pct=True) * 98 + 1).round() for i in lags}
    rs = rs_at[t]
    f["rs"] = rs
    f["rs_chg4w"] = rs - rs_at[lags[4]]
    f["rs_chg12w"] = rs - rs_at[lags[12]]
    stack = pd.concat([rs_at[i] for i in lags], axis=1)
    f["rs_from_max12w"] = rs - stack.max(axis=1)
    f["rs_from_min12w"] = rs - stack.min(axis=1)
    f["rs_min8w"] = stack.iloc[:, :9].min(axis=1)
    for n, nm in ((5, "r1w"), (21, "r1m"), (63, "r3m"), (126, "r6m"), (252, "r1y")):
        f[nm] = ret(n).iloc[t]

    # RS line against Nifty 500, blue dots
    n500 = PFULL.loc[PFULL.symbol == bench].set_index("date")["close"].reindex(dates).ffill()
    rsl = Cf.div(n500, axis=0)
    rsl_hi = rsl.rolling(252, min_periods=126).max()
    f["rsl_from_hi"] = (rsl / rsl_hi - 1).iloc[t]
    blue = (rsl >= rsl_hi * 0.99999) & traded
    last_blue = pd.DataFrame(np.where(blue, np.arange(nD)[:, None], np.nan), index=dates, columns=syms).ffill()
    f["since_blue"] = (np.arange(nD)[:, None] - last_blue).clip(upper=252).fillna(252).iloc[t]
    f["rsl_r3m"] = (rsl / rsl.shift(63) - 1).iloc[t]

    # trend and structure
    sma = {n: Cf.rolling(n, min_periods=n).mean() for n in (10, 20, 50, 150, 200)}
    for n in (10, 20, 50, 150, 200):
        f[f"c_sma{n}"] = (Cf / sma[n] - 1).iloc[t]
    f["sma50_slope"] = (sma[50] / sma[50].shift(20) - 1).iloc[t]
    slope150 = sma[150] / sma[150].shift(20) - 1
    f["sma150_slope"] = slope150.iloc[t]
    f["sma200_slope"] = (sma[200] / sma[200].shift(22) - 1).iloc[t]
    f["c_ema21"] = (Cf / Cf.ewm(span=21, adjust=False).mean() - 1).iloc[t]
    hi252 = H.rolling(252, min_periods=60).max(); lo252 = L.rolling(252, min_periods=60).min()
    f["from_hi"] = (Cf / hi252 - 1).iloc[t]
    f["from_lo"] = (Cf / lo252 - 1).iloc[t]
    hi_day = pd.DataFrame(np.where(H >= hi252 * 0.99999, np.arange(nD)[:, None], np.nan), index=dates, columns=syms).ffill()
    f["since_hi"] = (np.arange(nD)[:, None] - hi_day).clip(upper=252).iloc[t]     # no high since listing -> NaN, as tested
    c_, m_, s_ = Cf.iloc[t], sma[150].iloc[t], slope150.iloc[t]
    stg = pd.Series(np.select([(c_ > m_) & (s_ > 0.01), (c_ < m_) & (s_ < -0.01), c_ >= m_], [2, 4, 3], 1), index=syms, dtype=float)
    f["stage"] = stg.where(m_.notna())
    up200 = sma[200] > sma[200].shift(22)
    conds = [Cf > sma[150], Cf > sma[200], sma[150] > sma[200], up200, sma[50] > sma[150], sma[50] > sma[200],
             Cf > sma[50], Cf >= 1.3 * lo252, Cf >= 0.75 * hi252]
    ttn = sum(cc.iloc[t].astype(float) for cc in conds)
    f["tt_count"] = ttn
    f["tt"] = ((ttn == 9) & (rs >= 70)).astype(float)
    f["above50_frac"] = (Cf > sma[50]).astype(float).rolling(50, min_periods=20).mean().iloc[t]

    # volatility and tightness
    pc = Cf.shift(1)
    tr = pd.DataFrame(np.fmax.reduce([(H - L).to_numpy(), (H - pc).abs().to_numpy(), (L - pc).abs().to_numpy()]),
                      index=dates, columns=syms)
    f["atr_pct"] = (tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / Cf).iloc[t]
    f["adr20"] = ((H / L - 1) * 100).rolling(20, min_periods=10).mean().iloc[t]
    dr = Cf.pct_change(fill_method=None)
    f["vol63"] = dr.rolling(63, min_periods=40).std().iloc[t]
    rng = lambda n: H.rolling(n, min_periods=n // 2).max() / L.rolling(n, min_periods=n // 2).min() - 1
    r10, r63 = rng(10).iloc[t], rng(63).iloc[t]
    f["rng10"], f["rng63"], f["tight10_63"] = r10, r63, r10 / r63
    lo20, hi20 = L.rolling(20, min_periods=10).min(), H.rolling(20, min_periods=10).max()
    f["pos20"] = ((Cf - lo20) / (hi20 - lo20)).iloc[t]
    f["dd63"] = (Cf / Cf.rolling(63, min_periods=30).max() - 1).iloc[t]
    f["maxgain20"] = dr.rolling(20, min_periods=10).max().iloc[t]
    f["maxloss20"] = dr.rolling(20, min_periods=10).min().iloc[t]
    f["updays20"] = (dr > 0).astype(float).rolling(20, min_periods=10).mean().iloc[t]
    f["r1d"] = dr.iloc[t]

    # volume and size
    avgv50 = V.rolling(50, min_periods=20).mean().shift(1)
    f["vr1"] = (V / avgv50).iloc[t]
    f["vr5"] = (V.rolling(5, min_periods=3).mean() / avgv50).iloc[t]
    upv = V.where(dr > 0, 0).rolling(50, min_periods=20).sum(); dnv = V.where(dr < 0, 0).rolling(50, min_periods=20).sum()
    f["ud_vol50"] = np.log((upv + 1) / (dnv + 1)).iloc[t]
    f["to_trend"] = (TO.rolling(20, min_periods=10).mean() / TO.rolling(120, min_periods=60).mean()).iloc[t]
    f["log_to"] = np.log(med50.clip(lower=0.01)).iloc[t]
    f["log_px"] = np.log(Cf).iloc[t]

    # market breadth (liquid universe, point in time)
    ab50 = ((Cf > sma[50]) & liquid).sum(axis=1) / liquid.sum(axis=1)
    ab200 = ((Cf > sma[200]) & liquid).sum(axis=1) / liquid.sum(axis=1)
    drl = dr.where(liquid.shift(1).fillna(False).astype(bool)).clip(-0.4, 0.4)
    ew = (1 + drl.mean(axis=1).fillna(0)).cumprod()
    mk = {"m_ab50": ab50.iloc[t], "m_ab200": ab200.iloc[t], "m_ew_vs50": (ew / ew.rolling(50).mean() - 1).iloc[t],
          "m_ew_r3m": (ew / ew.shift(63) - 1).iloc[t], "m_ew_dd": (ew / ew.rolling(252, min_periods=60).max() - 1).iloc[t],
          "m_n500_vs50": (n500 / n500.rolling(50).mean() - 1).iloc[t]}
    for k, v in mk.items():
        f[k] = pd.Series(float(v), index=syms)

    # sector and industry rotation: equal-weight index of each group's liquid members
    liq_prev = liquid.shift(1).fillna(False).astype(bool) & liquid
    drg = dr.where(liq_prev).clip(-0.4, 0.4)
    ab50_s = (Cf > sma[50]).astype(float).where(liquid)
    ab200_s = (Cf > sma[200]).astype(float).where(liquid)
    near_hi = (Cf >= 0.85 * hi252).astype(float).where(liquid)
    TOl = TO.where(liquid)
    for gk, g in groups.items():
        g = g.reindex(syms)
        names = sorted(g.dropna().unique())
        M = np.zeros((nS, len(names)), np.float32)
        pos = {n: j for j, n in enumerate(names)}
        for j, s in enumerate(syms):
            if pd.notna(g.iloc[j]):
                M[j, pos[g.iloc[j]]] = 1

        def gmean(df):
            a = df.to_numpy(); m = np.isfinite(a)
            num = np.where(m, a, 0) @ M; den = m.astype(np.float32) @ M
            with np.errstate(all="ignore"):
                return num / den, den
        gret, _ = gmean(drg)
        gidx = pd.DataFrame(np.cumprod(1 + np.nan_to_num(gret), axis=0), index=dates, columns=names)
        ok = pd.DataFrame(gmean(TOl)[1], index=dates, columns=names) >= 3
        gr = {n: (gidx / gidx.shift(n) - 1).where(ok) for n in (5, 21, 63, 126)}
        gp = [gidx / gidx.shift(n) for n in (63, 126, 189, 252)]
        grs = (0.4 * gp[0] + 0.2 * gp[1] + 0.2 * gp[2] + 0.2 * gp[3]).where(ok).rank(axis=1, pct=True) * 98 + 1
        gto = pd.DataFrame(gmean(TOl.fillna(0).where(liquid))[0], index=dates, columns=names)
        rk = lambda df, i=t: df.iloc[i].rank(pct=True)
        gtab = {
            "r1w": rk(gr[5]), "r1m": rk(gr[21]), "r3m": rk(gr[63]), "r6m": rk(gr[126]),
            "r1m_rkchg": rk(gr[21]) - rk(gr[21], t - 5), "r3m_rkchg": rk(gr[63]) - rk(gr[63], t - 5),
            "rs": grs.iloc[t], "rs_chg4w": grs.iloc[t] - grs.iloc[t - 20], "rs_chg12w": grs.iloc[t] - grs.iloc[t - 60],
            "b50": pd.Series(gmean(ab50_s)[0][t], index=names).where(ok.iloc[t]),
            "b200": pd.Series(gmean(ab200_s)[0][t], index=names).where(ok.iloc[t]),
            "nearhi": pd.Series(gmean(near_hi)[0][t], index=names).where(ok.iloc[t]),
            "flow": (gto.rolling(20, min_periods=10).mean() / gto.rolling(120, min_periods=60).mean()).where(ok).iloc[t],
            "vs50": (gidx / gidx.rolling(50).mean() - 1).where(ok).iloc[t],
            "vs150": (gidx / gidx.rolling(150).mean() - 1).where(ok).iloc[t],
        }
        for k, ser in gtab.items():
            f[f"{gk}_{k}"] = g.map(ser).astype(float)
        f[f"{gk}_rel_r3m"] = f["r3m"] - g.map(gr[63].iloc[t]).astype(float)
        both = pd.DataFrame({"rs": rs, "g": g}).dropna()
        med = both.groupby("g")["rs"].agg(["median", "count"])
        f[f"{gk}_rs_med"] = g.map(med.loc[med["count"] >= 3, "median"]).astype(float)

    F = pd.DataFrame(f)
    F.index.name = "sym"
    elig = liquid.iloc[t] & (bars.iloc[t] >= 252)
    return F[elig.reindex(F.index).fillna(False).to_numpy()], dates[t], float(ab50.iloc[t])


def build(PFULL, syms, bench, groups, cfg: Path):
    """-> (upside.json content, {symbol: upside rank}) for the last session."""
    import lightgbm as lgb
    booster = lgb.Booster(model_file=str(cfg / "upside_model.txt"))
    feats = booster.feature_name()
    F, asof, ab50 = features(PFULL, syms, bench, groups)
    mkt = [c for c in feats if c.startswith("m_")]
    X = pd.concat([F[[c for c in feats if c not in mkt]].rank(pct=True), F[mkt]], axis=1)[feats].astype(np.float32)
    prob = pd.Series(booster.predict(X), index=F.index)
    pr = lambda s: s.rank(pct=True)
    mom = (pr(F["rs"]) + pr(F["from_hi"]) + pr(F["ind_rs"]).fillna(0.5)) / 3
    s4 = 0.5 * pr(prob) + 0.5 * pr(mom)
    up = (pr(s4) * 98 + 1).round()
    dec = np.floor(s4.rank(pct=True, method="first").clip(upper=0.9999) * 10).astype(int)
    contrib = pd.DataFrame(booster.predict(X, pred_contrib=True)[:, :-1], columns=feats, index=F.index)
    G = contrib.T.groupby(contrib.columns.map(family)).sum().T
    rows = []
    for s in up.sort_values(ascending=False).index:
        g = G.loc[s].sort_values()
        rows.append({"s": s, "u": int(up[s]), "d": int(dec[s]), "p": round(float(prob[s]) * 100, 1),
                     "w": [k for k, v in g[::-1].items() if v > 0.05][:3], "a": [k for k, v in g.items() if v < -0.05][:2],
                     "irs": None if pd.isna(F.at[s, "ind_rs"]) else int(round(F.at[s, "ind_rs"])),
                     "srs": None if pd.isna(F.at[s, "sec_rs"]) else int(round(F.at[s, "sec_rs"])),
                     "rs": None if pd.isna(F.at[s, "rs"]) else int(F.at[s, "rs"]),
                     "h52": None if pd.isna(F.at[s, "from_hi"]) else round(float(F.at[s, "from_hi"]) * 100, 1)})
    ev_f = cfg / "upside_evidence.json"
    out = {"asof": asof, "n": len(rows), "ab50": round(ab50 * 100, 1), "rows": rows,
           "evidence": json.loads(ev_f.read_text()) if ev_f.exists() else None}
    return out, {r["s"]: r["u"] for r in rows}
