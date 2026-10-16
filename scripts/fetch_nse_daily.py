"""NSE's own daily files, kept in the repository: delivery, trades, index valuations, corporate actions, holidays.

    python scripts/fetch_nse_daily.py                 # add every trading day not stored yet (daily run)
    python scripts/fetch_nse_daily.py --seed-eod2 DIR # one-time index history from eod2_data/daily (BennyThadikaran/eod2)
    python scripts/fetch_nse_daily.py --backfill 2024-01-01 2026-10-13   # delivery history straight from NSE

What is stored (config/nse/, committed; past months never change, so the repository grows slowly):
    dlv/YYYY-MM.csv.gz   date, symbol, series, volume, trades, dlv     every stock (EQ, BE, BZ, SME), NSE's raw numbers
                         from sec_bhavdata_full_DDMMYYYY.csv — delivery quantity = shares actually delivered
    idx/YYYY.csv.gz      date, index, open, high, low, close, pe, pb, dy   every NSE index incl. India VIX,
                         from ind_close_all_DDMMYYYY.csv (P/B and dividend yield only from the NSE files)
    corp_actions.json    splits, bonuses, dividends, rights, demergers with ex-dates (NSE corporate-actions list)
    holidays.json        NSE trading holidays for the year
    status.json          what was read and the official-close check

Also checks the price file (cache/prices.csv.gz): the last session's close of every stock is compared with NSE's
official close in the same NSE file and corrected when it differs (report in status.json).
The idea and the history come from EOD2 (github.com/BennyThadikaran/eod2), which builds the same data from the
same NSE reports.
"""
import argparse
import gzip
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
NSE = ROOT / "config" / "nse"
DLV, IDX = NSE / "dlv", NSE / "idx"
CACHE = ROOT / "cache"
IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36",
      "Accept": "*/*"}
HOSTS = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")
SERIES = {"EQ", "BE", "BZ", "SM", "ST"}
KEEP_FROM = "2024-01-01"            # delivery history kept in the repository (older history is used offline only)
MAX_GAP_DAYS = 45                   # the daily run catches up at most this far back


def today_ist():
    return datetime.now(IST).date()


def _get(path, tries=3):
    for host in HOSTS:
        for k in range(tries):
            try:
                r = requests.get(host + path, headers=UA, timeout=60)
                if r.status_code == 200 and len(r.content) > 200:
                    return r
                if r.status_code == 404:
                    break
            except requests.RequestException:
                pass
            time.sleep(1 + 2 * k)
    return None


def write_gz(path, df):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(df.to_csv(index=False).encode())
    path.write_bytes(buf.getvalue())


def merge_into(path, new, keys):
    """Add rows to a stored file, replacing rows with the same keys."""
    old = pd.read_csv(path, dtype=str) if path.exists() else pd.DataFrame(columns=new.columns)
    new = new.astype(str)
    out = pd.concat([old[~old.set_index(keys).index.isin(new.set_index(keys).index)], new], ignore_index=True)
    out = out.sort_values(keys).reset_index(drop=True)
    write_gz(path, out)
    return len(out)


# ════════════════════════════════════════ daily files
def read_delivery(d):
    """sec_bhavdata_full for one day -> DataFrame (date, symbol, series, close, volume, trades, dlv) or None."""
    r = _get(f"/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv")
    if r is None or not r.text.lstrip().startswith("SYMBOL"):
        return None
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    for c in ("SYMBOL", "SERIES", "DATE1"):
        df[c] = df[c].astype(str).str.strip()
    # on a holiday NSE serves the previous session's file under the holiday's name: trust the date inside the file
    if pd.to_datetime(df.DATE1, format="%d-%b-%Y", errors="coerce").dt.date.mode().get(0) != d:
        return None
    df = df[df.SERIES.isin(SERIES)]
    num = lambda s: pd.to_numeric(s.astype(str).str.strip().replace({"-": np.nan, "": np.nan}), errors="coerce")
    out = pd.DataFrame({"date": d.isoformat(), "symbol": df.SYMBOL, "series": df.SERIES,
                        "close": num(df.CLOSE_PRICE), "volume": num(df.TTL_TRD_QNTY), "trades": num(df.NO_OF_TRADES),
                        "dlv": num(df.DELIV_QTY)})
    # trade-to-trade series (BE, BZ) settle every trade by delivery
    t2t = out.series.isin({"BE", "BZ"})
    out.loc[t2t & out.dlv.isna(), "dlv"] = out.loc[t2t & out.dlv.isna(), "volume"]
    return out


