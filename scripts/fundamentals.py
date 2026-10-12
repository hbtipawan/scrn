"""Fundamental metrics, Fund rating and fundamental scanners.

Input: config/fund_results.csv, fund_holdings.csv, fund_info.csv (made by fetch_fundamentals.py
from NSE filings). Used by compute.py:

    F = fundamentals.build(U, ctx)  ->  dict with
        per_stock  {symbol: {...metrics...}}       merged into stocks.json rows
        detail     {symbol: {q: [...], h: [...]}}  quarterly tables for the stock card (fund.json)
        industry   {symbol: industry}
        meta, hits, metric                        extra scanners (same format as scanners.py)
        cats                                       their categories

Conventions
  * Growth uses net profit attributable to shareholders (PAT) - robust to splits/bonuses,
    unlike reported EPS. Growth is only computed when the base quarter is profitable.
  * P/E = today's market cap / trailing-4-quarter PAT, so it moves with the price every day.
  * Banks and lenders: no operating margin, ROCE, debt or cash-flow tests (they don't mean the
    same thing for a lender).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"

CATS = ["Earnings & growth", "Quality & value", "Ownership", "Fundamental red flags"]


def _num(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else x


def growth(now, base):
    """% growth, only when the base is positive and meaningful."""
    if now is None or base is None or not np.isfinite(now) or not np.isfinite(base) or base <= 0:
        return np.nan
    g = (now / base - 1) * 100
    return float(np.clip(g, -100, 999))


def load():
    r = pd.read_csv(CFG / "fund_results.csv", dtype={"symbol": str}) if (CFG / "fund_results.csv").exists() else pd.DataFrame()
    h = pd.read_csv(CFG / "fund_holdings.csv", dtype={"symbol": str}) if (CFG / "fund_holdings.csv").exists() else pd.DataFrame()
    i = pd.read_csv(CFG / "fund_info.csv", dtype={"symbol": str}).set_index("symbol") if (CFG / "fund_info.csv").exists() else pd.DataFrame()
    return r, h, i


def stock_metrics(q, hold):
    """q: this stock's quarterly rows sorted by quarter end; hold: shareholding rows sorted."""
    out = {}
    q = q.copy()
    q["qe"] = pd.to_datetime(q["qe"])
    q = q.drop_duplicates("qe", keep="last").set_index("qe").sort_index()
    bank = bool(q["bank"].fillna(0).iloc[-1]) if len(q) else False
    out["bank"] = bank
    if len(q):
        last = q.index[-1]

        qn = (q.index.year * 4 + (q.index.month - 1) // 3).tolist()
        pos = {n: i for i, n in enumerate(qn)}
        n0 = qn[-1]
        cols = {c: q[c].to_numpy(dtype=float) if c in q else None for c in q.columns if c not in ("symbol", "basis", "aud", "filed", "xbrl", "first_filed")}

        def at(months_back, col):
            i = pos.get(n0 - months_back // 3)
            arr = cols.get(col)
            return float(arr[i]) if i is not None and arr is not None else np.nan

        L = q.iloc[-1]
        out["qe"] = last.strftime("%Y-%m-%d")
        out["filed"] = L.get("filed")
        out["basis"] = L.get("basis")
        out["rev_q"], out["pat_q"] = _num(L["rev"]), _num(L["pat"])
        out["rev_yoy"], out["pat_yoy"] = growth(L["rev"], at(12, "rev")), growth(L["pat"], at(12, "pat"))
        out["rev_qoq"], out["pat_qoq"] = growth(L["rev"], at(3, "rev")), growth(L["pat"], at(3, "pat"))
        # YoY PAT growth for the previous two quarters (for acceleration)
        out["pat_yoy1"] = growth(at(3, "pat"), at(15, "pat"))
        out["pat_yoy2"] = growth(at(6, "pat"), at(18, "pat"))
        out["rev_yoy1"] = growth(at(3, "rev"), at(15, "rev"))
        # revenue growth streak (YoY > 10%) over the last 6 quarters
        streak = 0
        for k in range(6):
            g = growth(at(3 * k, "rev"), at(3 * k + 12, "rev"))
            if np.isfinite(g) and g > 10:
                streak += 1
            else:
                break
        out["rev_streak"] = streak
        # trailing four quarters (only when four consecutive quarters exist)
        def ttm(col, off=0):
            vals = [at(3 * k + off, col) for k in range(4)]
            return float(np.sum(vals)) if all(np.isfinite(v) for v in vals) else np.nan
        out["rev_ttm"], out["pat_ttm"] = ttm("rev"), ttm("pat")
        out["rev_ttm_g"] = growth(out["rev_ttm"], ttm("rev", 12))
        out["pat_ttm_g"] = growth(out["pat_ttm"], ttm("pat", 12))
        # operating margin (non-banks): PBT - exceptional + interest + depreciation - other income
        if not bank:
            op = (q["pbt"] - q["exc"].fillna(0) + q["fin"].fillna(0) + q["dep"].fillna(0) - q["oi"].fillna(0))
            opm = (op / q["rev"].where(q["rev"] > 0) * 100).clip(-200, 100)
            q["opm"] = opm
            cols["opm"] = opm.to_numpy(dtype=float)
            out["opm"] = _num(float(opm.iloc[-1])) if np.isfinite(opm.iloc[-1]) else None
            ago = at(12, "opm")
            out["opm_chg"] = float(opm.iloc[-1] - ago) if np.isfinite(opm.iloc[-1]) and np.isfinite(ago) else np.nan
            op_ttm = sum(at(3 * k, "opm") * at(3 * k, "rev") for k in range(4)) if np.isfinite(out["rev_ttm"]) else np.nan
            op_ttm0 = sum(at(3 * k + 12, "opm") * at(3 * k + 12, "rev") for k in range(4))
            r0 = ttm("rev", 12)
            out["opm_ttm"] = float(op_ttm / out["rev_ttm"]) if np.isfinite(op_ttm) and out["rev_ttm"] > 0 else np.nan
            out["opm_ttm_chg"] = float(out["opm_ttm"] - op_ttm0 / r0) if np.isfinite(out["opm_ttm"]) and np.isfinite(op_ttm0) and r0 and r0 > 0 else np.nan
        npm = q["pat"] / q["rev"].where(q["rev"] > 0) * 100
        q["npm"] = npm
        out["npm"] = float(npm.iloc[-1]) if np.isfinite(npm.iloc[-1]) else np.nan
        # balance sheet: latest half-year / year-end row
        bs = q[q["equity"].notna()]
        if len(bs):
            b = bs.iloc[-1]
            eq = b["equity"]
            prev = bs[bs.index <= bs.index[-1] - pd.DateOffset(months=11)]
            eq0 = prev["equity"].iloc[-1] if len(prev) else np.nan
            avg_eq = np.nanmean([eq, eq0]) if np.isfinite(eq0) else eq
            out["equity"] = _num(eq)
            out["bs_date"] = bs.index[-1].strftime("%Y-%m-%d")
            # ROE / ROCE on the last financial year (year-end equity), the convention most screeners use
            fyb = bs[bs.index.month == 3]
            fy_end = fyb.index[-1] if len(fyb) else None
            if fy_end is not None:
                back = (last.year * 4 + (last.month - 1) // 3) - (fy_end.year * 4 + (fy_end.month - 1) // 3)
                fy_pat = sum(at(3 * (back + k), "pat") for k in range(4))
                fy_ebit = sum(at(3 * (back + k), "pbt") - (at(3 * (back + k), "exc") if np.isfinite(at(3 * (back + k), "exc")) else 0)
                              + (at(3 * (back + k), "fin") if np.isfinite(at(3 * (back + k), "fin")) else 0) for k in range(4))
                if not np.isfinite(fy_pat):
                    fy_pat = fyb["ytd_pat"].iloc[-1]
                e_fy = fyb["equity"].iloc[-1]
                out["roe_fy"] = fy_end.strftime("%y")
                out["roe"] = float(np.clip(fy_pat / e_fy * 100, -200, 200)) if np.isfinite(fy_pat) and e_fy > 0 else np.nan
            else:
                fy_ebit, e_fy = np.nan, np.nan
                out["roe"] = float(np.clip(out["pat_ttm"] / avg_eq * 100, -200, 200)) if np.isfinite(out["pat_ttm"]) and avg_eq and avg_eq > 0 else np.nan
            if not bank:
                debt = b["borrow"] if np.isfinite(b["borrow"]) else np.nan
                out["debt"] = _num(debt)
                out["cash"] = _num(b["cash"])
                out["de"] = float(debt / eq) if np.isfinite(debt) and eq > 0 else np.nan
                if fy_end is not None:
                    d_fy = fyb["borrow"].iloc[-1]
                    cap = e_fy + (d_fy if np.isfinite(d_fy) else 0)
                    out["roce"] = float(np.clip(fy_ebit / cap * 100, -200, 200)) if np.isfinite(fy_ebit) and cap > 0 else np.nan
                out["cwip_pct"] = float(b["cwip"] / b["assets"] * 100) if np.isfinite(b["cwip"]) and b["assets"] and b["assets"] > 0 else np.nan
                prev_d = prev["borrow"].iloc[-1] if len(prev) else np.nan
                out["debt_chg"] = float(debt - prev_d) if np.isfinite(debt) and np.isfinite(prev_d) else np.nan
        # cash flow: latest March (full year) row
        fy = q[(q.index.month == 3) & q["ocf"].notna()]
        if len(fy) and not bank:
            f = fy.iloc[-1]
            out["fy"] = fy.index[-1].strftime("%Y")
            out["ocf"] = _num(f["ocf"])
            out["fcf"] = float(f["ocf"] - (f["capex"] if np.isfinite(f["capex"]) else 0))
            out["ocf_pat"] = float(f["ocf"] / f["ytd_pat"]) if np.isfinite(f["ytd_pat"]) and f["ytd_pat"] > 0 else np.nan
    # shareholding
    if hold is not None and len(hold):
        hh = hold.copy()
        hh["qe"] = pd.to_datetime(hh["qe"])
        hh = hh.drop_duplicates("qe", keep="last").set_index("qe").sort_index()
        hh["retail"] = hh["ret_small"].fillna(0) + hh["ret_big"].fillna(0)
        hh["inst"] = hh["fii"].fillna(0) + hh["dii"].fillna(0)
        H = hh.iloc[-1]
        out["shp_q"] = hh.index[-1].strftime("%Y-%m-%d")
        for c in ("promoter", "fii", "dii", "mf", "retail", "inst"):
            out[c] = _num(float(H[c])) if np.isfinite(H[c]) else None

        def chg(c, months):
            t = hh.index[-1] - pd.DateOffset(months=months)
            m = hh.index[(hh.index >= t - pd.Timedelta(days=10)) & (hh.index <= t + pd.Timedelta(days=10))]
            return float(H[c] - hh.loc[m[0], c]) if len(m) and np.isfinite(H[c]) and np.isfinite(hh.loc[m[0], c]) else np.nan
        for c in ("promoter", "fii", "dii", "mf", "retail", "inst"):
            out[c + "_1q"], out[c + "_1y"] = chg(c, 3), chg(c, 12)
        h0 = hh["holders"].dropna()
        out["holders"] = int(h0.iloc[-1]) if len(h0) else None
        out["holders_1y"] = growth(h0.iloc[-1], h0.iloc[0]) if len(h0) > 3 else np.nan
    # quarterly table for the stock card (latest 10 quarters)
    detail = {}
    if len(q):
        t = q.tail(10)
        detail["q"] = [[d.strftime("%b %y"), _r(r.rev), _r(r.pat), _r(r.eps, 2), _r(r.get("opm"), 1), _r(r.npm, 1)] for d, r in t.iterrows()]
        detail["basis"] = "Consolidated" if q["basis"].iloc[-1] == "C" else "Standalone"
    if hold is not None and len(hold):
        detail["h"] = [[d.strftime("%b %y"), _r(r.promoter, 2), _r(r.fii, 2), _r(r.dii, 2), _r(r.mf, 2), _r(r.retail, 2), None if pd.isna(r.holders) else int(r.holders)]
                       for d, r in hh.tail(6).iterrows()]
    return out, detail


def _r(v, nd=1):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if np.isfinite(v) else None


def pct(s):
    return s.rank(pct=True)


def build(U, ctx):
    """U: list of symbols in today's universe. ctx: dict with mcap (Series, Rs Cr), c (close), rs, st (stage),
    tt (trend template), a200 / a50 (bool Series), h52 (% from high), C (closes frame), dates, vr."""
    res, hold, info = load()
    if not len(res):
        return None
    res = res[res.symbol.isin(U)]
    hold = hold[hold.symbol.isin(U)] if len(hold) else hold
    hg = dict(tuple(hold.groupby("symbol"))) if len(hold) else {}
    M, detail = {}, {}
    for sym, g in res.groupby("symbol"):
        m, d = stock_metrics(g.sort_values("qe"), hg.get(sym))
        M[sym], detail[sym] = m, d
    for sym, g in hg.items():          # holdings only (no results parsed)
        if sym not in M:
            m, d = stock_metrics(pd.DataFrame(columns=res.columns), g)
            M[sym], detail[sym] = m, d
    df = pd.DataFrame.from_dict(M, orient="index").reindex(U)
    ALL = ["bank", "qe", "filed", "basis", "rev_q", "pat_q", "rev_yoy", "pat_yoy", "rev_qoq", "pat_qoq", "pat_yoy1", "pat_yoy2", "rev_yoy1",
           "rev_streak", "rev_ttm", "pat_ttm", "rev_ttm_g", "pat_ttm_g", "opm", "opm_chg", "opm_ttm", "opm_ttm_chg", "npm", "equity",
           "bs_date", "roe", "roe_fy", "debt", "cash", "de", "roce", "cwip_pct", "debt_chg", "fy", "ocf", "fcf", "ocf_pat", "shp_q", "holders",
           "holders_1y"] + [c + sfx for c in ("promoter", "fii", "dii", "mf", "retail", "inst") for sfx in ("", "_1q", "_1y")]
    for col in ALL:
        if col not in df:
            df[col] = np.nan
    mc = ctx["mcap"].reindex(U)
    df["pe"] = np.where(df["pat_ttm"] > 0, mc / df["pat_ttm"], np.nan)
    df["ps"] = np.where(df["rev_ttm"] > 0, mc / df["rev_ttm"], np.nan)
    df["peg"] = np.where((df["pe"] > 0) & (df["pat_ttm_g"] > 0), df["pe"] / df["pat_ttm_g"], np.nan)
    df["pb"] = np.where(df.get("equity", pd.Series(np.nan, index=df.index)) > 0, mc / df.get("equity"), np.nan)

    # ── Fund rating 1-99: growth (70%) + quality (30%), percentile across the universe
    comp = {
        "pat_yoy": (df["pat_yoy"].clip(-100, 300), .25), "pat_yoy1": (df["pat_yoy1"].clip(-100, 300), .15),
        "pat_ttm_g": (df["pat_ttm_g"].clip(-100, 300), .20), "rev_yoy": (df["rev_yoy"].clip(-100, 200), .15),
        "roe": (df["roe"].clip(-50, 60), .15),
        "margin": (df["opm_chg"].fillna(df["npm"] * 0).clip(-20, 20) if "opm_chg" in df else df["npm"] * 0, .10),
    }
    num, den = pd.Series(0.0, index=df.index), pd.Series(0.0, index=df.index)
    for k, (s, w) in comp.items():
        p = pct(s)
        num += p.fillna(0) * w
        den += p.notna() * w
    raw = num / den.where(den >= .5)
    # loss-making on a trailing basis: capped low; no usable results: no rating
    raw = raw.where(~(df["pat_ttm"] <= 0), raw.clip(upper=.15))
    # results exist but growth can't be measured (loss in the base quarter) -> rate low, not blank
    lossy = raw.isna() & df["pat_q"].notna() & ((df["pat_ttm"] <= 0) | (df["pat_q"] <= 0))
    raw = raw.where(~lossy, 0.05)
    fr = (raw.rank(pct=True) * 98 + 1).round()
    df["fr"] = fr

    # ── industry (Yahoo classification; NSE's where Yahoo is missing)
    industry = {}
    if len(info):
        ind = info["industry"].fillna(info.get("nse_industry"))
        industry = {s: ind[s] for s in U if s in ind.index and isinstance(ind[s], str)}
        df["next_results"] = info["next_results"].reindex(U)

    # ── scanners
    c, rs, st, tt = ctx["c"].reindex(U), ctx["rs"].reindex(U), ctx["st"].reindex(U), ctx["tt"].reindex(U)
    a200, h52, vr = ctx["a200"].reindex(U), ctx["h52"].reindex(U), ctx["vr"].reindex(U)
    # Lenders / financials: banks (bank-format filings) plus NBFCs, insurers, brokers etc. by sector
    fin_sec = ctx.get("sector", pd.Series(dtype=object)).reindex(U).astype(str).str.contains("Financial", case=False, na=False)
    if len(info) and "sector" in info:
        fin_sec |= info["sector"].reindex(U).astype(str).str.contains("Financial", case=False, na=False)
    nb = ~(df["bank"].fillna(False).astype(bool) | fin_sec)
    df["fin"] = ~nb
    hits, metric, meta = {}, {}, []

    def add(id_, name, cat, desc, mask, m_label=None, m_vals=None, m_fmt="pct", sort="metric"):
        mask = pd.Series(mask, index=df.index).fillna(False).astype(bool)
        syms = sorted(mask.index[mask])
        hits[id_] = syms
        if m_label:
            mv = pd.Series(m_vals, index=df.index).reindex(syms)
            metric[id_] = {s: (None if pd.isna(mv[s]) else round(float(mv[s]), 2)) for s in syms}
        meta.append({"id": id_, "name": name, "cat": cat, "desc": desc, "metric": m_label, "fmt": m_fmt, "sort": sort})

    E, Q, O, R = CATS
    add("f_growth", "Growth leaders 30/30", E,
        "Revenue and net profit both up 30%+ on the same quarter last year, profitable over the last 4 quarters, RS 80+ and "
        "in Stage 2 (Deepvue's 30/30 screen).",
        (df.rev_yoy >= 30) & (df.pat_yoy >= 30) & (df.pat_ttm > 0) & (rs >= 80) & (st == 2), "Profit YoY %", df.pat_yoy, "pct", "rs")
    add("f_accel", "Earnings acceleration", E,
        "Year-on-year profit growth faster in each of the last three quarters (e.g. +15% → +30% → +50%), latest at least +20%, "
        "revenue up 10%+, RS 60+. O'Neil's strongest earnings signal — from NSE's quarterly filings.",
        (df.pat_yoy2 < df.pat_yoy1) & (df.pat_yoy1 < df.pat_yoy) & (df.pat_yoy >= 20) & (df.pat_yoy2 > 0) & (df.rev_yoy >= 10) & (rs >= 60),
        "Profit YoY %", df.pat_yoy)
    add("f_canslim", "CANSLIM-style leaders", E,
        "C: quarterly profit +25% on sales +20% · A: trailing-year profit +20% · N: within 15% of the 52-week high · "
        "L: RS 80+ · I: FII + DII holding up over the year (William O'Neil). Check the market (M) on the Breadth tab.",
        (df.pat_yoy >= 25) & (df.rev_yoy >= 20) & (df.pat_ttm_g >= 20) & (h52 >= -15) & (rs >= 80) & (df.inst_1y > 0),
        "Profit YoY %", df.pat_yoy, "pct", "rs")
    add("f_sepa", "SEPA: trend template + earnings", E,
        "Passes Minervini's trend template and the business backs it: profit +20% and revenue +15% on last year, ROE 15%+.",
        tt & (df.pat_yoy >= 20) & (df.rev_yoy >= 15) & (df.roe >= 15), "Profit YoY %", df.pat_yoy, "pct", "rs")
    add("f_margin", "Margin expansion", E,
        "Operating margin up 3+ points on the same quarter last year and up on a trailing-year basis, revenue growing 15%+, "
        "RS 75+ — operating leverage kicking in (not for lenders).",
        nb & (df.opm_chg >= 3) & (df.opm_ttm_chg > 0) & (df.rev_yoy >= 15) & (df.pat_ttm > 0) & (rs >= 75), "Margin change (pts)", df.opm_chg)
    add("f_streak", "Revenue growth streak", E,
        "Revenue up 10%+ year on year for 5+ quarters in a row, trailing-year profit up 20%+, RS 70+ and above the "
        "200 DMA — consistent growers the market is rewarding.",
        (df.rev_streak >= 5) & (df.pat_ttm_g >= 20) & (rs >= 70) & (a200 == True), "Quarters in a row", df.rev_streak, "int")
    add("f_turn", "Turnaround", E,
        "Profitable in the latest quarter and the one before, after a loss in the same quarter last year — and the stock is "
        "above its 50 DMA.",
        (df.pat_q > 0) & (df.pat_yoy.isna()) & (df.pat_qoq.notna() | (df.pat_q > 0)) & (ctx["a50"].reindex(U) == True)
        & (pd.Series([M.get(s, {}).get("pat_q") for s in U], index=U) > 0) & (df.pat_ttm.notna()),
        "Quarter profit ₹Cr", df.pat_q, "num")
    rec = pd.to_datetime(df["filed"], errors="coerce")
    days = (pd.Timestamp(ctx["dates"][-1]) - rec).dt.days
    # price reaction since the results day
    C = ctx["C"]
    pre = pd.Series(np.nan, index=U)
    for s in U:
        f = rec.get(s)
        if pd.notna(f) and s in C and days.get(s, 999) <= 20:
            before = C[s][C.index < f.strftime("%Y-%m-%d")]
            if len(before):
                pre[s] = before.iloc[-1]
    react = (c / pre - 1) * 100
    add("f_post", "Post-results breakout", E,
        "Results filed in the last 20 days with profit up 20%+, and the stock is 5%+ above its close before the results "
        "— the market is buying the numbers (earnings episodic pivot / post-earnings drift).",
        (days <= 20) & (df.pat_yoy >= 20) & (react >= 5), "Since results %", react)
    if "next_results" not in df:
        df["next_results"] = None
    nr = pd.to_datetime(df["next_results"], errors="coerce")
    dleft = (nr - pd.Timestamp(ctx["dates"][-1])).dt.days
    add("f_upcoming", "Results in the next 7 days", E,
        "Board meeting for results scheduled within a week (from NSE's corporate calendar). RS 60+ only — the strong stocks "
        "worth watching into results.",
        (dleft >= 0) & (dleft <= 7) & (rs >= 60), "Days to results", dleft, "int", "metric_asc")

    add("f_quality", "Quality compounders", Q,
        "ROCE 20%+, ROE 18%+, debt/equity 0.5 or less, positive free cash flow last year, operating margin 15%+, revenue up 12%+ "
        "on a trailing basis, price above the 200 DMA (not for banks).",
        nb & (df.get("roce") >= 20) & (df.roe >= 18) & (df.get("de") <= .5) & (df.get("fcf") > 0) & (df.get("opm_ttm") >= 15)
        & (df.rev_ttm_g >= 12) & (a200 == True), "ROCE %", df.get("roce"))
    add("f_garp", "Growth at a reasonable price", Q,
        "PEG 0.8 or less (P/E ÷ trailing profit growth), profit growth 20%+, ROE 15%+, P/E under 35, RS 60+ and above the "
        "200 DMA.",
        (df.peg <= .8) & (df.pat_ttm_g >= 20) & (df.roe >= 15) & (df.pe < 35) & (rs >= 60) & (a200 == True), "PEG", df.peg, "num", "metric_asc")
    add("f_capex", "Capex cycle", Q,
        "Capital work in progress is 15%+ of total assets — new capacity being built that isn't in the numbers yet — with "
        "debt/equity ≤ 1 and revenue growing.",
        nb & (df.get("cwip_pct") >= 15) & (df.get("de") <= 1) & (df.rev_ttm_g > 0), "CWIP % of assets", df.get("cwip_pct"))
    add("f_netcash", "Net-cash small caps", Q,
        "Cash above total borrowings, market cap under ₹5,000 Cr, positive free cash flow and P/E under 25.",
        nb & (df.get("cash") > df.get("debt").fillna(0)) & (mc < 5000) & (df.get("fcf") > 0) & (df.pe > 0) & (df.pe < 25), "P/E", df.pe, "num", "metric_asc")

    add("f_smart", "Smart-money accumulation", O,
        "FII + DII holding up 0.5+ points this quarter and 1+ point over the year while retail holding fell — institutions "
        "buying from individuals — in a Stage-2 stock.",
        (df.inst_1q >= .5) & (df.inst_1y >= 1) & (df.retail_1y < 0) & (st == 2), "Inst. Δ1Y (pts)", df.inst_1y)
    add("f_mf", "Mutual funds moving in", O,
        "Mutual-fund holding up 2+ points over the year and still rising this quarter, RS 60+ — domestic funds building "
        "positions in a stock that is already acting well.",
        (df.mf_1y >= 2) & (df.mf_1q > 0) & (rs >= 60), "MF Δ1Y (pts)", df.mf_1y)
    add("f_promoter", "Promoter buying", O,
        "Promoter stake up 0.5+ points this quarter or 1+ point over the year — insiders putting in money.",
        (df.promoter_1q >= .5) | (df.promoter_1y >= 1), "Promoter Δ1Y (pts)", df.promoter_1y)
    add("f_under", "Under-followed leaders", O,
        "FII + DII own less than 5%, profit up 25%+ on revenue up 15%+, Fund rating 70+ and RS 80+ — strong businesses the institutions haven't "
        "found yet.",
        (df.inst < 5) & (df.pat_yoy >= 25) & (df.rev_yoy >= 15) & (df.fr >= 70) & (rs >= 80), "Inst. holding %", df.inst, "pct", "rs")

    flags = pd.DataFrame(index=df.index)
    flags["Promoter stake down 2+ pts in a year"] = df.promoter_1y <= -2
    flags["Promoter and FII both selling this quarter"] = (df.promoter_1q < -.25) & (df.fii_1q < -.25)
    flags["Negative operating cash flow last year despite a profit"] = nb & (df.ocf < 0) & (df.ocf_pat.notna())
    flags["Debt/equity above 1.5 and rising"] = nb & (df.get("de") > 1.5) & (df.get("debt_chg") > 0)
    flags["Profit down 25%+ with revenue falling"] = (df.pat_yoy <= -25) & (df.rev_yoy < 0)
    # the two promoter flags usually describe the same sale - count them once
    prom = flags[["Promoter stake down 2+ pts in a year", "Promoter and FII both selling this quarter"]].any(axis=1)
    nflags = flags.drop(columns=["Promoter stake down 2+ pts in a year", "Promoter and FII both selling this quarter"]).sum(axis=1) + prom
    add("f_red", "Fundamental red flags", R,
        "Two or more different warning signs: promoter selling (or promoter and FIIs exiting together), "
        "rising high debt, negative operating cash flow despite a profit, or profit and revenue both falling. An exit check for holdings — open the stock card for which ones.",
        nflags >= 2, "Flags", nflags, "int")

    # ── per-stock fields for stocks.json
    keep = ["fr", "pe", "ps", "peg", "pb", "roe", "roce", "de", "opm", "opm_chg", "npm", "rev_yoy", "pat_yoy", "pat_yoy1", "pat_yoy2",
            "rev_qoq", "pat_qoq", "rev_ttm", "pat_ttm", "rev_ttm_g", "pat_ttm_g", "rev_streak", "fcf", "ocf_pat", "cwip_pct",
            "promoter", "fii", "dii", "mf", "retail", "inst", "promoter_1q", "promoter_1y", "fii_1q", "fii_1y", "dii_1y", "mf_1y",
            "inst_1q", "inst_1y", "retail_1y", "holders", "qe", "filed", "next_results", "shp_q", "bank", "fin", "fy", "roe_fy"]
    per = {}
    fl = flags.apply(lambda r: [k for k, v in r.items() if v is True or v == True], axis=1)
    for s in U:
        if s not in df.index or pd.isna(df.loc[s, "fr"]) and s not in M:
            continue
        row = {}
        for k in keep:
            if k not in df:
                continue
            v = df.loc[s, k]
            if isinstance(v, (float, np.floating)):
                if np.isfinite(v):
                    row[k] = round(float(v), 2)
            elif isinstance(v, (bool, np.bool_)):
                row[k] = bool(v)
            elif isinstance(v, (int, np.integer)):
                row[k] = int(v)
            elif isinstance(v, str):
                row[k] = v
        if fl.get(s):
            row["flags"] = fl[s]
        per[s] = row
    return {"per_stock": per, "detail": detail, "industry": industry, "meta": meta, "hits": hits, "metric": metric, "cats": CATS}
