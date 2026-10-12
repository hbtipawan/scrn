"""Quarterly results for the current results season, with a Result Quality Score and a PEAD score.

The season is the calendar quarter in which results are announced: results announced 1 Oct - 31 Dec
are one season (mostly the September quarter, Q2), 1 Jan - 31 Mar the next, and so on. The site shows
the current season and the one before it.

For each result (consolidated when the company files it, else standalone; comparisons only against
quarters filed on the same basis):
  Revenue, EBITDA (PBT - exceptional items + finance cost + depreciation - other income),
  net profit, EPS, each with YoY and QoQ change; EBITDA margin and its change in points.
  Banks: net interest income and operating profit before provisions. Other lenders: operating profit
  before tax, without adding back finance cost (it is their raw material).

Result Quality Score (0-100): is the quarter good, and is the profit real?  See quality_points().
PEAD score (0-9): how likely the price keeps drifting up after the result.    See pead_points().
Both were calibrated on NSE results from 2019 to 2026 (see config/results_evidence.json).

Event date: the first filing of the quarter's results (a revised filing keeps the original date), or
the results board meeting when it came 1-3 days earlier (the XBRL often follows the announcement by a
day). Filings more than 100 days after the quarter ended are left out (revisions of old quarters and
very late filers - the scores were tested on results filed 10-100 days after quarter end).
The price reaction is measured over two sessions from the first session on or after the event date,
which covers results released during market hours and after the close alike; the PEAD score is filled
in once both sessions are in (until then the card shows the points known before the reaction, of 6).
Results with no like-for-like quarter a year ago (new listing, or a switch to consolidated) are not rated.

The research behind the scores used these same functions (quarter_metrics, price_features,
quality_points, pead_points), so the site computes exactly what was tested.
"""
import json
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"
CMP = ["rev", "ebitda", "core", "pat", "eps", "oi", "exc", "tax", "pbt", "basis", "shares", "nii"]
LAGS = 9


# ───────────────────────────────────────────────────────── labels
def fy_label(qe):
    qe = pd.Timestamp(qe)
    fy = qe.year + 1 if qe.month >= 4 else qe.year
    q = ((qe.month - 4) % 12) // 3 + 1
    return f"Q{q} FY{fy % 100:02d}"


MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def season_of(d):
    d = pd.Timestamp(d)
    q0 = (d.month - 1) // 3 * 3 + 1
    start = pd.Timestamp(d.year, q0, 1)
    end = start + pd.offsets.QuarterEnd(0)
    # results announced in this window are mostly for the quarter that ended just before it
    main = fy_label(start - pd.Timedelta(days=1))
    return {"id": f"{d.year}-Q{(q0 - 1) // 3 + 1}", "start": str(start.date()), "end": str(end.date()),
            "label": f"{MON[q0 - 1]}–{MON[q0 + 1]} {d.year}", "main": main}


# ───────────────────────────────────────────────────────── fundamentals
def shares_count(H):
    """Shares = paid-up capital / face value, checked against profit / EPS (some filings give paid-up
    capital in lakh or face value in paise)."""
    sh_pv = H.paidup * 1e7 / H.fv.where(H.fv > 0)
    pe_ok = (H.eps.abs() >= 0.1) & (H.pat.abs() >= 0.5)
    sh_now = (H.pat * 1e7 / H.eps).where(pe_ok)
    sh_now = sh_now.where(sh_now > 0)
    sh_med = sh_now.groupby(H.symbol).transform(lambda s: s.rolling(4, min_periods=1).median())
    ok = (sh_pv / sh_now).between(0.6, 1.7) | (sh_pv / sh_med).between(0.6, 1.7) | sh_med.isna()
    out = pd.Series(np.where(ok, sh_pv, sh_now.fillna(sh_med)), index=H.index)
    return out.where(out > 0)


BONUS = np.array([1.25, 4 / 3, 1.5, 5 / 3, 2, 2.5, 3, 4, 5, 6, 10, 20])


