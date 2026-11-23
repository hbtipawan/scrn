"""Breadth tab: the five Nifty benchmark indices and gold, silver and bitcoin - cards and candle charts.

Gold, silver and bitcoin are shown for reference only: they are not part of any breadth number, scanner, ranking or
other page of the site, and nothing else reads these files.

Where the prices come from
  Indices   NSE's own daily open/high/low/close, from the price file the rest of the site uses (cache/prices.csv.gz):
            NIFTY 50, NIFTY 500, NIFTY MIDCAP 150, NIFTY SMLCAP 250, NIFTY MICROCAP250.
  Gold      COMEX gold futures, front month (Yahoo Finance GC=F), US$ per troy ounce.
  Silver    COMEX silver futures, front month (Yahoo Finance SI=F), US$ per troy ounce.
  Bitcoin   BTC-USD (Yahoo Finance), US$; it trades every day of the week.
  US$/Rs    INR=X (Yahoo Finance), for the Rs view of the three: gold per 10 g, silver per kg, bitcoin per coin. That is
            the world price in rupees; Indian prices (MCX) also carry import duty and GST, so they run a few % higher.
  The three are kept in config/markets/<key>.csv.gz (committed), so a day when Yahoo does not answer only means no new
  bar; the first run downloads 10 years. Each run re-reads the last 3 months, so a bar still trading at the time of the
  evening run is corrected the next day.

Writes
  docs/data/mkt.json        the eight cards: last close, day change, returns, distance from the 52-week high and about
                            13 months of closes for the small chart
  docs/data/mkt/<key>.json  the chart: ~3 years of daily and ~10 years of weekly bars (Monday-based weeks, dated by
                            their last bar) and the state of EMA 21 / 50 / 200 just before the first bar shipped,
                            worked out on the full history (as stock_charts.py), plus NIFTY 500 on the same dates for
                            the RS line of the other indices, and the US$/Rs rate for the three.
Called from compute.py inside try/except: it can never break the daily run."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import stock_charts as SCH

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config" / "markets"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
DAYS = 750                 # about 3 years of daily bars (bitcoin: about 2 years, it trades every day)
WEEKS = 520                # about 10 years of weekly bars
EMAS = SCH.EMAS
OZ = 31.1034768            # grams in a troy ounce

# key, card name, kind, source, unit, Rs conversion (multiplier on US$ x rate, Rs unit)
MARKETS = [
    ("nifty50", "Nifty 50", "index", "NIFTY 50", "points", None),
    ("nifty500", "Nifty 500", "index", "NIFTY 500", "points", None),
    ("midcap150", "Nifty Midcap 150", "index", "NIFTY MIDCAP 150", "points", None),
    ("smallcap250", "Nifty Smallcap 250", "index", "NIFTY SMLCAP 250", "points", None),
    ("microcap250", "Nifty Microcap 250", "index", "NIFTY MICROCAP250", "points", None),
    ("gold", "Gold", "metal", "GC=F", "US$ per troy ounce", (10 / OZ, "₹ per 10 g")),
    ("silver", "Silver", "metal", "SI=F", "US$ per troy ounce", (1000 / OZ, "₹ per kg")),
    ("btc", "Bitcoin", "crypto", "BTC-USD", "US$", (1.0, "₹")),
]
FX = ("usdinr", "INR=X")
BENCH = "NIFTY 500"


# ---------------------------------------------------------------- Yahoo download
def yahoo(symbol, rng):
    """Daily bars from Yahoo's chart API; dates in the exchange's own time zone (so a COMEX day is its trading day)."""
    last = None
    for k in range(2):
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}",
                             params={"range": rng, "interval": "1d"}, headers={"User-Agent": UA}, timeout=25)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            res = (r.json().get("chart") or {}).get("result") or []
            if not res or "timestamp" not in res[0]:
                raise RuntimeError("no bars")
            off = int(res[0].get("meta", {}).get("gmtoffset") or 0)
            q = res[0]["indicators"]["quote"][0]
            d = pd.DataFrame({"date": pd.to_datetime(np.array(res[0]["timestamp"]) + off, unit="s").strftime("%Y-%m-%d"),
                              "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
                              "close": q.get("close"), "volume": q.get("volume")})
            d = d.dropna(subset=["open", "high", "low", "close"])
            d = d[(d.close > 0) & (d.low > 0) & (d.high >= d.low)]
            return d.drop_duplicates("date", keep="last").reset_index(drop=True)
        except Exception as e:  # network trouble: one retry, then give up for today
            last = e
            time.sleep(3)
    raise RuntimeError(f"{symbol}: {last}")


def refresh(key, symbol):
    """Stored history plus today's download (new bars added, the last 3 months re-read)."""
    CFG.mkdir(parents=True, exist_ok=True)
    f = CFG / f"{key}.csv.gz"
    old = pd.read_csv(f, dtype={"date": str}) if f.exists() else None
    stale = old is None or not len(old) or (pd.Timestamp.today() - pd.Timestamp(old.date.max())).days > 60
    try:
        new = yahoo(symbol, "10y" if stale else "3mo")
    except Exception as e:
        print(f"markets: {key} not downloaded ({e}); using the stored history")
        return old, False
    d = new if old is None else pd.concat([old[~old.date.isin(set(new.date))], new])
    d = d.sort_values("date").reset_index(drop=True)
    d["volume"] = d["volume"].fillna(0).clip(lower=0)
    d.to_csv(f, index=False, compression={"method": "gzip", "mtime": 0}, float_format="%.6g")
    return d, True


