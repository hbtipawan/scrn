"""Fundamentals from NSE's official filings - no login, no uploads.

Sources (all public NSE endpoints / archives):
  * integrated-filing-results   quarterly results filed since Feb 2025 (XBRL)
  * corporates-financial-results  older-format quarterly results (XBRL), used for 2024 quarters
  * corporate-share-holdings-master  quarterly shareholding pattern (XBRL)
  * corporate-board-meetings    results dates (past and upcoming) and NSE industry

Writes (plain CSV so git stores only small daily differences):
  config/fund_results.csv   one row per stock per quarter: P&L, plus balance sheet / cash flow
                            in the half-year (Sep) and year-end (Mar) filings
  config/fund_holdings.csv  one row per stock per quarter: promoter / FII / DII / MF / retail %
  config/fund_info.csv      industry, last and next results date
  config/fund_meta.json     date of the last successful run (next run only looks at newer filings)

The first run (or --full) lists everything since 2024 and downloads ~40k small files
(about 30-60 min). Later runs only fetch filings published since the previous run.
"""
import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
CFG, CACHE = ROOT / "config", ROOT / "cache"
F_RES, F_SHP, F_INFO, F_META = (CFG / n for n in ("fund_results.csv", "fund_holdings.csv", "fund_info.csv", "fund_meta.json"))
API = "https://www.nseindia.com/api/"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
       "Accept": "application/json,text/html,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"}
XPRE = "https://nsearchives.nseindia.com/corporate/xbrl/"
short = lambda u: str(u).replace(XPRE, "") if isinstance(u, str) else u      # keep CSVs compact
full_url = lambda u: u if str(u).startswith("http") else XPRE + str(u)
QUARTERS_KEPT = 12          # quarters of results kept per stock
RES_COLS = ["symbol", "qe", "basis", "aud", "filed", "bank", "rev", "oi", "inc", "exp", "fin", "dep", "exc", "pbt", "tax", "pat", "pat_own", "eps",
            "paidup", "fv", "prov", "equity", "borrow", "cash", "cwip", "assets", "inv", "recv", "ocf", "capex", "ytd_rev", "ytd_pat", "xbrl",
            "first_filed"]
SHP_QUARTERS = 5            # shareholding XBRLs per stock (latest quarter + 1 year back)
_tl = threading.local()


def sess():
    if not hasattr(_tl, "s"):
        _tl.s = requests.Session()
        _tl.s.headers.update(HDR)
    return _tl.s


class Rate:
    def __init__(self, per_sec):
        self.gap, self.lock, self.next = 1.0 / per_sec, threading.Lock(), 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        time.sleep(max(0.0, t - now))


RATE = Rate(12)


def fetch(url, js=False, tries=5):
    for a in range(tries):
        RATE.wait()
        try:
            r = sess().get(url, timeout=45)
        except requests.RequestException:
            time.sleep(2 + 3 * a)
            continue
        if r.status_code == 200:
            try:
                return r.json() if js else r.text
            except ValueError:
                pass
        elif r.status_code in (401, 403, 429) or r.status_code >= 500:
            time.sleep(3 + 5 * a)
            if a == 1:  # refresh cookies once, as a browser would
                try:
                    sess().get("https://www.nseindia.com/", timeout=30)
                except requests.RequestException:
                    pass
            continue
        else:
            return None
    return None


def d_api(d):
    return d.strftime("%d-%m-%Y")


def windows(start, end, days):
    out, a = [], start
    while a <= end:
        b = min(end, a + timedelta(days=days - 1))
        out.append((a, b))
        a = b + timedelta(days=1)
    return out


def pdate(s):
    for f in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(str(s).strip().title(), f)
        except (ValueError, TypeError):
            continue
    return None