def eps_adjust(ratio):
    """Divisor for an earlier EPS: the bonus/split ratio when the share count rose by (almost exactly)
    one, 1 for small changes, NaN (no comparison) for other large changes."""
    r = np.asarray(ratio, float)
    out = np.full(r.shape, np.nan)
    small = (r > 0.8) & (r < 1.2)
    out[small] = 1.0
    with np.errstate(all="ignore"):
        near = np.abs(r[:, None] / BONUS[None, :] - 1)
    k = np.nanargmin(np.where(np.isfinite(near), near, 9), axis=1)
    hit = (np.take_along_axis(near, k[:, None], 1)[:, 0] <= 0.005) & ~small
    out[hit] = BONUS[k[hit]]
    out[~np.isfinite(r)] = 1.0          # share count unknown: compare as reported
    return out


def quarter_metrics(H):
    """H: one row per stock per quarter (fund_results.csv columns, qe as Timestamp, finsec bool).
    Returns the same rows with YoY / QoQ changes, surprises, streaks and quality measures."""
    H = H.copy()
    for c in ("oi", "exc", "fin", "dep", "tax"):
        H[c] = H[c].fillna(0.0)
    H["isbank"] = H.bank.fillna(0).astype(int)
    H["core"] = H.pbt - H.exc                                          # profit before tax and exceptional items
    H["ebitda"] = np.where(H.isbank == 1, H.inc - H.exp,                # banks: operating profit before provisions
                           np.where(H.finsec, H.pbt - H.exc + H.dep - H.oi,      # other lenders
                                    H.pbt - H.exc + H.fin + H.dep - H.oi))
    H["nii"] = np.where(H.isbank == 1, H.rev - H.fin, np.nan)          # banks: net interest income
    H["shares"] = shares_count(H)
    H["qn"] = H.qe.dt.year * 4 + (H.qe.dt.month - 1) // 3
    key = H.set_index(["symbol", "qn"])
    lags = []
    for k in range(1, LAGS + 1):
        t = key[CMP].copy()
        t.index = pd.MultiIndex.from_arrays([t.index.get_level_values(0), t.index.get_level_values(1) + k])
        t.columns = [f"{c}_{k}" for c in CMP]
        lags.append(t)
    Z = key.join(lags)
    for k in range(1, LAGS + 1):                                       # compare only on the same basis
        bad = Z[f"basis_{k}"] != Z["basis"]
        for c in CMP:
            if c != "basis":
                Z.loc[bad, f"{c}_{k}"] = np.nan
    Z = Z.reset_index()

    def g(a, b):
        return np.where((b > 0) & np.isfinite(a), a / b - 1, np.nan)

    for c in ("rev", "ebitda", "core", "pat", "nii"):
        Z[f"{c}_yoy"] = g(Z[c], Z[f"{c}_4"])
        Z[f"{c}_qoq"] = g(Z[c], Z[f"{c}_1"])
        Z[f"{c}_yoy1"] = g(Z[f"{c}_1"], Z[f"{c}_5"])
        # change on the year scaled by last year's revenue: works when profit was near zero or a loss
        Z[f"{c}_d4r"] = (Z[c] - Z[f"{c}_4"]) / Z["rev_4"].where(Z["rev_4"] > 0)
        Z[f"{c}_d4r1"] = (Z[f"{c}_1"] - Z[f"{c}_5"]) / Z["rev_5"].where(Z["rev_5"] > 0)
        # standardised unexpected change: this year-on-year change against the spread of the
        # previous (up to five) year-on-year changes - seasonal random walk with drift
        d = np.column_stack([(Z[f"{c}_{k}"] - Z[f"{c}_{k + 4}"]).to_numpy(float) for k in range(1, 6)])
        n = np.isfinite(d).sum(1)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sd = np.nanstd(d, axis=1, ddof=1)
            mu = np.nanmean(d, axis=1)
        cur = (Z[c] - Z[f"{c}_4"]).to_numpy(float)
        ok = (n >= 3) & (sd > 0)
        Z[f"{c}_sue"] = np.where(ok, (cur - mu) / np.where(ok, sd, 1), np.nan)
    # EPS: adjust the earlier EPS for a bonus issue or split (share count up by an exact bonus/split ratio);
    # any other big change in the share count (new shares issued) leaves EPS growth blank
    Z["eps_4a"] = Z.eps_4 / eps_adjust(Z.shares / Z.shares_4)
    Z["eps_yoy"] = g(Z.eps, Z.eps_4a)
    Z["eps_1a"] = Z.eps_1 / eps_adjust(Z.shares / Z.shares_1)
    Z["eps_qoq"] = g(Z.eps, Z.eps_1a)
    with np.errstate(all="ignore"):
        Z["mgn"] = Z.ebitda / Z.rev.where(Z.rev > 0)
        Z["mgn_4"] = Z.ebitda_4 / Z.rev_4.where(Z.rev_4 > 0)
        Z["mgn_1"] = Z.ebitda_1 / Z.rev_1.where(Z.rev_1 > 0)
        prev = np.column_stack([(Z[f"ebitda_{k}"] / Z[f"rev_{k}"].where(Z[f"rev_{k}"] > 0)).to_numpy(float) for k in range(1, 5)])
        Z["mgn_hi4"] = (np.isfinite(prev).sum(1) >= 3) & (Z.mgn.to_numpy(float) >= np.max(np.where(np.isfinite(prev), prev, -np.inf), axis=1))
    Z["mgn_yoy"] = Z.mgn - Z.mgn_4
    Z["mgn_qoq"] = Z.mgn - Z.mgn_1
    # streaks: consecutive quarters, up to this one, with revenue / operating profit up on the year
    for name, c in (("rstreak", "rev"), ("streak", "ebitda")):
        s_ = np.zeros(len(Z), int)
        alive = np.ones(len(Z), bool)
        for k in range(0, 5):
            a = Z[c] if k == 0 else Z[f"{c}_{k}"]
            up = ((a > Z[f"{c}_{k + 4}"]) & a.notna() & Z[f"{c}_{k + 4}"].notna()).to_numpy()
            alive &= up
            s_ += alive
        Z[name] = s_
    with np.errstate(all="ignore"):
        Z["oi_sh"] = Z.oi / Z.pbt.where(Z.pbt > 0)
        Z["exc_sh"] = Z.exc / Z.pbt.abs().where(Z.pbt.abs() > 0)
        Z["etr"] = Z.tax / Z.pbt.where(Z.pbt > 0)
        Z["etr_4"] = Z.tax_4 / Z.pbt_4.where(Z.pbt_4 > 0)
        Z["ocf_pat"] = Z.ocf / Z.ytd_pat.where(Z.ytd_pat > 0) if "ocf" in Z else np.nan
    Z["turn"] = (Z.pat > 0) & (Z.pat_4 <= 0)
    Z["toloss"] = (Z.pat <= 0) & (Z.pat_4 > 0)
    Z["dil"] = Z.shares / Z.shares_4 - 1
    return Z


