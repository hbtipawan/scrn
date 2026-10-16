"""Fund flows: what mutual funds bought and sold, stock by stock, month by month.

Input  config/mf/YYYY-MM/<fund house>.csv.gz  (from fetch_mf.py: every scheme's equity holdings on the last day
       of the month) + cache/prices.csv.gz + config/mcap_nse.csv + AMFI scheme list (categories).
Output config/mf/site/mf.json         per stock: 12 months of net buying, buyers / sellers, holders, streak, size
       config/mf/site/mf_detail.json  per stock: which schemes bought or sold it in the latest month

How a flow is measured (the rules that keep it honest):
  * Shares, not rupees. A holding's value moves with the price; the share count moves only when the fund trades.
  * Same scheme, both months. A scheme counts only when it is in the previous month's file too (matched by name,
    or by an almost identical portfolio when it was renamed). A scheme missing in either month adds nothing, so a
    file that failed to download can never look like a sale.
  * A fund house counts only when both its months were read completely.
  * Bonus issues and splits: share counts are put on today's basis using the price in the file itself
    (value / quantity) against the split-adjusted close, so a 1:1 bonus is not read as every fund buying.
  * New schemes (NFO money being invested) are left out for their first three months. A scheme whose equity more
    than doubles in a month (a merger into it) is left out for that month.
  * Newly listed stocks (IPO, demerger) show holders but no "buying" in the month they list — allotment is not a
    trade in the market.
  * Active funds are counted on their own. Index funds / ETFs (they buy whatever money comes in), arbitrage funds
    and hedged hybrids (balanced advantage, equity savings, multi-asset) are reported separately.
"""
import calendar
import datetime as dt
import gzip
import io
import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MF = ROOT / "config" / "mf"
OUT = ROOT / "config" / "mf" / "site"          # committed; compute.py copies these into docs/data each day
CACHE = ROOT / "cache"
MONTHS_SHOWN = 12          # monthly bars on the site

BRAND = {"sbi": "SBI", "icici": "ICICI Prudential", "hdfc": "HDFC", "nippon": "Nippon India", "kotak": "Kotak",
         "axis": "Axis", "absl": "Aditya Birla SL", "uti": "UTI", "mirae": "Mirae Asset", "dsp": "DSP", "tata": "Tata",
         "ppfas": "Parag Parikh", "motilal": "Motilal Oswal", "invesco": "Invesco", "canara": "Canara Robeco",
         "hsbc": "HSBC", "franklin": "Franklin", "quant": "quant", "baroda": "Baroda BNP", "groww": "Groww",
         "helios": "Helios", "shriram": "Shriram", "nj": "NJ", "capitalmind": "Capitalmind", "samco": "Samco",
         "bandhan": "Bandhan", "whiteoak": "WhiteOak", "pgim": "PGIM India", "sundaram": "Sundaram", "lic": "LIC",
         "boi": "Bank of India", "bajaj": "Bajaj Finserv", "360one": "360 ONE", "oldbridge": "Old Bridge",
         "angelone": "Angel One", "edelweiss": "Edelweiss", "mahindra": "Mahindra Manulife", "jm": "JM Financial",
         "union": "Union", "iti": "ITI", "quantum": "Quantum", "zerodha": "Zerodha", "navi": "Navi", "jio": "Jio BlackRock"}
AMC_WORDS = {"sbi": "sbi", "icici": "icici prudential pru", "hdfc": "hdfc", "nippon": "nippon india reliance", "kotak": "kotak mahindra",
             "axis": "axis", "absl": "aditya birla sun life", "uti": "uti", "mirae": "mirae asset", "dsp": "dsp", "tata": "tata",
             "ppfas": "parag parikh ppfas", "motilal": "motilal oswal", "invesco": "invesco india", "canara": "canara robeco",
             "hsbc": "hsbc", "franklin": "franklin india templeton", "quant": "quant", "baroda": "baroda bnp paribas",
             "groww": "groww", "helios": "helios", "shriram": "shriram", "nj": "nj", "capitalmind": "capitalmind",
             "samco": "samco", "bandhan": "bandhan", "whiteoak": "whiteoak capital", "pgim": "pgim india", "sundaram": "sundaram",
             "lic": "lic mf", "boi": "bank of india", "bajaj": "bajaj finserv", "360one": "360 one", "oldbridge": "old bridge",
             "angelone": "angel one", "edelweiss": "edelweiss", "mahindra": "mahindra manulife", "jm": "jm financial",
             "union": "union", "iti": "iti", "quantum": "quantum", "zerodha": "zerodha", "navi": "navi", "jio": "jio blackrock"}
AMFI_AMC = {"sbi": "SBI Mutual Fund", "icici": "ICICI Prudential Mutual Fund", "hdfc": "HDFC Mutual Fund", "nippon": "Nippon India Mutual Fund",
            "kotak": "Kotak Mahindra Mutual Fund", "axis": "Axis Mutual Fund", "absl": "Aditya Birla Sun Life Mutual Fund",
            "uti": "UTI Mutual Fund", "mirae": "Mirae Asset Mutual Fund", "dsp": "DSP Mutual Fund", "tata": "Tata Mutual Fund",
            "ppfas": "PPFAS Mutual Fund", "motilal": "Motilal Oswal Mutual Fund", "invesco": "Invesco Mutual Fund",
            "canara": "Canara Robeco Mutual Fund", "hsbc": "HSBC Mutual Fund", "franklin": "Franklin Templeton Mutual Fund",
            "quant": "quant Mutual Fund", "baroda": "Baroda BNP Paribas Mutual Fund", "groww": "Groww Mutual Fund",
            "helios": "Helios Mutual Fund", "shriram": "Shriram Mutual Fund", "nj": "NJ Mutual Fund", "capitalmind": "Capitalmind Mutual Fund",
            "samco": "Samco Mutual Fund", "bandhan": "Bandhan Mutual Fund", "whiteoak": "WhiteOak Capital Mutual Fund",
            "pgim": "PGIM India Mutual Fund", "sundaram": "Sundaram Mutual Fund", "lic": "LIC Mutual Fund", "boi": "Bank of India Mutual Fund",
            "bajaj": "Bajaj Finserv Mutual Fund", "360one": "360 ONE Mutual Fund", "oldbridge": "Old Bridge Mutual Fund",
            "angelone": "Angel One Mutual Fund", "edelweiss": "Edelweiss Mutual Fund", "mahindra": "Mahindra Manulife Mutual Fund",
            "jm": "JM Financial Mutual Fund", "union": "Union Mutual Fund", "iti": "ITI Mutual Fund", "quantum": "Quantum Mutual Fund",
            "zerodha": "Zerodha Mutual Fund", "navi": "Navi Mutual Fund", "jio": "Jio BlackRock Mutual Fund"}

