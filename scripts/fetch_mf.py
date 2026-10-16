"""Download and read every fund house's monthly portfolio; save one compact file per fund house per month.

    python scripts/fetch_mf.py                     # latest months not yet saved (run daily 1st-15th)
    python scripts/fetch_mf.py --months 2025-09:2026-09 --only sbi,hdfc
    python scripts/fetch_mf.py --redo 2026-09      # re-read a month even if saved

Output (committed to the repo, read by mf_flows.py):
    config/mf/YYYY-MM/<code>.csv.gz   scheme, isin, name, qty, value_cr, kind   (kind: eq = shares held, fut = stock futures)
    config/mf/YYYY-MM/<code>.json     files used, schemes, dates, totals, warnings
Raw downloads are cached in cache/mf_raw/ (not committed).
"""
import argparse
import calendar
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import traceback
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import mf_parse as P
import mf_sources as S

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "config" / "mf"
RAW = ROOT / "cache" / "mf_raw"


def month_list(spec):
    a, b = spec.split(":") if ":" in spec else (spec, spec)
    y, m = map(int, a.split("-")); y2, m2 = map(int, b.split("-"))
    out = []
    while (y, m) <= (y2, m2):
        out.append((y, m)); m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def default_months(today=None):
    """The last completed month, plus the one before (late filers) — portfolios appear by the 10th."""
    t = today or dt.date.today()
    y, m = t.year, t.month - 1
    if m == 0:
        y, m = y - 1, 12
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    return [(py, pm), (y, m)]