# ───────────────────────────────────────────────────────── price reaction
def event_index(d, event):
    """First session on or after the announcement day."""
    i = int(np.searchsorted(d, np.datetime64(pd.Timestamp(event).date()), "left"))
    return i


def price_features(d, o, h, l, c, v, b, ia):
    """Reaction and context at session ia (first session on/after the result). Needs ia >= 61."""
    p0 = c[ia - 1]
    two = ia + 1 < len(c)
    j = ia + 1 if two else ia
    rec = {"p0": p0, "two": bool(two)}
    rec["ear"] = (c[j] / p0 - 1) - (b[j] / b[ia - 1] - 1)               # 2-session reaction, excess vs NIFTY 500
    rec["ear0"] = (c[ia] / p0 - 1) - (b[ia] / b[ia - 1] - 1)
    rec["gap"] = o[ia] / p0 - 1
    hi, lo = np.nanmax(h[ia:j + 1]), np.nanmin(l[ia:j + 1])
    rec["cl1"] = (c[j] - lo) / (hi - lo) if hi > lo else 0.5            # where the reaction closed in its range
    med = np.nanmedian(v[max(0, ia - 60):ia - 5])
    rec["vr"] = np.nanmax(v[ia:j + 1]) / med if med > 0 else np.nan
    rec["pre20"] = (c[ia - 1] / c[ia - 21] - 1) - (b[ia - 1] / b[ia - 21] - 1)
    rec["r250"] = c[ia - 1] / c[ia - 251] - 1 if ia >= 251 else np.nan
    rec["b250"] = b[ia - 1] / b[ia - 251] - 1 if ia >= 251 else np.nan
    rec["hi52"] = c[ia - 1] / np.nanmax(c[max(0, ia - 250):ia]) - 1
    sma = np.nanmean(c[ia - 200:ia]) if ia >= 200 else np.nan
    rec["a200"] = c[ia - 1] / sma - 1 if np.isfinite(sma) else np.nan
    rec["to50"] = np.nanmedian((c * v / 1e7)[max(0, ia - 50):ia])
    return rec