NICE = [1.25, 4 / 3, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 20, 25, 50, 100]


# ═══════════════════════════════════════════════ helpers
def ym_list():
    out = []
    for d in sorted(MF.glob("20[0-9][0-9]-[01][0-9]")):
        if any(d.glob("*.csv.gz")):
            out.append(d.name)
    return out


def prev_ym(ym):
    y, m = map(int, ym.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def month_end(ym):
    y, m = map(int, ym.split("-"))
    return f"{ym}-{calendar.monthrange(y, m)[1]:02d}"


def norm_name(s, amc=""):
    """Comparable scheme name: lower case, brand words, descriptors and filler removed, 'smallcap' = 'small cap'."""
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(s or ""))           # 'OswalBSE' -> 'Oswal BSE'
    s = s.lower().replace("&amp;", "&")
    s = re.sub(r"\[[^\]]*\]", " ", s)                                  # "[HDFCRETHEP]" codes
    s = re.sub(r"\(\s*(?:formerly|erstwhile|earlier|previously|\*?earlier|an? open|an? close|the)[^)]*\)?", " ", s)
    s = re.sub(r"\s(an?\s)?(open|close)[\s\-]ended.*$", " ", s)
    s = re.sub(r"(small|mid|large|flexi|multi|micro)\s*cap", r"\1 cap", s)
    s = re.sub(r"(nifty|sensex|bse)\s*(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)\s*(etf|index)", r"\1 \2", s)
    s = s.replace("&", " and ")
    for w in AMC_WORDS.get(amc, "").split():
        s = re.sub(rf"\b{re.escape(w)}\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(fund|the|scheme|mutual|mf|an|of|ltd|limited|monthly|portfolio|disclosure|as|on|series)\b", " ", s)
    s = re.sub(r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
               r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b", " ", s)
    s = re.sub(r"\b(19|20)\d{2}\b|\b\d{1,2}(st|nd|rd|th)\b", " ", s)
    return " ".join(s.split())


SD_AMC = {"sbi": "SBI Funds", "icici": "ICICI Prudential", "hdfc": "HDFC Asset", "nippon": "Nippon Life", "kotak": "Kotak Mahindra",
          "axis": "Axis Asset", "absl": "Aditya Birla", "uti": "UTI Asset", "mirae": "Mirae Asset", "dsp": "DSP Asset",
          "tata": "Tata Asset", "ppfas": "PPFAS", "motilal": "Motilal Oswal", "invesco": "Invesco", "canara": "Canara Robeco",
          "hsbc": "HSBC", "franklin": "Franklin Templeton", "quant": "quant Money", "baroda": "Baroda BNP", "groww": "Groww",
          "helios": "Helios", "shriram": "Shriram", "nj": "NJ Asset", "capitalmind": "Capitalmind", "samco": "Samco",
          "bandhan": "Bandhan", "whiteoak": "WhiteOak", "pgim": "PGIM", "sundaram": "Sundaram", "lic": "LIC Mutual",
          "boi": "Bank of India", "bajaj": "Bajaj Finserv", "360one": "360 ONE", "oldbridge": "Old Bridge",
          "angelone": "Angel One", "edelweiss": "Edelweiss", "mahindra": "Mahindra Manulife", "jm": "JM Financial",
          "union": "Union Asset", "iti": "ITI Asset", "quantum": "Quantum", "zerodha": "Zerodha", "navi": "Navi",
          "jio": "Jio BlackRock"}


def _date(s):
    try:
        return pd.Timestamp(dt.datetime.strptime(str(s).strip(), "%d-%b-%Y"))
    except (TypeError, ValueError):
        return None


def load_amfi():
    """{amc: [(norm name, official name, category, allotment date or None)]}.

    AMFI's scheme list (cache/amfi_schemes.csv, from DownloadSchemeData) carries each scheme's category and its NFO
    dates; allotment is taken as 5 days after the NFO closed (launch + 20 days when the closing date is blank).
    AMFI's NAVAll.txt is the fallback (categories only)."""
    out = defaultdict(list)
    f, keep = CACHE / "amfi_schemes.csv", MF / "amfi_schemes_min.csv.gz"     # the small copy is committed as a fallback
    d = None
    if f.exists():
        try:
            d = pd.read_csv(f, dtype=str)
            d.columns = [c.strip() for c in d.columns]
            d = d.drop_duplicates(["AMC", "Scheme Name"])[["AMC", "Scheme Name", "Scheme Category", "Launch Date", "Closure Date"]]
            if len(d) > 1000:
                d.to_csv(keep, index=False, compression={"method": "gzip", "mtime": 0})
        except Exception as e:
            print(f"AMFI scheme list unreadable ({e}); using the saved copy")
            d = None
    if d is None and keep.exists():
        d = pd.read_csv(keep, dtype=str)
    if d is not None:
        for code, word in SD_AMC.items():
            g = d[d.AMC.str.contains(word, case=False, na=False, regex=False)]
            for nm, cat, ld, cd in zip(g["Scheme Name"], g["Scheme Category"], g["Launch Date"], g["Closure Date"]):
                nm = str(nm).strip()
                close = _date(cd) or (_date(ld) + pd.Timedelta(days=15) if _date(ld) else None)
                out[code].append((norm_name(nm, code), nm, str(cat or ""), close + pd.Timedelta(days=5) if close else None))
        if out:
            return out
    f = CACHE / "amfi_navall.txt"
    if not f.exists():
        return out
    cat = amc = None
    seen = set()
    rev = {v: k for k, v in AMFI_AMC.items()}
    for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        if ";" not in line:
            if re.match(r"(Open|Close|Interval) Ended Schemes", line):
                cat = line
            else:
                amc = line
            continue
        p = line.split(";")
        if p[0] == "Scheme Code" or len(p) < 6:
            continue
        code = rev.get(amc)
        name = p[3].strip()
        if not code or (code, name) in seen:
            continue
        seen.add((code, name))
        nm = re.sub(r"\s*[-–]\s*(direct|regular|growth|idcw|dividend).*$", "", name, flags=re.I)
        out[code].append((norm_name(nm, code), nm, cat or "", None))
    return out


def classify(name, cat):
    """active / passive / hybrid / arbitrage / other, from the AMFI category when known, else from the name."""
    n = name.lower() if isinstance(name, str) else ""
    c = cat.lower() if isinstance(cat, str) else ""
    if re.search(r"\barbitrage\b", n) or "arbitrage" in c:
        return "arbitrage"
    if re.search(r"index fund|\betf\b|exchange traded|\bbees\b", n) or "index fund" in c or "etf" in c:
        return "passive"
    if re.search(r"fund of funds?|\bfof\b", n) or "fund of fund" in c or "fof" in c:
        return "other"
    if re.search(r"balanced advantage|dynamic asset|equity savings|multi[\s\-]?asset|conservative hybrid|balanced hybrid|"
                 r"hybrid[\s\-]*debt|debt plan|income plus|regular savings|asset allocat", n) or \
            re.search(r"balanced advantage|dynamic asset|equity savings|multi asset|conservative hybrid|balanced hybrid", c):
        return "hybrid"
    if re.search(r"debt|income|liquid|gilt|money market|overnight|bond|duration|credit|floater|fixed (term|maturity)|fmp", c) and "equity" not in c:
        return "other"
    if re.search(r"\b(nifty|sensex|bse)\b", n) and not re.search(r"\bfund\b.*\bfund\b", n):
        return "passive"
    return "active"


def snap_factor(f):
    """File price ÷ split-adjusted close → 1 (no change) or a bonus / split ratio. Only ratios that raise the share
    count are accepted (reverse splits are rare here; a lower file price is more often a stale or wrong price)."""
    if not np.isfinite(f) or f <= 0:
        return None
    if abs(f - 1) <= 0.03:
        return 1.0
    for k in NICE:
        if abs(f / k - 1) <= 0.03:
            return k
    return None


# ═══════════════════════════════════════════════ load
def load_months(months):
    """Holdings for every month: DataFrame amc, scheme, isin9, qty, value_cr (equity only) + futures exposure,
    and {(ym, amc): complete?}."""
    eq, fut, complete = [], [], {}
    for ym in months:
        for f in sorted((MF / ym).glob("*.csv.gz")):
            code = f.name.split(".")[0]
            meta_f = f.with_name(code + ".json")
            meta = json.loads(meta_f.read_text()) if meta_f.exists() else {}
            complete[(ym, code)] = bool(meta.get("complete", True))
            d = pd.read_csv(f, dtype={"isin": str, "scheme": str})
            d["ym"], d["amc"] = ym, code
            d["scheme"] = d["scheme"].fillna("(unnamed)").astype(str)
            e = d[d.kind == "eq"].copy()
            e["isin9"] = e["isin"].str[:9]
            eq.append(e[["ym", "amc", "scheme", "isin9", "qty", "value_cr"]])
            fu = d[d.kind == "fut"].copy()
            if len(fu):
                fut.append(fu[["ym", "amc", "scheme", "qty", "value_cr"]])
    E = pd.concat(eq, ignore_index=True)
    E = E.groupby(["ym", "amc", "scheme", "isin9"], as_index=False)[["qty", "value_cr"]].sum()   # a stock listed twice in one scheme
    F = pd.concat(fut, ignore_index=True) if fut else pd.DataFrame(columns=["ym", "amc", "scheme", "qty", "value_cr"])
    return E, F, complete


def load_prices(months):
    lst = pd.read_csv(CACHE / "equity_l.csv")
    lst.columns = [c.strip() for c in lst.columns]
    sym_isin = dict(zip(lst["SYMBOL"], lst["ISIN NUMBER"].str[:9]))
    uni = CACHE / "universe.csv"
    if uni.exists():
        u = pd.read_csv(uni, dtype=str)
        sym_isin.update({s: i[:9] for s, i in zip(u["symbol"], u["isin"]) if isinstance(i, str) and i.startswith("IN")})
    k9_sym = {}
    for s, k in sym_isin.items():
        k9_sym.setdefault(k, s)
    lo = f"{months[0]}-01"
    P = pd.read_csv(CACHE / "prices.csv.gz", dtype={"symbol": str, "date": str}, usecols=["symbol", "date", "close"])
    first = P.groupby("symbol").date.min()                                   # first trading day in the price file
    listed = pd.to_datetime(lst["DATE OF LISTING"], format="%d-%b-%Y", errors="coerce").dt.strftime("%Y-%m-%d")
    first = pd.Series(dict(zip(lst["SYMBOL"], listed))).dropna().combine_first(first)   # NSE listing date when known
    P = P[P.date >= f"{prev_ym(months[0])}-01"]
    P["ym"] = P.date.str[:7]
    last = P.sort_values("date").groupby(["symbol", "ym"]).close.last().unstack()
    avg = P.groupby(["symbol", "ym"]).close.mean().unstack()
    return k9_sym, last, avg, first


# ═══════════════════════════════════════════════ scheme identity across months
def _ratio(a, b):
    """0-1 similarity of two normalised names."""
    try:
        from rapidfuzz import fuzz
        return fuzz.ratio(a, b) / 100.0
    except ImportError:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio()


def _cos(a, b):
    """Cosine similarity of two portfolios given as {stock: value}."""
    common = set(a) & set(b)
    if not common:
        return 0.0
    num = sum(a[k] * b[k] for k in common)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def _gap(a, b):
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + mb - ma


EQUITY_CAT = re.compile(r"equity scheme|elss|aggressive hybrid|^growth$", re.I)


def link_schemes(E, months, amfi):
    """Stable id per scheme across months, plus its AMFI category, class and allotment date.

    Matching, fund house by fund house and month by month:
      1. the same name as a scheme seen before (most recent first),
      2. a near-identical name (spelling, 'Smallcap' / 'Small Cap', a dropped word),
      each accepted only when the portfolio agrees — a name printed wrongly inside a file can not join two
      different funds (holdings unrelated and size far apart);
      3. a renamed scheme: the same portfolio (value-weighted cosine 0.9+, size within 0.5-2x), last seen
         within three months."""
    info = E.groupby(["ym", "amc", "scheme"]).agg(eq=("value_cr", "sum"), n=("qty", "size")).reset_index()
    info["key"] = [norm_name(s, a) for s, a in zip(info.scheme, info.amc)]
    port = {k: dict(zip(g.isin9, g.value_cr)) for k, g in E.groupby(["ym", "amc", "scheme"])}
    sid, renames = {}, []
    for amc, ga in info.groupby("amc"):
        pool = {}                                   # id -> (ym, key, scheme, equity) at its last appearance
        for ym in months:
            cur = ga[ga.ym == ym]
            if cur.empty:
                continue
            rows = list(cur.itertuples())
            free = dict(pool)
            got = {}

            def fit(r, pid):
                pym, _, psch, peq = pool[pid]
                return _cos(port[(ym, amc, r.scheme)], port[(pym, amc, psch)]), (r.eq / peq if peq else 0.0)

            for step in (1, 2):
                for r in rows:
                    if r.Index in got:
                        continue
                    if step == 1:
                        cands = sorted((pid for pid, v in free.items() if v[1] == r.key), key=lambda p: pool[p][0], reverse=True)
                    else:
                        sc = [(_ratio(r.key, v[1]), v[0], pid) for pid, v in free.items()]
                        cands = [pid for s, _, pid in sorted(sc, reverse=True) if s >= 0.93]
                    for pid in cands:
                        cos, size = fit(r, pid)
                        if cos < 0.5 and not 0.4 <= size <= 2.5:
                            continue
                        got[r.Index] = pid
                        free.pop(pid)
                        break
            for r in rows:
                if r.Index in got:
                    continue
                best = []
                for pid, (pym, pkey, psch, peq) in free.items():
                    if _gap(pym, ym) > 3:
                        continue
                    cos, size = fit(r, pid)
                    if cos >= 0.9 and 0.5 <= size <= 2.0:
                        best.append((cos, _ratio(r.key, pkey), pid))
                if best:
                    best.sort(reverse=True)
                    if len(best) > 1 and best[1][0] >= best[0][0] - 0.01:    # near-identical portfolios (index funds)
                        best.sort(key=lambda x: x[1], reverse=True)          # the name decides
                    pid = best[0][2]
                    got[r.Index] = pid
                    free.pop(pid)
                    renames.append((ym, amc, pool[pid][2], r.scheme, round(best[0][0], 3)))
            for r in rows:
                pid = got.get(r.Index)
                if pid is None:
                    pid = f"{amc}:{r.key or r.scheme}"
                    while pid in pool or pid in got.values():
                        pid += "+"
                    got[r.Index] = pid
                sid[(ym, amc, r.scheme)] = pid
            for r in rows:
                pool[got[r.Index]] = (ym, r.key, r.scheme, r.eq)
    info["id"] = [sid[(y, a, s)] for y, a, s in zip(info.ym, info.amc, info.scheme)]

    # AMFI scheme for each name (category, NFO allotment date)
    amfi_hit = {}
    for amc, g in info.groupby("amc"):
        lst = [x for x in amfi.get(amc, []) if x[0]]
        for sch, key in set(zip(g.scheme, g.key)):
            best, bs = None, 0.0
            for k, nm, cat, alloc in lst:
                sc = _ratio(key, k)
                if sc > bs:
                    best, bs = (nm, cat, alloc), sc
            amfi_hit[(amc, sch)] = best if best and bs >= 0.9 else (None, None, None)
    info["amfi_name"] = [amfi_hit[(a, s)][0] for a, s in zip(info.amc, info.scheme)]
    info["amfi_cat"] = [amfi_hit[(a, s)][1] for a, s in zip(info.amc, info.scheme)]
    info["alloc"] = [amfi_hit[(a, s)][2] for a, s in zip(info.amc, info.scheme)]
    # one class per scheme (not per month): from its latest AMFI-matched month, else its latest name
    cls, cat, alloc = {}, {}, {}
    for i, g in info.sort_values("ym", ascending=False).groupby("id", sort=False):
        hit = g[g.amfi_cat.notna()]
        r = hit.iloc[0] if len(hit) else g.iloc[0]
        cls[i] = classify(r.amfi_name or r.scheme, r.amfi_cat)
        cat[i] = r.amfi_cat
        alloc[i] = r.alloc if len(hit) else None
    info["cls"] = info.id.map(cls)
    info["cat"] = info.id.map(cat)
    info["alloc_id"] = info.id.map(alloc)
    return info, renames


# ═══════════════════════════════════════════════ what happened next (early evidence)
EV_GROUPS = [("b25", "Bought 0.25%+ of the company"), ("b10", "Bought 0.10–0.25%"), ("flat", "Little change (within ±0.10%)"),
             ("s10", "Sold 0.10–0.25%"), ("s25", "Sold 0.25%+ of the company")]


def evidence(A, shares, months):
    """Returns after the portfolios became public, by how much of the company active funds bought or sold.

    Point in time: each month's returns start on the first session on or after the 11th of the next month
    (fund houses publish by the 10th) and run 21 and 63 sessions, against NIFTY 500. Pooled over every stock-month
    held by active funds; new listings and suspected splits are left out."""
    P = pd.read_csv(CACHE / "prices.csv.gz", dtype={"symbol": str, "date": str}, usecols=["symbol", "date", "close"])
    P = P[P.date >= f"{months[0]}-01"]
    C = P.pivot_table(index="date", columns="symbol", values="close").sort_index()
    if "NIFTY 500" not in C:
        return None
    dates = list(C.index)
    act = A[(A.cls == "active") & ~A.listing.astype(bool) & ((A.hold > 0) | (A.dq != 0))].copy()
    act["bp"] = act.dq / act.sym.map(shares) * 100
    act = act[np.isfinite(act.bp)]
    obs = []
    for t, g in act.groupby("ym"):
        y, m = map(int, t.split("-"))
        start = (dt.date(y, m, 1) + dt.timedelta(days=32)).replace(day=11).isoformat()
        i0 = next((i for i, d in enumerate(dates) if d >= start), None)
        if i0 is None:
            continue
        b0 = C["NIFTY 500"].iloc[i0]
        for h, col in ((21, "r1"), (63, "r3")):
            if i0 + h >= len(dates):
                g[col] = np.nan
                continue
            b = C["NIFTY 500"].iloc[i0 + h] / b0 - 1
            p0 = C.iloc[i0].reindex(g.sym).values
            p1 = C.iloc[i0 + h].reindex(g.sym).values
            g[col] = (p1 / p0 - 1 - b) * 100
        g["grp"] = np.select([g.bp >= .25, g.bp >= .10, g.bp > -.10, g.bp > -.25], ["b25", "b10", "flat", "s10"], "s25")
        g["start"] = dates[i0]
        obs.append(g[["ym", "sym", "bp", "grp", "r1", "r3", "start"]])
    if not obs:
        return None
    O = pd.concat(obs)
    base = {c: O.groupby("ym")[c].mean() for c in ("r1", "r3")}
    rows = []
    for key, label in EV_GROUPS:
        g = O[O.grp == key]
        row = {"key": key, "label": label}
        for c in ("r1", "r3"):
            v = g[c].dropna()
            mm = g.groupby("ym")[c].mean().dropna()
            row[c] = {"avg": round(float(v.mean()), 2) if len(v) else None, "med": round(float(v.median()), 2) if len(v) else None,
                      "win": round(float((v > 0).mean() * 100), 0) if len(v) else None, "n": int(len(v)),
                      "months": int(len(mm)), "beat_all": int((mm > base[c].reindex(mm.index)).sum())}
        rows.append(row)
    allr = {c: {"avg": round(float(O[c].dropna().mean()), 2), "n": int(O[c].notna().sum())} for c in ("r1", "r3")}
    return {"rows": rows, "all": allr, "first": O.ym.min(), "last": O.dropna(subset=["r1"]).ym.max(),
            "last3": O.dropna(subset=["r3"]).ym.max() if O.r3.notna().any() else None}


# ═══════════════════════════════════════════════ main
def main():
    months = ym_list()
    if len(months) < 2:
        print("mf_flows: need at least two months of portfolios")
        return
    E, F, complete = load_months(months)
    amfi = load_amfi()
    k9_sym, last_px, avg_px, first_date = load_prices(months)
    E["sym"] = E.isin9.map(k9_sym)
    unmapped = E[E.sym.isna()].value_cr.sum() / max(E.value_cr.sum(), 1)
    E = E[E.sym.notna()].copy()
    info, renames = link_schemes(E, months, amfi)
    key = ["ym", "amc", "scheme"]

    # hedged schemes (short futures above 10% of equity in most of their months) are hybrids, unless AMFI files
    # them as an equity scheme
    hedged_ids = []
    if len(F):
        short = F[F.qty < 0].groupby(key).value_cr.sum().abs()
        eqv = E.groupby(key).value_cr.sum()
        info["hedged"] = [bool(eqv.get(k, 0)) and short.get(k, 0) > 0.10 * eqv.get(k, 0)
                          for k in zip(info.ym, info.amc, info.scheme)]
        for i, g in info.groupby("id"):
            c = g.cat.iloc[0]
            if g.cls.iloc[0] == "active" and g.hedged.mean() >= 0.5 and not (isinstance(c, str) and EQUITY_CAT.search(c)):
                hedged_ids.append(i)
        info.loc[info.id.isin(hedged_ids), "cls"] = "hybrid"
    E = E.merge(info[key + ["id", "cls"]], on=key, how="left")

    # ── bonus / split: put every month's share counts on today's basis
    raw_px = (E.value_cr * 1e7 / E.qty).groupby([E.ym, E.sym]).median()
    fac, ca_log = {}, []
    for (ym, s), p in raw_px.items():
        adj = last_px.at[s, ym] if (s in last_px.index and ym in last_px.columns) else np.nan
        f = snap_factor(p / adj) if np.isfinite(adj) and adj > 0 else None
        fac[(ym, s)] = f
        if f not in (None, 1.0):
            ca_log.append((ym, s, round(p, 2), round(adj, 2), f))
    E["f"] = [fac.get((y, s)) for y, s in zip(E.ym, E.sym)]
    bad_px = E.f.isna()
    E["qa"] = E.qty * E.f.fillna(1.0)

    # ── scheme ages for the NFO rule
    first_seen = info.groupby("id").ym.min()
    alloc = info.groupby("id").alloc_id.first()
    ids_by_month = {(y, a): set(g.id) for (y, a), g in info.groupby(["ym", "amc"])}
    amc_of = info.groupby("id").amc.first()

    def is_new(i, t):
        """True while a scheme is still investing its NFO money: pairs ending within ~2 months of allotment."""
        a = alloc.get(i)
        fs = first_seen.get(i)
        if fs and _gap(fs, t) >= 3:            # we have the scheme 3+ months back: not a new fund, whatever the list says
            return False
        if a is not None and pd.notna(a):
            return pd.Timestamp(month_end(t)) < a + pd.Timedelta(days=62)
        # not in AMFI's list: new only when the fund house was read completely the month before it first appeared
        before = prev_ym(fs) if fs else None
        if before and complete.get((before, amc_of.get(i))) and i not in ids_by_month.get((before, amc_of.get(i)), set()):
            return _gap(fs, t) <= 2
        return False

    rows, detail, audit, merges, ca_suspect = [], defaultdict(list), [], [], []
    latest = months[-1]
    pairs = []
    pos = {k: g for k, g in E.groupby("ym")}
    for t in months[1:]:
        p = prev_ym(t)
        if p not in pos or t not in pos:
            continue
        amcs = sorted(a for a in set(pos[t].amc) & set(pos[p].amc) if complete.get((t, a)) and complete.get((p, a)))
        cur = pos[t][pos[t].amc.isin(amcs)].copy()
        prv = pos[p][pos[p].amc.isin(amcs)].copy()
        px_t = avg_px[t] if t in avg_px.columns else pd.Series(dtype=float)

        # mergers: a scheme that disappears while another scheme of the same fund house grows by its holdings —
        # its old holdings are added to the survivor's previous month, so the merger is not read as buying
        gone = set(prv.id) - set(cur.id)
        both = set(cur.id) & set(prv.id)
        for x in gone:
            X = prv[prv.id == x]
            if X.value_cr.sum() < 25:
                continue
            xv = (X.groupby("sym").qa.sum() * px_t.reindex(X.sym.unique())).dropna()
            amc = X.amc.iloc[0]
            best = None
            for y in both:
                if amc_of.get(y) != amc:
                    continue
                d = (cur[cur.id == y].groupby("sym").qa.sum().sub(prv[prv.id == y].groupby("sym").qa.sum(), fill_value=0))
                dv = (d * px_t.reindex(d.index)).dropna()
                common = xv.index.intersection(dv.index)
                if not len(common):
                    continue
                dot = float((xv[common] * dv[common]).sum())
                nx, nd = float(np.sqrt((xv ** 2).sum())), float(np.sqrt((dv ** 2).sum()))
                if nx and nd:
                    cos, scale = dot / (nx * nd), dot / (nx * nx)
                    if cos >= 0.8 and 0.6 <= scale <= 1.5 and (best is None or cos > best[0]):
                        best = (cos, y, scale)
            if best:
                prv.loc[prv.id == x, "id"] = best[1]
                merges.append({"m": t, "amc": amc, "from": X.scheme.iloc[0], "into": cur[cur.id == best[1]].scheme.iloc[0],
                               "cos": round(best[0], 3), "cr": round(float(X.value_cr.sum()), 1)})

        ids = set(cur.id) & set(prv.id)
        eq_t = cur.groupby("id").value_cr.sum()
        eq_p = prv.groupby("id").value_cr.sum()
        nfo = {i for i in ids if is_new(i, t)}
        grow = {i for i in ids - nfo if eq_p.get(i, 0) > 0 and eq_t.get(i, 0) / eq_p[i] > 2.0}
        ids -= nfo | grow
        c = cur[cur.id.isin(ids)].groupby(["id", "sym"]).agg(q1=("qa", "sum"), v1=("value_cr", "sum"), amc=("amc", "first"),
                                                               cls=("cls", "first"), nm=("scheme", "first"))
        o = prv[prv.id.isin(ids)].groupby(["id", "sym"]).agg(q0=("qa", "sum"), v0=("value_cr", "sum"), amc0=("amc", "first"),
                                                               cls0=("cls", "first"), nm0=("scheme", "first"))
        J = c.join(o, how="outer").reset_index()
        J["amc"] = J.amc.fillna(J.amc0)
        J["cls"] = J.cls.fillna(J.cls0)
        J["nm"] = J.nm.fillna(J.nm0)
        J[["q0", "q1", "v0", "v1"]] = J[["q0", "q1", "v0", "v1"]].fillna(0.0)
        J["dq"] = J.q1 - J.q0
        tol = np.maximum(1.0, 0.0005 * np.maximum(J.q0, J.q1))
        J.loc[J.dq.abs() <= tol, "dq"] = 0.0
        # safety net: a bonus / split the price file missed shows up as nearly every scheme's holding changing by the
        # same ratio — such a stock gets no flow this month (and is logged) rather than a false wave of buying
        # (one fund house trading all its schemes pro rata, or index funds rebalancing, also moves many holdings by
        # one ratio — so it also needs 3+ fund houses and the price in the files moving by the inverse ratio)
        hb = J[(J.q0 > 0) & (J.q1 > 0)]
        suspect = []
        for sym_, g_ in hb.groupby("sym"):
            rr = g_.q1 / g_.q0
            if len(rr) < 3 or g_.amc.nunique() < 3:
                continue
            med = float(rr.median())
            k = next((v for v in [2, 3, 4, 5, 10, 0.5, 0.2, 0.1] if abs(med / v - 1) <= 0.02), None)
            r0, r1 = raw_px.get((p, sym_)), raw_px.get((t, sym_))
            if k and (rr / med - 1).abs().le(0.02).mean() >= 0.8 and r0 and r1 and abs(r1 / r0 * k - 1) <= 0.15:
                suspect.append(sym_)
        if suspect:
            ca_suspect.extend((t, x) for x in suspect)
        # stocks listed during month t (IPO / demerger): holdings shown, no flow
        lp = month_end(p)
        new_list = set(s for s in J.sym.unique() if str(first_date.get(s, "1900")) > lp) | set(suspect)
        J["listing"] = J.sym.isin(new_list)
        J["px"] = px_t.reindex(J.sym).values
        J["flow"] = np.where(J.listing, 0.0, J.dq * J.px / 1e7)
        J.loc[J.flow.isna(), "flow"] = 0.0
        # audit trail for the month: what was counted and what was left out (active funds, ₹ cr at this month's prices)
        A_cur, A_prv = cur[cur.cls == "active"], prv[prv.cls == "active"]

        def net_of(idset):
            a = A_cur[A_cur.id.isin(idset)].groupby("sym").qa.sum()
            b = A_prv[A_prv.id.isin(idset)].groupby("sym").qa.sum()
            d = a.sub(b, fill_value=0)
            return round(float((d * px_t.reindex(d.index)).sum() / 1e7), 0)
        JA = J[J.cls == "active"]
        audit.append({"m": t, "fund_houses": len(amcs), "active_schemes": int(JA.id.nunique()),
                      "active_equity_cr": round(float(A_cur[A_cur.id.isin(ids)].value_cr.sum()), 0),
                      "active_net": round(float(JA.flow.sum()), 0),
                      "left_out": {"new_funds": net_of(nfo), "new_funds_n": len(nfo),
                                   "doubled": net_of(grow), "doubled_n": len(grow),
                                   "new_listings": round(float((JA[JA.listing].dq * JA[JA.listing].px).sum() / 1e7), 0),
                                   "only_one_month": net_of(set(cur.id) ^ set(prv.id))},
                      "merges": [m for m in merges if m["m"] == t],
                      "by_fund_house": {a: [round(float(v), 0), round(float(w), 0)] for (a, v), w in zip(
                          JA.groupby("amc").flow.sum().items(),
                          (JA.dq * JA.px / 1e7).where(JA.listing, 0).fillna(0).groupby(JA.amc).sum().values)}})
        pairs.append({"m": t, "amcs": amcs})
        if os.environ.get("MF_DEBUG") in (t, "all"):          # working data for the checking tools
            import pickle
            out_ = os.environ.get("MF_DEBUG_OUT", "/tmp/mf_debug.pkl")
            if os.environ.get("MF_DEBUG") == "all":
                out_ = out_.replace(".pkl", f"_{t}.pkl")
            pickle.dump({"J": J, "cur": cur, "prv": prv, "nfo": nfo, "grow": grow, "info": info}, open(out_, "wb"))
        for cls, G in J.groupby("cls"):
            G = G.copy()
            Gc = cur[cur.cls == cls]
            buy, sell = G[(G.dq > 0) & ~G.listing], G[(G.dq < 0) & ~G.listing]
            amc_net = G[~G.listing].groupby(["sym", "amc"]).dq.sum()
            amc_q = G[~G.listing].groupby(["sym", "amc"])[["q0", "q1"]].sum()
            amc_new = amc_q[(amc_q.q0 == 0) & (amc_q.q1 > 0)].groupby(level=0).size()       # fund houses new to the stock
            amc_b = amc_net[amc_net > 0].groupby(level=0).size()
            amc_s = amc_net[amc_net < 0].groupby(level=0).size()
            agg = pd.DataFrame({
                "net": G.groupby("sym").flow.sum(),
                "gb": buy.groupby("sym").flow.sum(), "gs": -sell.groupby("sym").flow.sum(),
                "nb": buy.groupby("sym").size(), "ns": sell.groupby("sym").size(),
                "nnew": G[(G.q0 == 0) & (G.q1 > 0) & ~G.listing].groupby("sym").size(),
                "nexit": G[(G.q0 > 0) & (G.q1 == 0) & ~G.listing].groupby("sym").size(),
                "ab": amc_b, "as": amc_s, "anew": amc_new,
                # holders and holdings: every scheme of this class in the month's files (new schemes included)
                "hold": Gc[Gc.qa > 0].groupby("sym").id.nunique(), "hamc": Gc[Gc.qa > 0].groupby("sym").amc.nunique(),
                "q1": Gc.groupby("sym").qa.sum(), "v1": Gc.groupby("sym").value_cr.sum(),
                "dq": G[~G.listing].groupby("sym").dq.sum(),
                "listing": G.groupby("sym").listing.any(),
            }).fillna(0)
            agg["ym"], agg["cls"] = t, cls
            rows.append(agg.reset_index())
            if t == latest and cls == "active":
                for r in G[(G.dq != 0) | G.listing].itertuples():
                    detail[r.sym].append([r.amc, r.nm, int(round(r.q1)), int(round(r.dq)), round(float(r.flow), 2), int(bool(r.listing))])
    A = pd.concat(rows, ignore_index=True)

    # ── whole-industry holdings (all scheme types) for "% of the company held by funds"
    tot_q = E[E.ym == latest].groupby("sym").qa.sum()
    tot_v = E[E.ym == latest].groupby("sym").value_cr.sum()
    mc = pd.read_csv(ROOT / "config" / "mcap_nse.csv")
    shares = (mc.set_index("Symbol").MarketCapCr * 1e7 / mc.set_index("Symbol").Close).replace([np.inf, -np.inf], np.nan)
    pct_mf = (tot_q / shares.reindex(tot_q.index) * 100).round(2)

    # ── size: AMFI method (rank by average full market cap over the last completed half-year; 1-100 large,
    #    101-250 mid, rest small), computed from NSE closes and current share counts
    y, m = map(int, latest.split("-"))
    h_end = f"{y}-06" if m >= 7 else f"{y - 1}-12"
    h_months = [c for c in avg_px.columns if c <= h_end][-6:]
    avg_mc = (avg_px[h_months].mean(axis=1) * shares.reindex(avg_px.index)).dropna().sort_values(ascending=False)
    rank = pd.Series(range(1, len(avg_mc) + 1), index=avg_mc.index)
    size = rank.map(lambda r: "L" if r <= 100 else "M" if r <= 250 else "S")

    # ── early evidence: what happened after the portfolios were published
    try:
        ev = evidence(A, shares, months)
    except Exception as e:                       # evidence is optional
        print(f"evidence skipped: {e}")
        ev = None

    # ── per stock output
    shown = [p["m"] for p in pairs][-MONTHS_SHOWN:]
    act = A[A.cls == "active"].set_index(["sym", "ym"])
    pas = A[A.cls == "passive"].groupby(["sym", "ym"]).net.sum()
    hyb = A[A.cls.isin(["hybrid", "arbitrage"])].groupby(["sym", "ym"]).net.sum()
    syms = sorted(set(act.index.get_level_values(0)) | set(tot_q.index))
    stocks = []
    for s in syms:
        def series(col):
            return [round(float(act[col].get((s, t), 0.0)), 2) if (s, t) in act.index else 0.0 for t in shown]
        net = series("net")
        last = act.loc[(s, latest)] if (s, latest) in act.index else None
        streak = 0
        for v in reversed(net):
            if v > 0:
                streak += 1
            else:
                break
        rec = {"s": s, "net": net, "gb": series("gb"), "gs": series("gs"),
               "nb": int(last.nb) if last is not None else 0, "ns": int(last.ns) if last is not None else 0,
               "nn": int(last.nnew) if last is not None else 0, "nx": int(last.nexit) if last is not None else 0,
               "ab": int(last.ab) if last is not None else 0, "as": int(last["as"]) if last is not None else 0,
               "an": int(last.anew) if last is not None else 0,
               "h": int(last.hold) if last is not None else 0, "ha": int(last.hamc) if last is not None else 0,
               "v": round(float(last.v1), 1) if last is not None else 0.0,
               "pas": round(float(pas.get((s, latest), 0.0)), 2), "hyb": round(float(hyb.get((s, latest), 0.0)), 2),
               "va": round(float(tot_v.get(s, 0.0)), 1), "pct": float(pct_mf.get(s)) if pd.notna(pct_mf.get(s)) else None,
               "st": streak, "sz": size.get(s, "S"), "ipo": bool(last.listing) if last is not None else False}
        sh = shares.get(s)
        if sh and np.isfinite(sh) and sh > 0:            # net shares bought each month, % of the company
            rec["bpm"] = [round(float(act["dq"].get((s, t), 0.0)) / sh * 100, 3) if (s, t) in act.index else 0.0 for t in shown]
            rec["bp"] = rec["bpm"][-1]
        if rec["h"] or any(net) or rec["va"]:
            stocks.append(rec)
    meta = {"months": shown, "latest": latest, "pairs": pairs[-MONTHS_SHOWN:],
            "built": dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d"),
            "fund_houses": {c: BRAND.get(c, c) for c in sorted(set(E.amc))},
            "coverage_latest": {"amcs": pairs[-1]["amcs"] if pairs else [], "unmapped_share": round(float(unmapped), 4)},
            "size_window": h_months, "corporate_actions": ca_log[-60:],
            "price_missing_rows": int(bad_px.sum()), "audit": audit[-MONTHS_SHOWN:],
            "missing": ", ".join(sorted(BRAND[c] for c in BRAND if pairs and c not in pairs[-1]["amcs"])),
            "evidence": ev}
    chk = OUT / "checks.json"                       # results of the independent checks (scratch tools), shown on the site
    if chk.exists():
        try:
            meta["checks"] = json.loads(chk.read_text())
        except ValueError:
            pass
    out = {"meta": meta, "stocks": stocks}
    OUT.mkdir(parents=True, exist_ok=True)
    # full working notes for checking (not used by the site)
    (OUT / "flows_audit.json").write_text(json.dumps(
        {"audit": audit, "merges": merges, "renames": renames, "hedged_as_hybrid": sorted(hedged_ids),
         "split_suspects_no_flow": ca_suspect,
         "corporate_actions": ca_log, "unmapped_share": round(float(unmapped), 5)}, indent=1, default=str))
    (OUT / "mf.json").write_text(json.dumps(out, separators=(",", ":")))
    det = {s: sorted(v, key=lambda r: -abs(r[4]))[:60] for s, v in detail.items()}
    (OUT / "mf_detail.json").write_text(json.dumps({"latest": latest, "names": BRAND, "rows": det}, separators=(",", ":")))
    n_act = sum(1 for r in stocks if r["h"])
    print(f"mf_flows: {len(months)} months ({months[0]}..{latest}), {len(stocks)} stocks, {n_act} held by active funds; "
          f"latest pair {pairs[-1]['m']} with {len(pairs[-1]['amcs'])} fund houses; corporate actions {len(ca_log)}")
    return out


if __name__ == "__main__":
    main()