def fetch_bytes(url):
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    ext = re.search(r"\.(xlsx|xls|xlsb|zip|csv)(?:\?|$)", url.lower())
    f = RAW / f"{key}.{ext.group(1) if ext else 'bin'}"
    if f.exists() and f.stat().st_size > 500:
        return f.read_bytes()
    r = S.http_get(url, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    data = r.content
    if data[:1] == b'"' and b"PK" in data[:6]:
        raise RuntimeError("file came back JSON-encoded")
    if data[:2] not in (b"PK",) and data[:4] != b"\xd0\xcf\x11\xe0" and b"<table" not in data[:200000].lower():
        raise RuntimeError(f"not a spreadsheet ({data[:12]!r})")
    RAW.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return data


_PX = {}


def month_prices(y, m):
    """{isin[:9]: NSE close on the last session of (y, m)} — used to check each file's value unit.
    The first 9 ISIN characters identify a company's equity across face-value changes."""
    key = (y, m)
    if key in _PX:
        return _PX[key]
    out = {}
    try:
        lst = pd.read_csv(ROOT / "cache" / "equity_l.csv")
        lst.columns = [c.strip() for c in lst.columns]
        sym2isin = dict(zip(lst["SYMBOL"], lst["ISIN NUMBER"].str[:9]))
        uni = ROOT / "cache" / "universe.csv"
        if uni.exists():
            u = pd.read_csv(uni, dtype=str)
            sym2isin.update({s: i[:9] for s, i in zip(u["symbol"], u["isin"]) if isinstance(i, str) and i.startswith("IN")})
        start, end = f"{y}-{m:02d}-01", f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
        px = pd.read_csv(ROOT / "cache" / "prices.csv.gz", dtype={"symbol": str, "date": str}, usecols=["symbol", "date", "close"])
        px = px[(px.date >= start) & (px.date <= end)].sort_values("date").groupby("symbol").close.last()
        out = {sym2isin[s]: float(c) for s, c in px.items() if s in sym2isin and c > 0}
    except Exception as e:                       # prices are a check, not a requirement
        print(f"   (no prices for unit check: {type(e).__name__}: {e})")
    _PX[key] = out
    return out


def date_ok(d, y, m):
    """Portfolio date must be within the last 7 days of the month (some houses use the last business day)."""
    if not d:
        return None
    try:
        x = dt.date.fromisoformat(d)
    except ValueError:
        return None
    end = dt.date(y, m, calendar.monthrange(y, m)[1])
    return (end - dt.timedelta(days=7)) <= x <= end


def clean_scheme(name):
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    s = re.sub(r"^[A-Z]{1,5}\d{1,4}\s*[-–:]\s*", "", s)                 # "IB01-Groww Large Cap Fund"
    s = re.sub(r"\(\s*(?:an |formerly|erstwhile|earlier)[^)]*\)?", "", s, flags=re.I)
    s = re.sub(r"\s*[\^*#]+\s*$", "", s)                                   # footnote marks
    s = re.sub(r"\s*[-–]\s*(monthly )?portfolio.*$", "", s, flags=re.I)
    s = re.sub(r"\s+(as on|as at)\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s*\b\d{1,2}(st|nd|rd|th)?[\s\-]+[A-Za-z]{3,9}[\s\-,]+\d{4}\s*$", "", s)
    s = re.sub(r"[\s\-–:]+$", "", s).strip()
    return s


SCHEME_LIKE = re.compile(r"\b(fund|plan|etf|fof|scheme|bees)\b", re.I)


def listing_name(fname):
    """Scheme name from a download's title: 'Monthly HDFC Retirement Fund - Equity Plan - 30 September 2026.xlsx'."""
    s = re.sub(r"\.(xlsx?|xlsb|xlsm|zip|csv|pdf)$", "", str(fname or ""), flags=re.I)
    s = re.sub(r"^(monthly|portfolio)\s+", "", s.strip(), flags=re.I)
    return clean_scheme(s)


def read_month(code, y, m, log, files=None):
    name, lister = S.SOURCES[code]
    files = lister(y, m) if files is None else files
    if not files:
        return None
    rows, used, warn, schemes, seen_blocks, failed, items = [], [], [], {}, {}, [], []
    for f in files:
        try:
            data = fetch_bytes(f["url"])
            blocks = P.parse(data, f["url"].rsplit("/", 1)[-1].split("?")[0], px=month_prices(y, m))
        except Exception as e:
            warn.append(f"{f['name'][:60]}: {type(e).__name__}: {str(e)[:120]}")
            failed.append(f["name"][:80])
            continue
        dates = [b["date"] for b in blocks if (b["eq"] or b["fut"]) and b.get("date_strong")]
        checks = [date_ok(d, y, m) for d in dates]
        bad = sum(1 for c in checks if c is False)
        good = sum(1 for c in checks if c)
        if bad and bad >= good:
            warn.append(f"{f['name'][:60]}: dated {sorted(set(d for d in dates if d))[:3]} not {y}-{m:02d} — skipped")
            continue
        n_eq = 0
        for b in blocks:
            if not b["eq"] and not b["fut"]:
                if b.get("eq_raw"):
                    warn.append(f"{(b['scheme'] or b['sheet'])[:50]}: {len(b['eq_raw'])} holdings dropped — value unit unknown")
                continue
            if b.get("date_strong") and date_ok(b["date"], y, m) is False:
                warn.append(f"{b['scheme'][:50]}: block dated {b['date']} — skipped")
                continue
            sig = hash(tuple(sorted((i, round(q)) for i, _, q, _, _ in b["eq"])))
            if b["eq"] and sig in seen_blocks:                                      # the same portfolio published twice
                warn.append(f"{b['scheme'][:50]}: identical to {seen_blocks[sig][:50]} — skipped duplicate")
                continue
            seen_blocks[sig] = b["scheme"]
            sch = clean_scheme(b["scheme"]) or clean_scheme(f["name"])
            if "::" in sch:                                                       # "<file in zip>::<sheet>" fallback
                sch = sch.split("::")[-1]
            if re.fullmatch(r"[A-Z0-9_\- ]{2,12}", sch or "") or sch == b["sheet"]:
                sch = listing_name(f["name"]) if len(files) > 1 else sch          # per-scheme file: its title names the scheme
            n_eq += len(b["eq"])
            items.append([sch, b, f, len(blocks) == 1 and len(files) > 1])
        used.append({"name": f["name"][:120], "url": f["url"], "schemes": len(blocks), "eq_rows": n_eq})
    # two blocks with the same scheme name: when each came from its own per-scheme file, the file titles decide
    # (e.g. a fund house printed the wrong plan name inside one file)
    key = lambda s: re.sub(r"\[[^\]]*\]|[^a-z0-9]", "", s.lower())
    cnt = defaultdict(int)
    for it in items:
        cnt[key(it[0])] += 1
    for it in items:
        if cnt[key(it[0])] > 1 and it[3]:
            alt = listing_name(it[2]["name"])
            if alt and SCHEME_LIKE.search(alt) and key(alt) != key(it[0]):
                warn.append(f"{it[0][:50]}: name shared with another file — using the file title {alt[:60]!r}")
                it[0] = alt
    for sch, b, f, _ in items:
        k = sch
        if k in schemes:
            k = f"{sch} [{b['sheet']}]"                                           # same name twice: keep both, flag
            warn.append(f"duplicate scheme name {sch!r} in {b['sheet']}")
        if b.get("unit_note"):
            warn.append(f"{sch[:50]}: {b['unit_note']}")
        schemes[k] = {"eq": len(b["eq"]), "fut": len(b["fut"]), "date": b["date"], "unit": b["unit"],
                      "price_match": round(b.get("price_match", 0), 3),
                      "eq_cr": round(sum(v for _, _, _, v, _ in b["eq"]), 2), "total_cr": round(b["total"], 2) if b["total"] else None}
        for isin, nm, q, v, pct in b["eq"]:
            rows.append((k, isin, (nm or "")[:80], q, round(v, 4), "eq"))
        for fi, nm, q, v in b["fut"]:
            rows.append((k, fi, (nm or "")[:80], q, round(v, 4), "fut"))
    if not rows:
        return {"code": code, "amc": name, "month": f"{y}-{m:02d}", "files": used, "warn": warn, "schemes": {}, "rows": 0}
    df = pd.DataFrame(rows, columns=["scheme", "isin", "name", "qty", "value_cr", "kind"])
    d = OUT / f"{y}-{m:02d}"
    d.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(df.to_csv(index=False).encode())
    (d / f"{code}.csv.gz").write_bytes(buf.getvalue())
    # a fund house that suddenly shows far fewer schemes than the month before probably published only part of its
    # files so far: keep the month but mark it incomplete (it is left out of the flows and read again next run)
    py_, pm_ = (y, m - 1) if m > 1 else (y - 1, 12)
    prev_meta = OUT / f"{py_}-{pm_:02d}" / f"{code}.json"
    if prev_meta.exists():
        try:
            n_prev = len(json.loads(prev_meta.read_text()).get("schemes", {}))
        except ValueError:
            n_prev = 0
        if n_prev >= 5 and len(schemes) < 0.8 * n_prev:
            warn.append(f"only {len(schemes)} schemes against {n_prev} last month — marked incomplete")
            failed.append(f"scheme count {len(schemes)} < 80% of {n_prev}")
    meta = {"code": code, "amc": name, "month": f"{y}-{m:02d}", "complete": not failed, "failed_files": failed, "fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "files": used, "schemes": schemes, "rows": len(df), "eq_cr": round(df[df.kind == "eq"].value_cr.sum(), 1), "warn": warn[:50]}
    (d / f"{code}.json").write_text(json.dumps(meta, indent=1))
    return meta


def deadline(y, m):
    """SEBI: portfolios within 10 days of month end. Two days' grace for late uploads."""
    return dt.date(y, m, calendar.monthrange(y, m)[1]) + dt.timedelta(days=12)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", help="YYYY-MM or YYYY-MM:YYYY-MM")
    ap.add_argument("--only", help="comma-separated fund-house codes")
    ap.add_argument("--skip", help="comma-separated codes to skip")
    ap.add_argument("--redo", action="store_true", help="re-read months already saved")
    ap.add_argument("--auto", action="store_true",
                    help="daily-run mode: from the 1st to the 20th, read new month-end files; otherwise do nothing")
    a = ap.parse_args()
    today = dt.date.today()
    months = month_list(a.months) if a.months else default_months(today)
    codes = a.only.split(",") if a.only else list(S.SOURCES)
    if a.skip:
        codes = [c for c in codes if c not in a.skip.split(",")]
    changed = 0
    if a.auto and today.day > 20:
        print("fund portfolios: nothing new expected after the 20th")
        months = []
    t0 = time.time()
    for (y, m) in months:
        for code in codes:
            done = OUT / f"{y}-{m:02d}" / f"{code}.json"
            files = None
            if done.exists() and not a.redo:
                try:
                    old = json.loads(done.read_text())
                except ValueError:
                    old = {}
                if old.get("complete", True):
                    try:
                        fetched = dt.date.fromisoformat(str(old.get("fetched", ""))[:10])
                    except ValueError:
                        fetched = dt.date(1900, 1, 1)
                    if old.get("final") or fetched > deadline(y, m) or not a.auto:
                        continue                     # saved and complete
                    # read before the deadline: a fund house may still add files, so compare the file list
                    try:
                        files = S.SOURCES[code][1](y, m)
                    except Exception as e:
                        print(f"{y}-{m:02d} {code:10s} list check failed: {type(e).__name__}")
                        continue
                    if files and {f["url"] for f in files} <= {f["url"] for f in old.get("files", [])}:
                        if today > deadline(y, m):
                            old["final"] = True
                            done.write_text(json.dumps(old, indent=1))
                        continue
            t1 = time.time()
            try:
                meta = read_month(code, y, m, print, files)
            except Exception as e:
                print(f"{y}-{m:02d} {code:10s} ERROR {type(e).__name__}: {str(e)[:200]}")
                traceback.print_exc(limit=1)
                continue
            if meta is None:
                print(f"{y}-{m:02d} {code:10s} not published yet")
                continue
            changed += meta["rows"] > 0
            print(f"{y}-{m:02d} {code:10s} {len(meta['files']):3d} files  {len(meta['schemes']):3d} schemes  "
                  f"{meta['rows']:6d} rows  equity ₹{meta.get('eq_cr', 0):>10,.0f} cr  {time.time() - t1:5.1f}s"
                  + (f"  ⚠ {len(meta['warn'])} warnings" if meta["warn"] else ""))
    print(f"done in {time.time() - t0:.0f}s, {changed} fund-house months saved")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
