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
that row is used when the company names agree. A stock not in the master is left unclassified (never guessed).

Hand-reviewed corrections in config/class_overrides.csv (symbol, sector, industry, reason) win over the master: for a
label that is plainly wrong for the company's business today (Raymond under "Air Transport Service", Premier Energies
under "Trading", ...). They survive a refresh of the master file; delete a line when the master gets it right."""
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

# Mixed-bag labels: companies that share only the label (traders, holding companies, "... Others"). They stay on
# every stock, but the Rotation tab does not rank them as groups: in 2021-26 tests a mixed bag in the top fifth of
# groups was followed by -2.5% against the average stock over 3 months (real industries +3.5%), and with them left
# out the site's other groups still flagged 34 of the 35 rallies found from prices alone (the 35th was not a labelling
# problem). Glass containers / aluminium sheets are real product groups, so they stay ranked.
MIXED = {
    "Sector": {"Trading", "Miscellaneous", "Diversified"},
    "Industry": {"Trading", "Miscellaneous", "Diversified", "Finance", "Services Others", "Finance and Investments Others",
                 "Finance Investment and Others", "NBFC Others", "Pharma Others", "Textiles Others", "Chemicals Others",
                 "Petrochemicals Others", "Plastics Others", "Auto Others", "Food Processing Others", "Leather Products Others",
                 "Platform Others", "Machine Tools Others", "Metal Others", "Capital Goods Others", "Electronics Others",
                 "Packaging Others", "Sugar Others"},
}


def load_overrides(cfg: Path):
    """config/class_overrides.csv: symbol, sector, industry (blank = keep the master's), reason. Reviewed by hand:
    where the master's label is plainly wrong for the company's business today. Also classifies a stock the master
    does not have yet."""
    f = cfg / "class_overrides.csv"
    if not f.exists():
        return pd.DataFrame(columns=["symbol", "sector", "industry", "reason"])
    d = pd.read_csv(f, dtype=str, comment="#").fillna("")
    for c in ("symbol", "sector", "industry"):
        d[c] = d[c].str.strip()
    return d[d.symbol != ""].drop_duplicates("symbol", keep="last")


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
    matched = len(sec)
    # hand-reviewed corrections win over the master file
    ov = load_overrides(cfg)
    known_sec, known_ind = set(d["Sector"].dropna()), set(d["Industry"].dropna())
    applied, odd = [], []
    wanted = set(symbols)
    for _, o in ov.iterrows():
        s = o["symbol"]
        if s not in wanted:
            continue
        if o["sector"]:
            if o["sector"] not in known_sec:
                odd.append(f"{s}: sector '{o['sector']}'")
            sec[s] = o["sector"]
        if o["industry"]:
            if o["industry"] not in known_ind:
                odd.append(f"{s}: industry '{o['industry']}'")
            ind[s] = o["industry"]
        applied.append(s)
    if odd:
        print("class_overrides.csv: label not used anywhere in the master (check the spelling): " + "; ".join(odd))
    rep = {"rows": int(len(d)), "matched": matched, "via_bse": via_bse, "missing": len(missing), "refused": len(refused),
           "sectors": int(pd.Series(sec).nunique()), "industries": int(pd.Series(ind).nunique()),
           "missing_list": missing[:50], "refused_list": refused[:50], "overrides": applied}
    return pd.Series(sec, dtype=object), pd.Series(ind, dtype=object), rep