def read_indices(d):
    """ind_close_all for one day -> DataFrame (date, index, open, high, low, close, pe, pb, dy) or None."""
    r = _get(f"/content/indices/ind_close_all_{d:%d%m%Y}.csv")
    if r is None or not r.text.lstrip().startswith("Index Name"):
        return None
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    if pd.to_datetime(df["Index Date"].astype(str).str.strip(), format="%d-%m-%Y", errors="coerce").dt.date.mode().get(0) != d:
        return None
    num = lambda c: pd.to_numeric(df[c].astype(str).str.strip().replace({"-": np.nan}), errors="coerce") if c in df else np.nan
    return pd.DataFrame({"date": d.isoformat(), "index": df["Index Name"].astype(str).str.strip(),
                         "open": num("Open Index Value"), "high": num("High Index Value"), "low": num("Low Index Value"),
                         "close": num("Closing Index Value"), "pe": num("P/E"), "pb": num("P/B"), "dy": num("Div Yield")})


def last_stored(folder):
    files = sorted(folder.glob("*.csv.gz"))
    if not files:
        return None
    return pd.read_csv(files[-1], usecols=["date"]).date.max()


def holidays():
    f = NSE / "holidays.json"
    if f.exists():
        try:
            return {h["date"] for h in json.loads(f.read_text()).get("trading", [])}
        except ValueError:
            pass
    return set()


def catch_up(status):
    hol = holidays()
    today = today_ist()
    after_close = datetime.now(IST).hour * 60 + datetime.now(IST).minute >= 18 * 60   # NSE posts the files by ~6 PM
    for name, folder, reader, monthly in (("delivery", DLV, read_delivery, True), ("indices", IDX, read_indices, False)):
        last = last_stored(folder)
        start = max(date.fromisoformat(last) + timedelta(days=1) if last else today - timedelta(days=10),
                    today - timedelta(days=MAX_GAP_DAYS))
        added, missing = [], []
        d = start
        while d <= today:
            # weekends are tried as well (special sessions such as budget day); only a missing weekday is reported
            if d.isoformat() not in hol and (d < today or after_close):
                df = reader(d)
                if df is None or df.empty:
                    if d.weekday() < 5:
                        missing.append(d.isoformat())
                else:
                    keep = df.drop(columns=["close"]) if name == "delivery" else df
                    path = folder / (f"{d:%Y-%m}.csv.gz" if monthly else f"{d:%Y}.csv.gz")
                    merge_into(path, keep, ["date", "symbol"] if name == "delivery" else ["date", "index"])
                    added.append(d.isoformat())
                    if name == "delivery":
                        status["last_delivery_file"] = df          # kept in memory for the close check
            d += timedelta(days=1)
        status[name] = {"added": added, "not_published": missing[-5:], "last": last_stored(folder)}
        print(f"{name}: added {len(added)} day(s) {added[-3:]}; not available {missing[-3:]}")


# ════════════════════════════════════════ NSE API: corporate actions, holidays
def nse_api(path):
    s = requests.Session()
    s.headers.update({**UA, "Accept": "application/json,text/plain,*/*",
                      "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions"})
    for k in range(3):
        try:
            if k:
                s.get("https://www.nseindia.com/", timeout=30)        # cookies, as a browser would
            r = s.get("https://www.nseindia.com/api/" + path, timeout=30)
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 + 3 * k)
    return None


def _ratio(subject):
    m = re.search(r"(\d+)\s*:\s*(\d+)", subject)
    return (int(m.group(1)), int(m.group(2))) if m else None