# ───────────────────────────────────────────────────────── listings
def list_results(start, end):
    """All quarterly-result filings broadcast between start and end -> DataFrame."""
    rows = []
    for a, b in windows(start, end, 15):
        if b >= date(2025, 1, 15):   # integrated filing (new format)
            j = fetch(f"{API}integrated-filing-results?index=equities&type=Integrated%20Filing-%20Financials"
                      f"&from_date={d_api(a)}&to_date={d_api(b)}&size=10000", js=True) or {}
            for x in j.get("data", []):
                rows.append({"symbol": x.get("symbol"), "qe": x.get("qe_Date"), "basis": "C" if str(x.get("consolidated", "")).startswith("Cons") else "S",
                             "filed": x.get("broadcast_Date") or x.get("creation_Date"), "xbrl": x.get("xbrl"), "aud": x.get("audited")})
        if a <= date(2025, 6, 30):   # older format
            j = fetch(f"{API}corporates-financial-results?index=equities&period=Quarterly"
                      f"&from_date={d_api(a)}&to_date={d_api(b)}", js=True) or []
            for x in j if isinstance(j, list) else []:
                rows.append({"symbol": x.get("symbol"), "qe": x.get("toDate"), "basis": "C" if str(x.get("consolidated", "")).startswith("Cons") else "S",
                             "filed": x.get("broadCastDate") or x.get("filingDate"), "xbrl": x.get("xbrl"), "aud": x.get("audited")})
        print(f"  results listing {a}..{b}: {len(rows)} so far", flush=True)
    df = pd.DataFrame(rows, columns=["symbol", "qe", "basis", "filed", "xbrl", "aud"])
    df = df[df.xbrl.astype(str).str.startswith("http") & df.symbol.notna()]
    df["qe"] = pd.to_datetime(df.qe.map(lambda s: pdate(s)), errors="coerce").dt.date.astype(str)
    df["xbrl"] = df.xbrl.map(short)
    df["filed_dt"] = df.filed.map(pdate)
    return df[df.qe != "NaT"]


def list_shp(start, end):
    rows = []
    for a, b in windows(start, end, 31):
        j = fetch(f"{API}corporate-share-holdings-master?index=equities&from_date={d_api(a)}&to_date={d_api(b)}", js=True) or []
        for x in j if isinstance(j, list) else []:
            rows.append({"symbol": x.get("symbol"), "qe": x.get("date"), "filed": x.get("broadcastDate") or x.get("submissionDate"),
                         "xbrl": x.get("xbrl"), "promoter": x.get("pr_and_prgrp")})
        print(f"  shareholding listing {a}..{b}: {len(rows)} so far", flush=True)
    df = pd.DataFrame(rows, columns=["symbol", "qe", "filed", "xbrl", "promoter"])
    df = df[df.symbol.notna() & df.xbrl.astype(str).str.startswith("http")]
    df["qe"] = pd.to_datetime(df.qe.map(pdate), errors="coerce").dt.date.astype(str)
    df["xbrl"] = df.xbrl.map(short)
    df["filed_dt"] = df.filed.map(pdate)
    return df[df.qe != "NaT"]


def list_meetings(start, end):
    rows = []
    for a, b in windows(start, end, 31):
        j = fetch(f"{API}corporate-board-meetings?index=equities&from_date={d_api(a)}&to_date={d_api(b)}", js=True) or []
        for x in j if isinstance(j, list) else []:
            text = f"{x.get('bm_purpose', '')} {x.get('bm_desc', '')}".lower()
            rows.append({"symbol": x.get("bm_symbol"), "date": pdate(x.get("bm_date")), "industry": x.get("sm_indusrty"),
                         "results": ("result" in text) or ("financial" in text)})
    return pd.DataFrame(rows, columns=["symbol", "date", "industry", "results"])


# ───────────────────────────────────────────────────────── XBRL parsing
FACT = re.compile(r'<[A-Za-z-]+:([A-Za-z]+)\b([^>]*?)contextRef="([^"]+)"([^>]*)>([^<]{1,40})</')


def facts(text):
    """{context: {tag: float}} for numeric facts."""
    out = {}
    for tag, _a, ctx, _b, val in FACT.findall(text):
        try:
            v = float(val)
        except ValueError:
            continue
        out.setdefault(ctx, {})[tag] = v
    return out


def first(d, *keys):
    for k in keys:
        if k in d:
            return d[k]
    return None


CR = 1e7