# ───────────────────────────────────────────────────────── scores
def _f(row, k):
    v = row.get(k)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return np.nan
    return v if np.isfinite(v) else np.nan


def _step(v, cuts, pts, missing=0):
    """points for the first cut v reaches (cuts descending)."""
    if not np.isfinite(v):
        return missing
    for c, p in zip(cuts, pts):
        if v >= c:
            return p
    return pts[-1] if len(pts) > len(cuts) else 0


QUALITY_PARTS = [
    ("Revenue growth", 20, "Revenue vs the same quarter last year (banks: net interest income). 50%+ 20 · 30%+ 18 · 20%+ 16 · 12%+ 13 · 6%+ 9 · up 5 · down up to 10% 2 · worse 0."),
    ("Operating profit growth", 20, "EBITDA vs the same quarter last year (banks: operating profit before provisions). 40%+ 20 · 25%+ 17 · 15%+ 15 · 5%+ 11 · up 7 · down up to 15% 3. From a loss: back to profit 16, smaller loss 6."),
    ("Margins", 20, "10 if the margin is the highest of the last five quarters, plus the change on the year: +1 pt or more 10 · up 7 · down up to 1 pt 4 · down up to 3 pts 2."),
    ("Consistency", 20, "Quarters in a row with operating profit up on the year: 1 = 8 · 2 = 11 · 3+ = 14. Plus revenue growth speeding up (3+ pts faster than last quarter) 6, or holding 3."),
    ("Clean profit", 20, "Starts at 20. Net loss −10 · exceptional gain over 10% of PBT −5 · tax rate under 10% −4 · other income over 30% of PBT −4 (over 50% −6). 8 or less caps the score at 54 (WEAK)."),
]
PEAD_PARTS = [
    ("Profit surprise", 2, "EBITDA change on the year against the spread of its last five yearly changes (standardised unexpected earnings): 1.0+ 2 · 0+ 1. Under 3 years of comparable history: EBITDA change of 3%+ of last year's revenue 2 · any rise 1."),
    ("Profit jump vs share price", 1, "Rise in quarterly net profit on the year worth 0.5% or more of the market value before the result."),
    ("Revenue surprise", 2, "Same test on revenue: 1.5+ 2 · 0+ 1. Short history: revenue growth 25%+ 2 · 8%+ 1."),
    ("Price reaction", 2, "Return over the first two sessions after the result, minus NIFTY 500: +4% or more 2 · +1% or more 1."),
    ("Strong close", 1, "Closed in the top 30% of the two sessions' high-low range."),
    ("Near the 52-week high", 1, "Before the result the stock was within 10% of its 52-week closing high."),
]


def grade(q):
    return None if q is None else "ex" if q >= 85 else "vg" if q >= 70 else "gd" if q >= 55 else "wk" if q >= 40 else "vw"