def classify_action(subject):
    """(kind, short label) from NSE's free-text purpose."""
    s = subject.strip()
    lo = s.lower()
    if "bonus" in lo:
        r = _ratio(s)
        return "bonus", f"Bonus {r[0]}:{r[1]}" if r else "Bonus"
    if "split" in lo or "face value" in lo or "sub-division" in lo or "subdivision" in lo:
        m = re.search(r"from\s*(?:rs\.?|re\.?|₹)?\s*([\d.]+).*?to\s*(?:rs\.?|re\.?|₹)?\s*([\d.]+)", lo)
        return "split", (f"Split ₹{float(m.group(1)):g} → ₹{float(m.group(2)):g}" if m else "Split")
    if "demerger" in lo or "scheme of arrangement" in lo:
        return "demerger", "Demerger"
    if "rights" in lo:
        r = _ratio(s)
        return "rights", f"Rights {r[0]}:{r[1]}" if r else "Rights issue"
    if "buy back" in lo or "buyback" in lo:
        return "buyback", "Buyback"
    if "dividend" in lo or "distribution" in lo:
        amt = sum(float(x) for x in re.findall(r"(?:rs\.?|re\.?|₹)\s*([\d.]+)", lo) if x.replace(".", "", 1).isdigit())
        kind = "Special dividend" if "special" in lo else "Final dividend" if "final" in lo else "Interim dividend" if "interim" in lo else "Dividend"
        return "dividend", f"{kind} ₹{amt:g}" if amt else kind
    return "other", s[:40]


def corporate_actions(status):
    t = today_ist()
    rows = []
    for idx in ("equities", "sme"):
        j = nse_api(f"corporates-corporateActions?index={idx}&from_date={t - timedelta(days=10):%d-%m-%Y}"
                    f"&to_date={t + timedelta(days=60):%d-%m-%Y}")
        if j is None:
            status["corp_actions_error"] = f"NSE corporate actions ({idx}) not reachable"
            continue
        for x in j:
            try:
                ex = datetime.strptime(x.get("exDate", ""), "%d-%b-%Y").date().isoformat()
            except ValueError:
                continue
            kind, label = classify_action(x.get("subject", ""))
            rows.append({"symbol": x.get("symbol"), "series": x.get("series"), "ex": ex, "kind": kind, "label": label,
                         "subject": x.get("subject", "")[:120]})
    if rows or not (NSE / "corp_actions.json").exists():
        rows = sorted({(r["symbol"], r["ex"], r["subject"]): r for r in rows}.values(), key=lambda r: (r["ex"], r["symbol"]))
        (NSE / "corp_actions.json").write_text(json.dumps({"fetched": t.isoformat(), "rows": rows}, indent=0))
    print(f"corporate actions: {len(rows)}")


def trading_holidays(status):
    j = nse_api("holiday-master?type=trading")
    if not j or "CM" not in j:
        print("holidays: NSE not reachable, keeping the saved list")
        return
    out = []
    for h in j["CM"]:
        try:
            out.append({"date": datetime.strptime(h["tradingDate"], "%d-%b-%Y").date().isoformat(), "name": h.get("description", "")})
        except (KeyError, ValueError):
            pass
    (NSE / "holidays.json").write_text(json.dumps({"fetched": today_ist().isoformat(), "trading": out}, indent=0))
    print(f"holidays: {len(out)}")


# ════════════════════════════════════════ official close check
def check_closes(status):
    """Compare the price file's last session with NSE's official closes for the same day; correct differences."""
    f = CACHE / "prices.csv.gz"
    if not f.exists():
        return
    p = pd.read_csv(f, dtype={"symbol": str, "date": str})
    last = p.date.max()
    nse = status.get("last_delivery_file")
    if nse is None or nse.date.iloc[0] != last:
        nse = read_delivery(date.fromisoformat(last))
    if nse is None:
        status["close_check"] = {"date": last, "checked": 0, "note": "NSE file not available"}
        return
    off = nse[nse.series.isin({"EQ", "BE", "BZ"})].drop_duplicates("symbol").set_index("symbol")["close"]
    day = p[p.date == last]
    cmp_ = pd.DataFrame({"ours": day.set_index("symbol")["close"], "nse": off}).dropna()
    diff = (cmp_.ours / cmp_.nse - 1).abs()
    bad = diff[diff > 0.001]
    if len(bad) and len(bad) < 0.2 * len(cmp_):      # a mass disagreement means a wrong file, not wrong prices
        idx = p.index[(p.date == last) & p.symbol.isin(bad.index)]
        p.loc[idx, "close"] = p.loc[idx, "symbol"].map(off).values
        p.loc[idx, "high"] = np.fmax(p.loc[idx, "high"], p.loc[idx, "close"])   # keep the bar consistent
        p.loc[idx, "low"] = np.fmin(p.loc[idx, "low"], p.loc[idx, "close"])
        p.to_csv(f, index=False, compression="gzip")
    status["close_check"] = {"date": last, "checked": int(len(cmp_)), "corrected": int(len(bad)) if len(bad) < 0.2 * len(cmp_) else 0,
                             "disagree": int(len(bad)), "examples": {k: [round(float(cmp_.ours[k]), 2), round(float(cmp_.nse[k]), 2)]
                                                                     for k in list(bad.sort_values(ascending=False).index[:8])}}
    print(f"official close check {last}: {len(cmp_)} stocks, {len(bad)} differed by more than 0.1%")


