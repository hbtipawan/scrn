"""Fund-flow scanners for the Scanners tab, from config/mf/site/mf.json (made by mf_flows.py).

Every scan uses ACTIVE funds only (index funds / ETFs, arbitrage and hedged hybrids are left out — their buying is
mechanical) and the latest month for which fund-house portfolios have been read. Sizes are measured as a share of
the company (shares bought ÷ shares outstanding), so a large cap and a small cap are judged on the same scale.
"""
import json
from pathlib import Path

CAT = "Fund flows"
MON = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
       "November", "December"]


def month_name(ym):
    y, m = ym.split("-")
    return f"{MON[int(m)]} {y}"


def build(path, by):
    """by: {symbol: stock row from compute.py (rs, st, mc ...)}. Returns None when there is no fund-flow file."""
    p = Path(path)
    if not p.exists():
        return None
    M = json.loads(p.read_text())
    meta, stocks = M["meta"], M["stocks"]
    if not stocks or not meta.get("months"):
        return None
    latest = meta["latest"]
    mon = month_name(latest)
    hits, metric, sm = {}, {}, []

    def add(id_, name, desc, cond, mval, label, fmt="num", sort="metric"):
        sel = [r for r in stocks if r["s"] in by and cond(r, by[r["s"]])]
        hits[id_] = sorted(r["s"] for r in sel)
        metric[id_] = {r["s"]: mval(r) for r in sel}
        sm.append({"id": id_, "name": name, "cat": CAT, "desc": desc, "metric": label, "fmt": fmt, "sort": sort})

    last = lambda r: r["net"][-1] if r["net"] else 0.0
    bp = lambda r: r.get("bp") or 0.0                      # net bought, % of the company's shares, latest month

    add("mf_top", "Most bought by mutual funds",
        f"Active mutual funds were net buyers of 0.25%+ of the company in {mon}, with at least 3 schemes buying and more "
        "schemes buying than selling. From every scheme's month-end portfolio.",
        lambda r, x: bp(r) >= 0.25 and r["nb"] >= 3 and r["nb"] > r["ns"] and not r.get("ipo"),
        lambda r: round(last(r), 1), "Net bought ₹Cr")
    add("mf_streak", "Fund buying streak",
        f"Active funds were net buyers in each of the last 3+ months to {mon}, and bought 0.1%+ of the company in the "
        "latest month — steady accumulation rather than a one-off.",
        lambda r, x: r["st"] >= 3 and bp(r) >= 0.1,
        lambda r: r["st"], "Months in a row", "int")
    add("mf_broad", "Broad fund buying",
        f"5+ fund houses added to the stock in {mon} and at least three times as many fund houses bought as sold — "
        "many independent teams reaching the same view.",
        lambda r, x: r["ab"] >= 5 and r["ab"] >= 3 * r["as"] and last(r) > 0,
        lambda r: r["ab"], "Fund houses buying", "int")
    add("mf_new", "New fund entries",
        f"2+ fund houses bought the stock for the first time in {mon} (none of their active schemes held it a month "
        "earlier), across 3+ schemes. New listings are left out.",
        lambda r, x: r.get("an", 0) >= 2 and r["nn"] >= 3 and not r.get("ipo"),
        lambda r: r.get("an", 0), "New fund houses", "int")
    add("mf_lead", "Fund buying in leaders",
        f"Active funds net bought 0.1%+ of the company in {mon}, and the stock is in Stage 2 with an RS rating of 70+ — "
        "institutional demand behind a stock that is already leading.",
        lambda r, x: bp(r) >= 0.1 and r["nb"] > r["ns"] and (x.get("rs") or 0) >= 70 and x.get("st") == 2,
        lambda r: round(last(r), 1), "Net bought ₹Cr")
    add("mf_sold", "Most sold by mutual funds",
        f"Active funds were net sellers of 0.25%+ of the company in {mon}, with more schemes selling than buying.",
        lambda r, x: bp(r) <= -0.25 and r["ns"] > r["nb"],
        lambda r: round(last(r), 1), "Net sold ₹Cr", "num", "metric_asc")

    per_stock = {r["s"]: {"mfn": round(last(r), 1), "mfst": r["st"]} for r in stocks if r["s"] in by and (last(r) or r["st"])}
    houses = len(meta.get("coverage_latest", {}).get("amcs", []))
    info = {"latest": latest, "months": len(meta["months"]), "fund_houses": houses, "stocks": len(stocks)}
    print(f"fund flows: {mon}, {houses} fund houses, " + ", ".join(f"{m['id']} {len(hits[m['id']])}" for m in sm))
    return {"meta": sm, "hits": hits, "metric": metric, "per_stock": per_stock, "info": info}