def quality_points(row):
    """Result Quality Score 0-100 -> (score, [points per part], [flags])."""
    bank = row.get("isbank") == 1
    rev_y = _f(row, "nii_yoy") if bank else _f(row, "rev_yoy")
    p_rev = _step(rev_y, [.50, .30, .20, .12, .06, 0, -.10], [20, 18, 16, 13, 9, 5, 2], missing=5)
    eb, eb4, eb_y = _f(row, "ebitda"), _f(row, "ebitda_4"), _f(row, "ebitda_yoy")
    flags = []
    if np.isfinite(eb_y):
        p_eb = _step(eb_y, [.40, .25, .15, .05, 0, -.15], [20, 17, 15, 11, 7, 3])
    elif np.isfinite(eb4) and np.isfinite(eb):            # last year was a loss (or zero)
        p_eb = 16 if eb > 0 else 6 if eb > eb4 else 0
        if eb > 0:
            flags.append("+Operating loss turned to profit")
    else:
        p_eb = 6
    hi = bool(row.get("mgn_hi4"))
    p_m = (10 if hi else 0) + _step(_f(row, "mgn_yoy"), [.01, 0, -.01, -.03], [10, 7, 4, 2], missing=3)
    stk = _f(row, "streak")
    stk = int(stk) if np.isfinite(stk) else 0
    acc = rev_y - (_f(row, "nii_yoy1") if bank else _f(row, "rev_yoy1"))
    p_c = {0: 0, 1: 8, 2: 11}.get(stk, 14) + (6 if acc >= .03 else 3 if acc >= 0 else 0)
    clean = 20
    pbt, pat = _f(row, "pbt"), _f(row, "pat")
    if np.isfinite(pat) and pat <= 0:
        clean -= 10
        flags.append("!Net loss")
    ex = _f(row, "exc_sh")
    if np.isfinite(ex) and ex > .10:
        clean -= 5
        flags.append(f"!Exceptional gain {ex * 100:.0f}% of PBT")
    elif np.isfinite(ex) and ex < -.10:
        flags.append(f"Exceptional charge {abs(ex) * 100:.0f}% of PBT")
    etr = _f(row, "etr")
    if np.isfinite(etr) and pbt > 0 and etr < .10:
        clean -= 4
        flags.append(f"!Tax rate only {max(etr, 0) * 100:.0f}%")
    oi = _f(row, "oi_sh")
    if not row.get("finsec") and np.isfinite(oi) and oi > .30:
        clean -= 6 if oi > .5 else 4
        flags.append(f"!Other income {oi * 100:.0f}% of PBT")
    clean = max(clean, 0)
    if hi:
        flags.append("+Best margin in 5 quarters")
    if stk >= 4:
        flags.append(f"+Operating profit up {stk if stk < 5 else '5+'} quarters running")
    parts = [int(p_rev), int(p_eb), int(p_m), int(p_c), int(clean)]
    q = int(sum(parts))
    if clean <= 8:
        q = min(q, 54)                     # a failed forensic check caps the grade at WEAK
    return q, parts, flags


def pead_points(row, rec):
    """PEAD score 0-9 -> (score, [points per part]). rec: price reaction (price_features)."""
    sue = _f(row, "ebitda_sue")
    if np.isfinite(sue):
        p1 = _step(sue, [1, 0], [2, 1])
    else:
        p1 = _step(_f(row, "ebitda_d4r"), [.03, 0], [2, 1])
    mc = _f(rec, "mcap")
    jump = (_f(row, "pat") - _f(row, "pat_4")) / mc if mc and mc > 0 else np.nan
    p2 = 1 if jump >= .005 else 0
    rsue = _f(row, "rev_sue")
    p3 = _step(rsue, [1.5, 0], [2, 1]) if np.isfinite(rsue) else _step(_f(row, "rev_yoy"), [.25, .08], [2, 1])
    p4 = _step(_f(rec, "ear"), [.04, .01], [2, 1])
    p5 = 1 if _f(rec, "cl1") >= .7 else 0
    p6 = 1 if _f(rec, "hi52") >= -.10 else 0
    parts = [int(p1), int(p2), int(p3), int(p4), int(p5), int(p6)]
    return int(sum(parts)), parts


# ───────────────────────────────────────────────────────── site build
def _r(v, nd=1):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    v = round(v, nd)
    return int(v) if nd == 0 else v


def _pct(v, nd=1):
    return _r(v * 100, nd) if v is not None and np.isfinite(v) else None


def today_ist():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


def load_quarters():
    R = pd.read_csv(CFG / "fund_results.csv", dtype={"symbol": str})
    info = pd.read_csv(CFG / "fund_info.csv", dtype={"symbol": str}).set_index("symbol")
    R["qe"] = pd.to_datetime(R.qe)
    fin_sec = info["sector"].astype(str).str.contains("Financial", na=False) if "sector" in info else pd.Series(dtype=bool)
    R["finsec"] = R.symbol.map(fin_sec).fillna(False).astype(bool) | (R.bank.fillna(0) == 1)
    return R, info