# ════════════════════════════════════════ one-time history from EOD2
def seed_eod2(folder):
    """eod2_data/daily → config/nse (delivery since KEEP_FROM, every index since 2012)."""
    folder = Path(folder)
    dl, ix = [], []
    for f in sorted(folder.glob("*.csv")):
        try:
            head = f.open().readline()
        except UnicodeDecodeError:
            continue
        if "P/E" in head:                                   # an index file
            d = pd.read_csv(f)
            ix.append(pd.DataFrame({"date": d.Date, "index": f.stem, "open": d.Open, "high": d.High, "low": d.Low,
                                    "close": d.Close, "pe": d["P/E"], "pb": np.nan, "dy": np.nan}))
            continue
        d = pd.read_csv(f, usecols=["Date", "Volume", "Series", "TOTAL_TRADES", "DLV_QTY"])
        d = d[(d.Date >= KEEP_FROM) & d.DLV_QTY.notna()]
        if d.empty:
            continue
        sym = f.stem[:-4] if f.stem.endswith("_sme") else f.stem
        dl.append(pd.DataFrame({"date": d.Date, "symbol": sym.upper(), "series": d.Series, "volume": d.Volume,
                                "trades": d.TOTAL_TRADES, "dlv": d.DLV_QTY}))
    D = pd.concat(dl, ignore_index=True)
    for c in ("volume", "trades", "dlv"):
        D[c] = pd.to_numeric(D[c], errors="coerce").round().astype("Int64")
    D["m"] = D.date.str[:7]
    for m, g in D.groupby("m"):
        write_gz(DLV / f"{m}.csv.gz", g.drop(columns="m").sort_values(["date", "symbol"]))
    I = pd.concat(ix, ignore_index=True)
    # eod2 names are NSE's index names in lower case: restore NSE's spelling from the latest NSE file
    latest = None
    for back in range(1, 8):
        latest = read_indices(today_ist() - timedelta(days=back))
        if latest is not None:
            break
    # eod2 file names replace "/" and ":" with "-", so names are matched on letters and digits only
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    names = {norm(n): n for n in latest["index"]} if latest is not None else {}
    I["index"] = I["index"].map(lambda n: names.get(norm(n), n.title()))
    I["y"] = I.date.str[:4]
    for y, g in I.groupby("y"):
        write_gz(IDX / f"{y}.csv.gz", g.drop(columns="y").sort_values(["date", "index"]))
    print(f"seeded: delivery {len(D):,} rows ({D.date.min()}..{D.date.max()}, {D.symbol.nunique()} symbols); "
          f"indices {len(I):,} rows, {I['index'].nunique()} indices ({I.date.min()}..{I.date.max()})")


def backfill(start, end, folder=DLV, workers=4):
    """Delivery history straight from NSE's daily files (every weekday in the range; holidays simply 404).
    Whole months are rewritten, so a month is either complete or untouched."""
    from concurrent.futures import ThreadPoolExecutor
    days = [start + timedelta(days=k) for k in range((end - start).days + 1)]   # weekends too: budget-day sessions
    with ThreadPoolExecutor(workers) as ex:
        got = [x for x in ex.map(read_delivery, days) if x is not None and not x.empty]
    D = pd.concat(got, ignore_index=True).drop(columns="close")
    for c in ("volume", "trades", "dlv"):
        D[c] = pd.to_numeric(D[c], errors="coerce").round().astype("Int64")
    D["m"] = D.date.str[:7]
    for m, g in D.groupby("m"):
        write_gz(Path(folder) / f"{m}.csv.gz", g.drop(columns="m").sort_values(["date", "symbol"]))
    print(f"backfill {start}..{end}: {D.date.nunique()} sessions, {len(D):,} rows, {D.symbol.nunique()} symbols → {folder}")