def parse_result(text):
    f = facts(text)
    q, y, i = f.get("OneD", {}), f.get("FourD", {}), f.get("OneI", {})
    if not q:
        return None
    bank = "InterestEarned" in q and "RevenueFromOperations" not in q
    rev = first(q, "RevenueFromOperations", "InterestEarned", "Income")
    # Net profit for the period (as Screener / StockScan report it). Some filers leave the
    # "attributable to owners" line at 0, so it is kept separately and only used as a fallback.
    pat_own = first(q, "ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates")
    pat = first(q, "ProfitLossForPeriod", "ProfitLossForThePeriod", "ProfitLossFromOrdinaryActivitiesAfterTax")
    pbt_ = first(q, "ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax")
    implied = (pbt_ - q["TaxExpense"]) if pbt_ is not None and "TaxExpense" in q else None
    if pat is None or (pat == 0 and implied):
        pat = pat_own if pat_own else implied
    eps = first(q, "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsLossPerShareFromContinuingOperations",
                "BasicEarningsPerShareAfterExtraordinaryItems", "BasicEarningsPerShareBeforeExtraordinaryItems")
    pbt = first(q, "ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax")
    r = {
        "bank": int(bank),
        "rev": rev, "oi": q.get("OtherIncome"), "inc": q.get("Income"), "exp": first(q, "Expenses", "ExpenditureExcludingProvisionsAndContingencies"),
        "fin": first(q, "FinanceCosts", "InterestExpended"), "dep": q.get("DepreciationDepletionAndAmortisationExpense"),
        "exc": first(q, "ExceptionalItemsBeforeTax", "ExceptionalItems"), "pbt": pbt, "tax": q.get("TaxExpense"),
        "pat": pat, "pat_own": pat_own, "eps": eps, "paidup": q.get("PaidUpValueOfEquityShareCapital"), "fv": q.get("FaceValueOfEquityShareCapital"),
        "prov": q.get("ProvisionsOtherThanTaxAndContingencies"),
        # balance sheet (half-year / year-end filings)
        "equity": first(i, "EquityAttributableToOwnersOfParent", "Equity") or
                  ((i.get("Capital") or 0) + i["ReservesAndSurplus"] if "ReservesAndSurplus" in i else None),   # bank format
        "borrow": (i.get("BorrowingsNoncurrent") or 0) + (i.get("BorrowingsCurrent") or 0) if ("BorrowingsNoncurrent" in i or "BorrowingsCurrent" in i) else None,
        "cash": i.get("CashAndCashEquivalents"), "cwip": i.get("CapitalWorkInProgress"), "assets": i.get("Assets"),
        "inv": i.get("Inventories"), "recv": i.get("TradeReceivablesCurrent"),
        # cash flow (FourD = year to date: 6 months in Sep, 12 months in Mar)
        "ocf": y.get("CashFlowsFromUsedInOperatingActivities"),
        "capex": y.get("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
        "ytd_rev": first(y, "RevenueFromOperations", "InterestEarned", "Income"),
        "ytd_pat": first(y, "ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForPeriod", "ProfitLossForThePeriod"),
    }
    for k, v in list(r.items()):
        if k in ("bank", "eps", "fv") or v is None:
            continue
        r[k] = round(v / CR, 3)        # rupees -> crore
    return r


SHP_CTX = {"promoter": "ShareholdingOfPromoterAndPromoterGroup", "fii": "InstitutionsForeign", "dii": "InstitutionsDomestic",
           "mf": "MutualFundsOrUTI", "ret_small": "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh",
           "ret_big": "ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh", "public": "PublicShareholding",
           "corp": "BodiesCorporate"}
PCT = re.compile(r'<[A-Za-z-]+:ShareholdingAsAPercentageOfTotalNumberOfShares\b[^>]*contextRef="([A-Za-z]+)_ContextI"[^>]*>([^<]+)<')
HOLDERS = re.compile(r'<[A-Za-z-]+:NumberOfShareholders\b[^>]*contextRef="ShareholdingPattern_ContextI"[^>]*>([^<]+)<')


def parse_shp(text):
    p = {c: float(v) for c, v in PCT.findall(text) if re.match(r"^[\d.]+$", v)}
    if not p:
        return None
    # Newer filings give fractions (0.5116), older ones percentages (51.16): scale by the 100% total.
    tot = p.get("ShareholdingPattern") or (p.get("ShareholdingOfPromoterAndPromoterGroup", 0) + p.get("PublicShareholding", 0))
    k = 100.0 if tot and tot <= 1.5 else 1.0
    r = {key: (round(p[c] * k, 2) if c in p else None) for key, c in SHP_CTX.items()}
    h = HOLDERS.search(text)
    r["holders"] = int(float(h.group(1))) if h else None
    return r


# ───────────────────────────────────────────────────────── main
def run_pool(items, job, workers, label):
    out, fails, t0 = [], 0, time.time()
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(job, it) for it in items]
        for n, f in enumerate(as_completed(futs), 1):
            try:
                r = f.result()
                if r:
                    out.append(r)
                else:
                    fails += 1
            except Exception:
                fails += 1
            if n % 1000 == 0:
                print(f"  {label} {n}/{len(items)}  {time.time() - t0:.0f}s  ({fails} failed)", flush=True)
    print(f"  {label}: {len(out)} parsed, {fails} failed, {time.time() - t0:.0f}s", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="rebuild from 2024 instead of fetching only new filings")
    ap.add_argument("--limit", type=int, default=0, help="only the first N stocks (testing)")
    ap.add_argument("--redo-results", action="store_true", help="re-read all results files, keep shareholding")
    a = ap.parse_args()
    t_start = time.time()
    today = date.today()
    meta = json.loads(F_META.read_text()) if F_META.exists() else {}
    full = a.full or not F_RES.exists() or not meta.get("last_run")
    since = date(2024, 4, 1) if full else datetime.strptime(meta["last_run"], "%Y-%m-%d").date() - timedelta(days=4)
    print(f"Fundamentals: {'full build' if full else 'update'} - filings since {since}")

    u = pd.read_csv(CACHE / "universe.csv", dtype={"symbol": str})
    syms = sorted(u.loc[u.kind == "stock", "symbol"])
    if a.limit:
        syms = syms[: a.limit]
    want = set(syms)

    # ── results
    old = pd.read_csv(F_RES, dtype={"symbol": str}) if F_RES.exists() and not (full or a.redo_results) else pd.DataFrame()
    if len(old) and ("first_filed" not in old or old["first_filed"].isna().all()):
        # one-time: original announcement dates for recent quarters (later revisions overwrote "filed")
        L0 = list_results(today - timedelta(days=210), today)
        f0 = L0[L0.filed_dt.notna()].groupby(["symbol", "qe"]).filed_dt.min().dt.strftime("%Y-%m-%d")
        old["first_filed"] = [min(f0.get((s_, q_), fd), fd) if isinstance(fd, str) else f0.get((s_, q_))
                              for s_, q_, fd in zip(old.symbol, old.qe, old.filed)]
        print(f"  original result dates filled for {int(sum((s_, q_) in f0.index for s_, q_ in zip(old.symbol, old.qe)))} recent quarters")
    lst = list_results(date(2024, 4, 1) if a.redo_results else since, today)
    lst = lst[lst.symbol.isin(want)]
    # first broadcast of each quarter's results (any basis): a later revision must not move the result date
    first_dt = lst.groupby(["symbol", "qe"]).filed_dt.min()
    lst = lst.sort_values("filed_dt").drop_duplicates(["symbol", "qe", "basis"], keep="last")
    # One basis per quarter: consolidated when the company files it, else standalone.
    lst["pref"] = (lst.basis == "C").astype(int)
    lst = lst.sort_values(["pref", "filed_dt"]).drop_duplicates(["symbol", "qe"], keep="last").drop(columns="pref")
    if len(old):  # skip filings we already parsed (same XBRL link)
        old["xbrl"] = old.xbrl.map(short)
        have = set(zip(old.symbol, old.qe, old.basis, old.xbrl))
        lst = lst[[(s, q, b, x) not in have for s, q, b, x in zip(lst.symbol, lst.qe, lst.basis, lst.xbrl)]]
    # keep only recent quarters
    cutoff_q = str(pd.Timestamp(today) - pd.DateOffset(months=3 * QUARTERS_KEPT + 3))[:10]
    lst = lst[lst.qe >= cutoff_q]
    print(f"Results files to download: {len(lst)}")

    def job_r(row):
        t = fetch(full_url(row.xbrl))
        r = parse_result(t) if t else None
        if not r:
            return None
        f0 = first_dt.get((row.symbol, row.qe))
        r.update({"symbol": row.symbol, "qe": row.qe, "basis": row.basis, "aud": str(row.aud)[:1],
                  "filed": row.filed_dt.strftime("%Y-%m-%d") if row.filed_dt else None, "xbrl": row.xbrl,
                  "first_filed": f0.strftime("%Y-%m-%d") if f0 is not None and pd.notna(f0) else None})
        return r
    new = pd.DataFrame(run_pool(list(lst.itertuples()), job_r, 8, "results"))
    res = pd.concat([old, new], ignore_index=True) if len(old) else new
    if len(res):
        # keep the earliest known announcement date when a revised filing replaces the original
        ff = res["first_filed"] if "first_filed" in res else pd.Series(None, index=res.index, dtype=object)
        res["first_filed"] = ff.where(ff.notna(), res["filed"])
        res["first_filed"] = res.groupby(["symbol", "qe"])["first_filed"].transform("min")
        res["pref"] = (res.basis == "C").astype(int)
        res = res.sort_values(["pref", "filed"]).drop_duplicates(["symbol", "qe"], keep="last").drop(columns="pref")
        res = res[res.qe >= cutoff_q].sort_values(["symbol", "qe", "basis"])
        res.reindex(columns=RES_COLS).to_csv(F_RES, index=False)
    print(f"fund_results.csv: {len(res)} rows, {res.symbol.nunique() if len(res) else 0} stocks")

    # ── shareholding
    old_s = pd.read_csv(F_SHP, dtype={"symbol": str}) if F_SHP.exists() and not full else pd.DataFrame()
    sl = list_shp(max(since, today - timedelta(days=500)), today)
    sl = sl[sl.symbol.isin(want)].sort_values("filed_dt").drop_duplicates(["symbol", "qe"], keep="last")
    qd = pd.to_datetime(sl.qe)
    sl = sl[qd.dt.month.isin([3, 6, 9, 12]) & qd.dt.is_month_end]      # quarterly patterns only
    sl = sl.sort_values("qe").groupby("symbol").tail(SHP_QUARTERS)
    if len(old_s):
        old_s["xbrl"] = old_s.xbrl.map(short)
        have = set(zip(old_s.symbol, old_s.qe, old_s.xbrl))
        sl = sl[[(s, q, x) not in have for s, q, x in zip(sl.symbol, sl.qe, sl.xbrl)]]
    print(f"Shareholding files to download: {len(sl)}")

    def job_s(row):
        t = fetch(full_url(row.xbrl))
        r = parse_shp(t) if t else None
        if not r:
            return None
        r.update({"symbol": row.symbol, "qe": row.qe, "filed": row.filed_dt.strftime("%Y-%m-%d") if row.filed_dt else None, "xbrl": row.xbrl})
        return r
    new_s = pd.DataFrame(run_pool(list(sl.itertuples()), job_s, 8, "shareholding"))
    shp = pd.concat([old_s, new_s], ignore_index=True) if len(old_s) else new_s
    if len(shp):
        shp = shp.sort_values("filed").drop_duplicates(["symbol", "qe"], keep="last")
        shp = shp.sort_values(["symbol", "qe"]).groupby("symbol").tail(SHP_QUARTERS + 3)
        cols = ["symbol", "qe", "filed", "promoter", "fii", "dii", "mf", "ret_small", "ret_big", "corp", "public", "holders", "xbrl"]
        shp.reindex(columns=cols).to_csv(F_SHP, index=False)
    print(f"fund_holdings.csv: {len(shp)} rows, {shp.symbol.nunique() if len(shp) else 0} stocks")

    # ── results calendar (next 60 days) + NSE industry from board meetings; Yahoo industry for everyone
    bm = list_meetings(today - timedelta(days=120 if not full else 400), today + timedelta(days=60))
    # result date = the board meeting that approved the results when it came 1-3 days before the
    # first filing (the XBRL often follows the announcement by a day)
    if len(res) and len(bm):
        rm = bm[bm.results & bm.date.notna() & bm.symbol.notna()][["symbol", "date"]].copy()
        rm["mtg"] = pd.to_datetime(rm.date).dt.normalize()
        rm = rm.drop(columns="date").drop_duplicates().sort_values("mtg")
        ff = pd.to_datetime(res["first_filed"], errors="coerce")
        q = pd.DataFrame({"i": res.index, "symbol": res.symbol, "ff": ff - pd.Timedelta(days=1)}).dropna().sort_values("ff")
        m = pd.merge_asof(q, rm, left_on="ff", right_on="mtg", by="symbol", direction="backward", tolerance=pd.Timedelta(days=2))
        m = m[m.mtg.notna()]
        if len(m):
            res.loc[m.i.to_numpy(), "first_filed"] = m.mtg.dt.strftime("%Y-%m-%d").to_numpy()
            res.reindex(columns=RES_COLS).to_csv(F_RES, index=False)
            print(f"  result dates moved to the board meeting day: {len(m)}")
    info = pd.read_csv(F_INFO, dtype={"symbol": str}).set_index("symbol") if F_INFO.exists() else pd.DataFrame(columns=["industry"])
    if len(bm):
        bm = bm[bm.symbol.notna()]
        ind = bm.dropna(subset=["industry"]).sort_values("date").groupby("symbol")["industry"].last()
        ind = ind[ind.astype(str).str.strip().ne("-")]
        rs = bm[bm.results & bm.date.notna()]
        nxt = rs[rs.date.dt.date >= today].groupby("symbol")["date"].min()
        # latest results meeting already held: the results usually reach the market that day, while the
        # XBRL file (our "filed" date) can follow a day or two later (results.py uses the earlier date)
        held = rs[rs.date.dt.date <= today].groupby("symbol")["date"].max()
        info = info.reindex(sorted(set(info.index) | set(ind.index) | want))
        info.loc[ind.index, "nse_industry"] = ind
        info["next_results"] = nxt.reindex(info.index).dt.strftime("%Y-%m-%d")
        if "last_results" not in info:
            info["last_results"] = None
        held = held[held.index.isin(info.index)]
        info.loc[held.index, "last_results"] = held.dt.strftime("%Y-%m-%d")
    else:
        info = info.reindex(sorted(set(info.index) | want))
    for c in ("industry", "sector", "ind_date", "nse_industry", "next_results", "last_results"):
        if c not in info:
            info[c] = None
    # Yahoo classification: missing ones first, then refresh the oldest (max 400 a night)
    age = pd.to_datetime(info["ind_date"], errors="coerce")
    never = info["industry"].isna() & (age.isna() | (age < pd.Timestamp(today - timedelta(days=30))))   # unknown ones: retry monthly
    todo = list(info.index[never]) + list(age[info["industry"].notna() & (age < pd.Timestamp(today - timedelta(days=120)))].sort_values().index)
    todo = [x for x in dict.fromkeys(todo) if x in want][: (len(want) if full else 400)]
    if todo:
        try:
            import yfinance as yf

            def yjob(sym):
                for k in range(3):          # Yahoo throttles bursts - go gently and retry
                    try:
                        time.sleep(0.4)
                        i = yf.Ticker(sym + ".NS").info
                        if i.get("industry") or i.get("sector"):
                            return sym, i.get("industry"), i.get("sector")
                    except Exception:
                        pass
                    time.sleep(5 * (k + 1))
                return sym, None, None
            with ThreadPoolExecutor(2) as ex:
                for sym, ind_, sec_ in ex.map(yjob, todo):
                    if ind_:
                        info.loc[sym, ["industry", "sector", "ind_date"]] = [ind_, sec_, str(today)]
                    else:
                        info.loc[sym, "ind_date"] = str(today)
            print(f"  Yahoo industry: {len(todo)} looked up")
        except ImportError:
            print("  yfinance not installed - industry skipped")
    info = info[info.index.isin(want)]
    info.index.name = "symbol"
    info[["industry", "sector", "ind_date", "nse_industry", "next_results", "last_results"]].to_csv(F_INFO)
    print(f"fund_info.csv: {int(info.industry.notna().sum())} stocks with industry, {int(info.next_results.notna().sum())} with upcoming results date")

    if len(res):
        F_META.write_text(json.dumps({"last_run": str(today), "seconds": round(time.time() - t_start)}))
    print(f"Done in {time.time() - t_start:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