def event_dates(Z, info):
    """First filing date, or the results board meeting date when it came up to 3 days earlier."""
    filed = pd.to_datetime(Z.first_filed if "first_filed" in Z else Z.filed, errors="coerce")
    filed = filed.fillna(pd.to_datetime(Z.filed, errors="coerce"))
    mtg = pd.to_datetime(Z.symbol.map(info["last_results"]) if "last_results" in info else pd.Series(pd.NaT, index=Z.index), errors="coerce")
    use = mtg.notna() & (filed - mtg).dt.days.between(1, 3)
    return filed.where(~use, mtg)


def build(W, U, ctx):
    """W: wide price frames (open/high/low/close/volume, date index); U: universe symbols;
    ctx: bench (name), names, mcap (Series), today (date, optional)."""
    import time
    t0 = time.time()
    R, info = load_quarters()
    Z = quarter_metrics(R)
    Z["event"] = event_dates(Z, info)
    Z["late"] = (pd.to_datetime(Z.filed, errors="coerce") - Z.event).dt.days
    today = ctx.get("today") or today_ist()
    cur = season_of(today)
    prev = season_of(pd.Timestamp(cur["start"]) - pd.Timedelta(days=1))
    seasons = [cur, prev]
    lo = pd.Timestamp(prev["start"])
    days = (Z.event - Z.qe).dt.days
    # on-time results only: a filing more than 100 days after the quarter ended is a revision of an
    # older result or a very late filer (the scores were tested on results 10-100 days after quarter end)
    sel = Z[(Z.event >= lo) & days.between(0, 100) & Z.symbol.isin(set(U))].copy()
    C, O, Hh, L, V = (W[k] for k in ("close", "open", "high", "low", "volume"))
    dates = pd.to_datetime(pd.Index(C.index)).values
    bench = C[ctx["bench"]].ffill().to_numpy(float) if ctx["bench"] in C else None
    names = ctx.get("names", {})
    mcap = ctx.get("mcap", pd.Series(dtype=float))
    rows, per = [], {}
    for r in sel.itertuples():
        s = r.symbol
        if s not in C or bench is None:
            continue
        c = C[s].to_numpy(float)
        ia = event_index(dates, r.event)
        rec = None
        if 61 <= ia and ia + 1 < len(c) and np.isfinite(c[ia - 1]):     # the two reaction sessions are in
            rec = price_features(dates, O[s].to_numpy(float), Hh[s].to_numpy(float), L[s].to_numpy(float), c, V[s].to_numpy(float), bench, ia)
            rec["since"] = (c[-1] / rec["p0"] - 1) - (bench[-1] / bench[ia - 1] - 1) if np.isfinite(c[-1]) else np.nan
            rec["mcap"] = rec["p0"] * r.shares / 1e7 if np.isfinite(r.shares) else np.nan
        row = r._asdict()
        hist = bool(np.isfinite(r.rev_yoy) or np.isfinite(r.ebitda_4) or (r.isbank == 1 and np.isfinite(r.nii_yoy)))
        if hist and np.isfinite(r.pat):
            qs, qparts, flags = quality_points(row)
        else:                                # nothing like-for-like a year ago (new listing / new basis)
            qs, qparts, flags = None, None, ["No like-for-like quarter a year ago"]
        pre = None
        if rec is not None and hist:
            ps, pparts = pead_points(row, rec)
        else:
            ps, pparts = None, None
            if hist:                         # points known before the reaction (max 6 of 9)
                c_ = c[:ia] if ia <= len(c) else c
                hi52 = c_[-1] / np.nanmax(c_[-250:]) - 1 if len(c_) > 1 and np.isfinite(c_[-1]) else np.nan
                mc0 = c_[-1] * r.shares / 1e7 if len(c_) and np.isfinite(r.shares) else np.nan
                _, pp_ = pead_points(row, {"mcap": mc0, "hi52": hi52, "ear": np.nan, "cl1": np.nan})
                pre = int(pp_[0] + pp_[1] + pp_[2] + pp_[5])
        fin = 1 if r.isbank == 1 else 2 if r.finsec else 0
        tile_rev = r.nii if fin == 1 else r.rev
        out = {"s": s, "n": names.get(s, ""), "sn": season_of(r.event)["id"], "d": str(pd.Timestamp(r.event).date()),
               "filed": str(r.filed)[:10],
               "late": bool((pd.Timestamp(r.event) - pd.Timestamp(r.qe)).days > (60 if pd.Timestamp(r.qe).month == 3 else 45)),
               "q": fy_label(r.qe), "qe": str(pd.Timestamp(r.qe).date()), "b": r.basis, "fin": fin,
               "rev": _r(tile_rev, 2), "rev_y": _pct(r.nii_yoy if fin == 1 else r.rev_yoy), "rev_q": _pct(r.nii_qoq if fin == 1 else r.rev_qoq),
               "eb": _r(r.ebitda, 2), "eb_y": _pct(r.ebitda_yoy), "eb_q": _pct(r.ebitda_qoq),
               "np": _r(r.pat, 2), "np_y": _pct(r.pat_yoy), "np_q": _pct(r.pat_qoq),
               "eps": _r(r.eps, 2), "eps_y": _pct(r.eps_yoy), "eps_q": _pct(r.eps_qoq),
               "m": _pct(r.mgn), "m_y": _pct(r.mgn_yoy), "m_q": _pct(r.mgn_qoq),
               "qs": qs, "qp": qparts, "flags": flags, "pead": ps, "pp": pparts, "pend": rec is None and hist, "pre": pre,
               "two": bool(rec["two"]) if rec else False,
               "ear": _pct(rec["ear"]) if rec else None, "vr": _r(rec["vr"], 1) if rec else None,
               "since": _pct(rec["since"]) if rec else None,
               "mc": _r(mcap.get(s), 0) if s in mcap else (_r(rec["mcap"], 0) if rec else None)}
        rows.append(out)
    rows.sort(key=lambda x: (x["d"], x["qs"] or 0), reverse=True)
    for x in rows:                       # latest result of the current season, for the stock window and scanners
        if x["sn"] == cur["id"] and x["s"] not in per:
            per[x["s"]] = {"rq": x["qs"], "rp": x["pead"], "rd": x["d"]}
    due = []
    if "next_results" in info:
        nx = pd.to_datetime(info["next_results"], errors="coerce")
        nx = nx[(nx >= pd.Timestamp(today)) & (nx <= pd.Timestamp(today) + pd.Timedelta(days=14)) & nx.index.isin(set(U))]
        due = [[s, str(d.date())] for s, d in nx.sort_values().items()]
    ev_file = CFG / "results_evidence.json"
    evidence = json.loads(ev_file.read_text()) if ev_file.exists() else None
    ncur = sum(1 for x in rows if x["sn"] == cur["id"])
    print(f"results: {ncur} this season ({cur['label']}), {len(rows) - ncur} last season, {len(due)} due in 14 days, {time.time() - t0:.0f}s")
    return {"asof": str(today), "seasons": seasons, "rows": rows, "due": due, "evidence": evidence, "per_stock": per}