def backfill_idx(start, end, workers=4):
    """Index history (close, P/E, P/B, dividend yield) straight from NSE's daily ind_close_all files; years rewritten
    only for the days fetched (rows of other days in those years are kept)."""
    from concurrent.futures import ThreadPoolExecutor
    days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
    with ThreadPoolExecutor(workers) as ex:
        got = [x for x in ex.map(read_indices, days) if x is not None and not x.empty]
    I = pd.concat(got, ignore_index=True)
    I["y"] = I.date.str[:4]
    for y, g in I.groupby("y"):
        merge_into(IDX / f"{y}.csv.gz", g.drop(columns="y"), ["date", "index"])
    print(f"index backfill {start}..{end}: {I.date.nunique()} sessions, {I['index'].nunique()} indices")


def symbol_changes(status):
    """NSE's list of symbol changes (old → new, effective date): delivery rows stored under an old symbol are
    joined to the current one when the site is built."""
    r = _get("/content/equities/symbolchange.csv")
    if r is None:
        print("symbol changes: not reachable, keeping the saved list")
        return
    df = pd.read_csv(io.StringIO(r.text), dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]
    rows = []
    for _, x in df.iterrows():
        try:
            d = datetime.strptime(str(x["effective date"]).strip(), "%d-%b-%Y").date().isoformat()
        except ValueError:
            continue
        rows.append([str(x["old symbol"]).strip(), str(x["new symbol"]).strip(), d])
    (NSE / "symbol_changes.json").write_text(json.dumps({"fetched": today_ist().isoformat(), "rows": rows}, indent=0))
    print(f"symbol changes: {len(rows)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-eod2", help="path to eod2_data/daily for the one-time history")
    ap.add_argument("--backfill", nargs=2, metavar=("FROM", "TO"), help="delivery history from NSE, YYYY-MM-DD YYYY-MM-DD")
    ap.add_argument("--out", help="folder for --backfill (default config/nse/dlv)")
    ap.add_argument("--backfill-idx", nargs=2, metavar=("FROM", "TO"), help="index history from NSE, YYYY-MM-DD YYYY-MM-DD")
    ap.add_argument("--no-check", action="store_true", help="skip the official-close check")
    ap.add_argument("--wait", type=int, default=0, metavar="MIN",
                    help="after 6 PM IST, wait up to MIN minutes for today's NSE files if they are not out yet")
    a = ap.parse_args()
    NSE.mkdir(parents=True, exist_ok=True)
    if a.seed_eod2:
        seed_eod2(a.seed_eod2)
    if a.backfill:
        backfill(date.fromisoformat(a.backfill[0]), date.fromisoformat(a.backfill[1]), Path(a.out) if a.out else DLV)
        if a.out:
            return
    if a.backfill_idx:
        backfill_idx(date.fromisoformat(a.backfill_idx[0]), date.fromisoformat(a.backfill_idx[1]))
        return
    status = {"run": datetime.now(IST).strftime("%Y-%m-%d %H:%M")}
    trading_holidays(status)
    symbol_changes(status)
    catch_up(status)
    t = today_ist()
    if a.wait and t.isoformat() not in holidays() and datetime.now(IST).hour >= 18:
        deadline = time.time() + 60 * a.wait
        while time.time() < deadline and t.isoformat() in status["delivery"]["not_published"] + status["indices"]["not_published"]:
            print(f"today's NSE files are not out yet - checking again in 2 minutes")
            time.sleep(120)
            catch_up(status)
    corporate_actions(status)
    if not a.no_check:
        check_closes(status)
    status.pop("last_delivery_file", None)
    (NSE / "status.json").write_text(json.dumps(status, indent=1, default=str))


if __name__ == "__main__":
    main()