# ---------------------------------------------------------------- build
def rd(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def ret(c, dates, days):
    """% change from the last close on or before (last date - days calendar days)"""
    t0 = (pd.Timestamp(dates[-1]) - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    i = int(np.searchsorted(dates, t0, side="right")) - 1
    return rd((c[-1] / c[i] - 1) * 100, 2) if i >= 0 and c[i] > 0 else None


def pack(w, nd):
    return {"t": list(w["date"]), "o": [rd(x, nd) for x in w.open], "h": [rd(x, nd) for x in w.high],
            "l": [rd(x, nd) for x in w.low], "c": [rd(x, nd) for x in w.close], "v": [int(x) for x in w.volume]}


def build(PFULL, last, out_dir):
    out_dir = Path(out_dir)
    (out_dir / "mkt").mkdir(parents=True, exist_ok=True)
    for f in (out_dir / "mkt").glob("*.json"):
        f.unlink()
    src = {}
    for key, name, kind, sym, unit, inr in MARKETS:
        if kind == "index":
            g = PFULL[PFULL.symbol == sym][["date", "open", "high", "low", "close", "volume"]]
            src[key] = g[g.date <= last].dropna(subset=["close"]).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    got = {}
    for key, name, kind, sym, unit, inr in MARKETS:
        if kind != "index":
            src[key], got[key] = refresh(key, sym)
    fx, got["usdinr"] = refresh(*FX)
    fxs = fx.set_index("date")["close"] if fx is not None and len(fx) else None
    bench = src.get("nifty500")
    bser = bench.set_index("date")["close"] if bench is not None and len(bench) else None
    cards, worst = [], 0.0
    for key, name, kind, sym, unit, inr in MARKETS:
        d = src.get(key)
        if d is None or len(d) < 30:
            print(f"markets: {name} has no history - card left out")
            continue
        d = d.copy()
        d["volume"] = d["volume"].fillna(0).clip(lower=0)
        dates, c = d.date.to_numpy(), d.close.to_numpy(dtype=float)
        nd = 2
        k0 = max(0, len(d) - DAYS)
        dd = d.iloc[k0:]
        w = SCH.weekly(d)
        j0 = max(0, len(w) - WEEKS)
        ww = w.iloc[j0:]
        wc = w.close.to_numpy(dtype=float)
        rec = {"k": key, "n": name, "kind": kind, "unit": unit, "asof": str(dates[-1]),
               "d": pack(dd, nd), "w": pack(ww, nd),
               "sd": {str(n): SCH.ema_state(c[:k0], n) for n in EMAS},
               "sw": {str(n): SCH.ema_state(wc[:j0], n) for n in EMAS}}
        # check: continuing the seed over the shipped bars gives the full-history EMA on the last bar
        for n in EMAS:
            full = SCH.ema_full(c, n)[-1]
            kk, e = rec["sd"][str(n)]
            for x in c[k0:]:
                kk += 1
                e = e + x if kk < n else (e + x) / n if kk == n else e + 2.0 / (n + 1) * (x - e)
            if full is not None:
                worst = max(worst, abs(e / full - 1))
        if kind == "index" and key != "nifty500" and bser is not None:
            rec["bd"] = [rd(x) for x in bser.reindex(dd.date)]
            rec["bw"] = [rd(x) for x in bser.reindex(ww.date)]
        if inr and fxs is not None:
            # the rate on each bar's date (the last one known on that date: bitcoin trades on weekends)
            f_all = fxs.reindex(sorted(set(fxs.index) | set(d.date))).ffill()
            fd = f_all.reindex(d.date).to_numpy(dtype=float)
            ci = c * fd * inr[0]
            okk = np.isfinite(ci)
            rec["fx"] = {"m": inr[0], "u": inr[1], "d": [rd(x, 4) for x in fd[k0:]],
                         "w": [rd(x, 4) for x in f_all.reindex(ww.date)]}
            wfull = w.close.to_numpy(dtype=float) * f_all.reindex(w.date).to_numpy(dtype=float) * inr[0]
            first = int(np.argmax(okk)) if okk.any() else len(ci)
            rec["sdi"] = {str(n): SCH.ema_state(ci[first:k0], n) if k0 > first else [0, 0.0] for n in EMAS}
            wok = np.isfinite(wfull)
            wfirst = int(np.argmax(wok)) if wok.any() else len(wfull)
            rec["swi"] = {str(n): SCH.ema_state(wfull[wfirst:j0], n) if j0 > wfirst else [0, 0.0] for n in EMAS}
            rec["fx0"] = str(fxs.index.min())
        (out_dir / "mkt" / f"{key}.json").write_text(json.dumps(rec, separators=(",", ":"), allow_nan=False))
        # the card
        y0 = (pd.Timestamp(dates[-1]) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
        sp = d[d.date >= y0]
        h52 = d[d.date > (pd.Timestamp(dates[-1]) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")].high.max()
        card = {"k": key, "n": name, "kind": kind, "unit": unit, "d": str(dates[-1]), "c": rd(c[-1]),
                "ch": rd((c[-1] / c[-2] - 1) * 100) if len(c) > 1 else None,
                "r": {"1M": ret(c, dates, 30), "3M": ret(c, dates, 91), "6M": ret(c, dates, 182), "1Y": ret(c, dates, 365)},
                "h52": rd((c[-1] / h52 - 1) * 100) if h52 > 0 else None,
                "st": list(sp.date), "sc": [rd(x) for x in sp.close]}
        if inr and fxs is not None and "fx" in rec:
            card["inr"] = {"u": inr[1], "c": rd(c[-1] * rec["fx"]["d"][-1] * inr[0], 0) if rec["fx"]["d"][-1] else None,
                           "rate": rec["fx"]["d"][-1]}
        if kind != "index":
            card["fresh"] = bool(got.get(key))
        cards.append(card)
    if worst > 1e-9:
        raise ValueError(f"EMA seed check failed ({worst})")
    meta = {"asof": last, "built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "rows": cards,
            "fx": {"rate": rd(float(fx.close.iloc[-1]), 4), "d": str(fx.date.iloc[-1])} if fx is not None and len(fx) else None}
    (out_dir / "mkt.json").write_text(json.dumps(meta, separators=(",", ":"), allow_nan=False))
    print(f"markets: {len(cards)} cards ({', '.join(c['n'] for c in cards)}); downloads "
          f"{', '.join(k for k, v in got.items() if v) or 'none'}; EMA seed check worst error {worst:.1e}")
    return {"n": len(cards), "keys": [c["k"] for c in cards], "asof": last}


if __name__ == "__main__":       # python scripts/markets.py  - rebuild the market files from the price cache
    p = pd.read_csv(ROOT / "cache" / "prices.csv.gz", dtype={"symbol": str, "date": str})
    print(build(p, p[p.symbol == BENCH].date.max(), ROOT / "docs" / "data"))