def scans(B):
    rows = [r for r in B["rows"] if r["sn"] == B["seasons"][0]["id"]]
    seen, hits = set(), {"res_strong": [], "res_quality": []}
    metric = {"res_strong": {}, "res_quality": {}}
    for r in rows:                       # latest result per stock
        if r["s"] in seen:
            continue
        seen.add(r["s"])
        if r["qs"] is not None and r["qs"] >= 70 and r["pead"] is not None and r["pead"] >= 7:
            hits["res_strong"].append(r["s"])
            metric["res_strong"][r["s"]] = float(r["pead"])
        if r["qs"] is not None and r["qs"] >= 85:
            hits["res_quality"].append(r["s"])
            metric["res_quality"][r["s"]] = float(r["qs"])
    meta = [{"id": "res_strong", "name": "Strong results, PEAD 7+", "cat": "Results",
             "desc": "Announced results this season with a Result Quality Score of 70+ and a PEAD score of 7+ out of 9 - "
                     "a real, broad-based beat that the market has started to reward. See the Results tab for the evidence.",
             "metric": "PEAD score", "fmt": "int", "sort": "metric"},
            {"id": "res_quality", "name": "Excellent results (Quality 85+)", "cat": "Results",
             "desc": "This season's results with a Result Quality Score of 85 or more: strong growth in revenue and operating profit, "
                     "margins up, clean profit (little other income or one-offs) and a growth streak.",
             "metric": "Result Quality", "fmt": "int", "sort": "metric"}]
    for k in hits:
        hits[k] = sorted(hits[k])
    return meta, hits, metric
