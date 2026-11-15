"""Sector and industry for every stock, from the master classification file (config/classification_master.csv).

The master file is a plain export with four columns: companyId (NSE:SYMBOL or BSE:SYMBOL), Name, Industry, Sector.
To refresh it, export the same list again and replace the file - nothing else changes.

Two clean-ups are applied, and only these:
  * spelling variants of one label are merged ("IT - Software" and "IT Software", "Capital Goods-Non Electrical
    Equipment" and "Capital Goods Non Electrical Equipment", "Steel - Tubes / Pipes" and "Steel Tubes and Pipes", ...):
    the most common spelling wins;
  * a few old-style industry labels ("Computers - Software - Medium / Small", ...) get the current label of the
    same industry (MANUAL_IND below).
A site symbol is matched to NSE:SYMBOL; if the master lists the company only under BSE:SYMBOL with the same symbol,
that row is used when the company names agree. A stock not in the master is left unclassified (never guessed)."""
import difflib
import re
from pathlib import Path

import pandas as pd

MANUAL_IND = {
    "Computers - Software - Medium / Small": "IT Services",
    "IT Enabled Services / Business Process Outsourcing": "IT Enabled Services and BPO",
    "Diamond Cutting / Jewellery - Medium / Small": "Diamond Gems and Jewellery",
    "Leather / Synthetic Footware - Medium / Small": "Leather and Synthetic Footwear",
    "Pharmaceuticals - Indian - Formulations": "Pharma Formulations",
    "Pesticides / Agrochemicals - Indian - Medium/Small": "Pesticides and Agrochemicals",
    "Textiles - Spinning/Cotton/Blended Yarn - Ring Spg": "Textiles Spinning and Cotton and Blended",
    "Engineering - Light - Gears": "Engineering Light Gears",
    "Engineering Light Gears": "Engineering Light Gears",
    "Auto Ancillaries - Others": "Auto Others",
    "Auto Ancillaries - Plastic Mouldings": "Auto Others",
}
# lenders, brokers, insurers ... (used where the site treats financial companies differently)
FINANCIAL_SECTORS = {"Finance", "Banks", "Insurance", "Stock and Commodity Brokers", "Financial Services"}


def _key(x):
    x = str(x).lower().replace("&", " and ").replace("/", " and ").replace(",", " ").replace("-", " ")
    x = re.sub(r"[^a-z0-9 ]", " ", x)
    t = [w for w in x.split() if w not in ("medium", "small", "large")]
    while t and t[-1] == "and":
        t.pop()
    out = []
    for w in t:
        if not (w == "and" and out and out[-1] == "and"):
            out.append(w)
    return " ".join(out)


def _clean_label(s):
    """the most common spelling of each label; ties go to the spelling without ' - ' or '/'"""
    vc = s.value_counts()
    best = {}
    for v, n in vc.items():
        k = _key(v)
        cur = best.get(k)
        tidy = not re.search(r" - |/|,", v)
        if cur is None or n > cur[1] or (n == cur[1] and tidy and not cur[2]):
            best[k] = (v, n, tidy)
    return s.map(lambda v: best[_key(v)][0])


def _name_key(x):
    x = str(x).upper().replace("&", " AND ")
    x = re.sub(r"\b(LIMITED|LTD|L|THE|COMPANY|CO|CORPORATION|CORP|INDIA|INDUSTRIES|IND)\b", " ", x)
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", x).split())


def load_master(cfg: Path):
    f = cfg / "classification_master.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f, dtype=str).dropna(subset=["companyId"])
    d["ex"] = d["companyId"].str.split(":").str[0].str.strip().str.upper()
    d["sym"] = d["companyId"].str.split(":").str[1].str.strip()
    for col in ("Industry", "Sector"):
        d[col] = d[col].fillna("").str.strip()
        d.loc[d[col] == "", col] = None
        ok = d[col].notna()
        d.loc[ok, col] = _clean_label(d.loc[ok, col])
    d["Industry"] = d["Industry"].map(lambda v: MANUAL_IND.get(v, v) if isinstance(v, str) else v)
    return d


def classify(symbols, names, cfg: Path):
    """-> (sector Series, industry Series, report dict) for the given site symbols. names: {symbol: company name}"""
    d = load_master(cfg)
    if d is None:
        return None, None, None
    nse = d[d.ex == "NSE"].drop_duplicates("sym").set_index("sym")
    bse = d[d.ex == "BSE"].drop_duplicates("sym").set_index("sym")
    sec, ind, via_bse, refused, missing = {}, {}, 0, [], []
    for s in symbols:
        if s in nse.index:
            r = nse.loc[s]
        elif s in bse.index:
            r = bse.loc[s]
            a, b = _name_key(names.get(s, "")), _name_key(r["Name"])
            if not a or difflib.SequenceMatcher(None, a, b).ratio() < 0.5:
                refused.append(s)            # same symbol, different company: do not guess
                continue
            via_bse += 1
        else:
            missing.append(s)
            continue
        if isinstance(r["Sector"], str):
            sec[s] = r["Sector"]
        if isinstance(r["Industry"], str):
            ind[s] = r["Industry"]
    rep = {"rows": int(len(d)), "matched": len(sec), "via_bse": via_bse, "missing": len(missing), "refused": len(refused),
           "sectors": int(pd.Series(sec).nunique()), "industries": int(pd.Series(ind).nunique()),
           "missing_list": missing[:50], "refused_list": refused[:50]}
    return pd.Series(sec, dtype=object), pd.Series(ind, dtype=object), rep
