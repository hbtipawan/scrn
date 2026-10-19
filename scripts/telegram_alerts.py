"""Telegram alerts for PKC Sector Radar.

  --evening  after the daily run: market summary + your watchlist alerts (same rules as the
             website's "Needs your attention today") + today's best scans.
  --live     during market hours (run every 15 min by .github/workflows/telegram.yml): live
             price check of your watchlist stocks - pivot crossed, stop broken, target hit,
             near pivot, big intraday move. Each alert is sent once per stock per day.
  --test     sends a test message (and prints your chat id if TELEGRAM_CHAT_ID isn't set yet).

Secrets (GitHub repo -> Settings -> Secrets and variables -> Actions):
  TELEGRAM_BOT_TOKEN  from @BotFather
  TELEGRAM_CHAT_ID    your chat id (the --test run prints it)
  GIST_TOKEN          the same ghp_ token used for "Sync devices" on the Watchlists tab;
                      the job reads your watchlists from that private gist
Optional repository variable SITE_URL (defaults to https://<owner>.github.io/<repo>/).
Without the secrets the script does nothing and exits cleanly.
"""
import argparse
import html
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA, CFG = ROOT / "docs" / "data", ROOT / "config"
IST = timezone(timedelta(hours=5, minutes=30))
TG_API = os.environ.get("TELEGRAM_API", "https://api.telegram.org")
GH_API = os.environ.get("GITHUB_API", "https://api.github.com")
UPX = os.environ.get("UPSTOX_API", "https://api.upstox.com/v3/historical-candle")
GFILE, SFILE = "pkc-radar-watchlists.json", "pkc-radar-alert-state.json"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GTOK = os.environ.get("GIST_TOKEN", "").strip()
MOVE_PCT = float(os.environ.get("MOVE_PCT") or 5)
UA = {"User-Agent": "Mozilla/5.0 (PKC Sector Radar alerts)"}


def site_url():
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"].rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


E = html.escape
inr = lambda v: "–" if v is None else (f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}".rstrip("0").rstrip("."))
sgn = lambda v, d=1, u="%": "–" if v is None else f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v):.{d}f}{u}"
tv = lambda s, ex="NSE": f"https://in.tradingview.com/chart/?symbol={quote(f'{ex}:{s}')}"
sym = lambda s, ex="NSE": f'<a href="{tv(s, ex)}">{E(s)}</a>'


# ───────────────────────────────────────────── Telegram / GitHub
def tg(method, **params):
    r = requests.post(f"{TG_API}/bot{TOKEN}/{method}", json=params, timeout=30)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not j.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {j.get('description') or r.status_code}")
    return j["result"]


def tg_send(text):
    """Send HTML text, split under Telegram's 4096-character limit at line breaks."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3900:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    for c in chunks:
        tg("sendMessage", chat_id=CHAT, text=c, parse_mode="HTML", disable_web_page_preview=True)
        time.sleep(0.4)


def gh(path, method="GET", body=None):
    r = requests.request(method, GH_API + path, json=body, timeout=30,
                         headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GTOK}", **UA})
    if r.status_code >= 300:
        raise RuntimeError(f"GitHub {path}: HTTP {r.status_code}")
    return r.json()


def gist_load():
    """-> (gist_id, watchlists dict, alert-state dict). Watchlists come from the website's Sync."""
    if not GTOK:
        return None, None, {}
    g = next((x for x in gh("/gists?per_page=100") if GFILE in (x.get("files") or {})), None)
    if not g:
        return None, None, {}
    full = gh(f"/gists/{g['id']}")
    files = full.get("files", {})
    wl = json.loads(files[GFILE]["content"])
    state = json.loads(files[SFILE]["content"]) if SFILE in files and files[SFILE].get("content") else {}
    return g["id"], wl, state


def state_save(gid, state):
    gh(f"/gists/{gid}", "PATCH", {"files": {SFILE: {"content": json.dumps(state)}}})


def wl_symbols(wl):
    seen, out = set(), []
    for L in wl.get("lists", []):
        for it in L.get("items", []):
            if it["s"] not in seen:
                seen.add(it["s"])
                out.append(it["s"])
    return out


def lists_of(wl, s):
    return [L["name"] for L in wl.get("lists", []) if any(i["s"] == s for i in L.get("items", []))]


# ───────────────────────────────────────────── evening digest
BULL = ["combo3", "up4", "high52_dcr", "ath", "vcp", "pocket_pivot", "tight3w", "power3", "bgu", "episodic_pivot", "darvas",
        "stage2_bo", "bull_snort", "wedge_pop", "f_post", "f_accel", "lb_breakout", "lb_near", "s2_early", "res_strong",
        "rs_bluedot", "dlv_quiet"]
BEAR = ["down4", "leader_down", "below200", "ema_down", "death", "gap_down", "f_red", "rs_fade", "dlv_dist"]
ICON = {"crit": "🛑", "warn": "⚠️", "good": "🚀", "info": "📅"}


def load(name):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else None


def sma50(c, i):
    if i < 49:
        return None
    w = c[i - 49:i + 1]
    return None if any(v is None for v in w) else sum(w) / 50


def watch_alerts(wl, by, scans_of, scan_name, closes, vp, asof, corp=None):
    """Python twin of wlAlerts() in docs/index.html."""
    out = []
    ca = {}
    for r in (corp or {}).get("rows", []):
        ca.setdefault(r.get("symbol"), []).append(r)
    meta = wl.get("meta", {})
    for s in wl_symbols(wl):
        x, m = by.get(s), meta.get(s, {}) or {}
        px = (x or {}).get("px") or (vp.get(s) or {}).get("close")
        add = lambda lvl, txt, rank: out.append((lvl, rank, s, txt))
        r1 = ((x or {}).get("r") or {}).get("1D")
        prev = px / (1 + r1 / 100) if px and r1 is not None else None
        stop, piv, tgt = m.get("stop"), m.get("pivot"), m.get("target")
        if px and stop:
            if px < stop:
                add("crit", f"closed below your stop ₹{inr(stop)} today" if prev and prev >= stop else f"below your stop ₹{inr(stop)} ({sgn((px / stop - 1) * 100)})", 0)
            elif px / stop - 1 <= .03:
                add("warn", f"within {(px / stop - 1) * 100:.1f}% of your stop ₹{inr(stop)}", 2)
        if px and tgt and px >= tgt:
            add("good", f"reached your target ₹{inr(tgt)}", 3)
        if px and piv:
            fp = (px / piv - 1) * 100
            if prev and prev <= piv < px:
                vr = (x or {}).get("vr")
                add("good", f"broke out above your pivot ₹{inr(piv)}" + (f" on {vr:.1f}× volume" if vr else ""), 1)
            elif 0 <= fp <= 5:
                add("good", f"in the buy zone, {sgn(fp)} above pivot ₹{inr(piv)}", 4)
            elif -3 <= fp < 0:
                add("info", f"{abs(fp):.1f}% below your pivot ₹{inr(piv)} — get ready", 5)
        bad = [scan_name[i] for i in scans_of.get(s, []) if i in BEAR and i in scan_name]
        if bad:
            add("warn", "warning: " + ", ".join(bad), 2)
        good = [scan_name[i] for i in scans_of.get(s, []) if i in BULL and i in scan_name]
        if good:
            add("good", "in today's scans: " + ", ".join(good), 6)
        if x and x.get("rs") is not None and x.get("rs1w") is not None and x["rs"] < 70 <= x["rs1w"]:
            add("warn", f"RS rating fell to {x['rs']} (was {x['rs1w']})", 7)
        c = (closes or {}).get("c", {}).get(s)
        if c and len(c) > 51:
            i = len(c) - 1
            a, b = sma50(c, i), sma50(c, i - 1)
            if a and b and c[i] is not None and c[i - 1] is not None:
                if c[i] < a and c[i - 1] >= b:
                    add("warn", "closed below its 50-day average", 3)
                elif c[i] > a and c[i - 1] <= b:
                    add("info", "closed back above its 50-day average", 8)
        nr = (x or {}).get("next_results")
        if nr:
            dd = (datetime.strptime(nr, "%Y-%m-%d") - datetime.strptime(asof, "%Y-%m-%d")).days
            if 0 <= dd <= 7:
                add("info", f"results on {datetime.strptime(nr, '%Y-%m-%d'):%a %d %b} ({'today' if dd == 0 else 'tomorrow' if dd == 1 else f'in {dd} days'})", 9)
        if "FRESH" in str((vp.get(s) or {}).get("status", "")):
            add("good", "fresh VPCI buy signal this week", 6)
        for r in ca.get(s, []):
            dd = (datetime.strptime(r["ex"], "%Y-%m-%d") - datetime.strptime(asof, "%Y-%m-%d")).days
            if 0 <= dd <= 7:
                add("info", f"{r['label']} — ex-date {datetime.strptime(r['ex'], '%Y-%m-%d'):%a %d %b}"
                    + (" (price will adjust)" if r.get("kind") in ("split", "bonus") else ""), 9)
    order = {"crit": 0, "warn": 1, "good": 2, "info": 3}
    return sorted(out, key=lambda a: (order[a[0]], a[1], a[2]))


def ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def evening():
    meta, stocks, scans, breadth, groups = (load(n) for n in ("meta.json", "stocks.json", "scans.json", "breadth.json", "groups.json"))
    if not meta or not stocks:
        print("No dashboard data - run compute.py first")
        return
    now_ist = datetime.now(IST)
    today = now_ist.strftime("%Y-%m-%d")
    try:
        hol = {h["date"]: h.get("name", "") for h in json.loads((CFG / "nse" / "holidays.json").read_text()).get("trading", [])}
    except (OSError, ValueError):
        hol = {}
    if today in hol and meta.get("asof") != today:
        print(f"NSE holiday today ({hol[today]}): no evening digest")
        return
    closes = load("closes.json")
    vpj = load("vpci/completed.json")
    vp = {}
    if vpj:
        cols = vpj["results"]["columns"]
        vp = {r[cols.index("symbol")]: dict(zip(cols, r)) for r in vpj["results"]["rows"]}
    by = {r["s"]: r for r in stocks}
    scans_of, scan_name = {}, {m["id"]: m["name"] for m in scans["meta"]}
    for i, syms in scans["hits"].items():
        for s in syms:
            scans_of.setdefault(s, []).append(i)
    asof = meta["asof"]
    bname = breadth.get("bench_name", "NIFTY 500")
    bi = meta["indices"].get(bname, {})
    L = len(breadth["dates"]) - 1
    a50, a50w = breadth["a50"][L], breadth["a50"][max(0, L - 5)]
    verdict = "Strong" if a50 >= 60 else "Mixed" if a50 >= 40 else "Weak"
    lines = [f"<b>📊 PKC Sector Radar · {datetime.strptime(asof, '%Y-%m-%d'):%d %b %Y}</b>",
             f"{E(bname)} {inr(bi.get('px'))} ({sgn((bi.get('r') or {}).get('1D'), 2)}) · Breadth <b>{verdict}</b>: {a50:.1f}% above 50 DMA ({sgn(a50 - a50w, 1, ' pts')} in a week)",
             f"Advances/declines {breadth['adv'][L]}/{breadth['dec'][L]} · 52W highs/lows {breadth['nh'][L]}/{breadth['nl'][L]}"
             + (f" ({breadth['n'][L]:,} stocks)" if breadth.get("n") else "")]
    ix = meta.get("idx") or {}
    vx, pe = ix.get("vix") or {}, ix.get("pe50") or {}
    if vx.get("v") is not None or pe.get("pe") is not None:
        bits = []
        if vx.get("v") is not None:
            bits.append(f"India VIX {vx['v']:.2f} ({sgn(vx.get('d1'), 1)})")
        if pe.get("pe") is not None:
            bits.append(f"Nifty 50 P/E {pe['pe']:.1f}" + (f" ({'lowest since Apr 2021' if pe['p'] == 0 else ordinal(pe['p']) + ' percentile since Apr 2021'})" if pe.get("p") is not None else ""))
        lines.append(" · ".join(bits))
    if meta.get("asof") != today and now_ist.weekday() < 5 and now_ist.hour >= 18 and today not in hol:
        lines.append(f"⚠️ Prices are still from {datetime.strptime(meta['asof'], '%Y-%m-%d'):%d %b} — today's data did not arrive")
    th = []
    for name, syms in (groups or {}).get("Themes", {}).items():
        v = [by[s]["r"]["1M"] for s in syms if s in by and by[s]["r"].get("1M") is not None]
        if len(v) >= (meta.get("min_group_size") or 3):
            th.append((sum(v) / len(v), name))
    th.sort(reverse=True)
    if th:
        lines.append("Leading themes (1M): " + " · ".join(f"{E(n)} {sgn(v, 1)}" for v, n in th[:3]))
    G = load("grp.json")
    if G and G.get("rows"):
        # group signals that fired today and held up in testing (themes, sectors, NSE indices, industries; all stocks)
        names = {"g_rank": "RS rating climbing", "g_stage2m": "Stage 2 start with money", "g_stage2": "Stage 2 start",
                 "g_money": "Money flowing in"}
        kind = {"Themes": "theme", "Sector": "sector", "NSE Index": "index", "Industry": "industry"}
        got = []
        for sid, label in names.items():
            hit = [r for r in G["rows"] if (r.get("a") or {}).get("ago", {}).get(sid) == 0]
            if sid == "g_stage2":
                hit = [r for r in hit if (r.get("a") or {}).get("ago", {}).get("g_stage2m") != 0]
            if hit:
                hit.sort(key=lambda r: -((r.get("a") or {}).get("rk") or 0))
                got.append(f"{label}: " + ", ".join(f"{E(r['n'])} ({kind.get(r['k'], '')})" for r in hit[:6])
                           + (f" +{len(hit) - 6} more" if len(hit) > 6 else ""))
        if got:
            lines.append("Group signals today — " + " · ".join(got))

    gid, wl, state = (None, None, {})
    try:
        gid, wl, state = gist_load()
    except Exception as e:
        lines += ["", f"⚠️ Couldn't read your watchlists: {E(str(e))}"]
    if wl:
        syms = wl_symbols(wl)
        rets = []
        for L_ in wl.get("lists", []):
            for it in L_.get("items", []):
                px = (by.get(it["s"]) or {}).get("px")
                if px and it.get("p"):
                    rets.append((px / it["p"] - 1) * 100)
        al = watch_alerts(wl, by, scans_of, scan_name, closes, vp, asof, load("corp.json"))
        lines += ["", f"<b>⭐ Your watchlists</b> — {len(syms)} stocks" + (f" · average since added {sgn(sum(rets) / len(rets))}" if rets else "")]
        if al:
            for lvl, _, s, txt in al[:40]:
                lines.append(f"{ICON[lvl]} {sym(s)} — {E(txt)}")
            if len(al) > 40:
                lines.append(f"…and {len(al) - 40} more on the dashboard")
        else:
            lines.append("No alerts on your watchlists today.")
    elif GTOK:
        lines += ["", "⭐ No synced watchlists found — turn on <i>Sync devices</i> on the Watchlists tab."]

    top = lambda ids, n=8: sorted(ids, key=lambda s: -((by.get(s) or {}).get("rs") or 0))[:n]
    lines += ["", "<b>🔎 Today's scans</b>"]
    for sid, label in (("combo3", "Confluence (4+ signal groups)"), ("lb_breakout", "Long-base breakouts (100+ day bases)"), ("s2_early", "Early Stage 2, score 70+"), ("res_strong", "Strong results (Quality 70+, PEAD 7+)"), ("f_post", "Post-results breakouts"), ("high52_dcr", "52-week highs, strong close"), ("vcp", "VCP setups")):
        h = scans["hits"].get(sid) or []
        if h:
            lines.append(f"{label}: <b>{len(h)}</b> — " + ", ".join(sym(s) for s in top(h)))
    fresh = [s for s, r in vp.items() if "FRESH" in str(r.get("status", ""))]
    if fresh:
        lines.append(f"Fresh VPCI buys: <b>{len(fresh)}</b> — " + ", ".join(sym(s, vp[s].get("exchange") or "NSE") for s in fresh[:10]))
    mf_lines, mf_key = fund_flow_note(by, wl, state if gid else None)
    if mf_lines:
        lines += [""] + mf_lines
    if site_url():
        lines += ["", f'<a href="{site_url()}">Open the dashboard</a>']
    tg_send("\n".join(lines))
    if mf_key and gid:
        try:
            state["mf"] = mf_key
            state_save(gid, state)
        except Exception as e:
            print(f"could not save alert state: {e}")
    print(f"Evening digest sent ({len(lines)} lines)")


def fund_flow_note(by, wl, state):
    """A few lines on mutual-fund buying when a new month of fund portfolios is in (or many more fund houses were
    added to it). Returns (lines, key to remember) — nothing on other days."""
    M = load("mf.json")
    if not M or not M.get("stocks"):
        return [], None
    meta = M["meta"]
    latest, houses = meta.get("latest"), len(meta.get("coverage_latest", {}).get("amcs", []))
    if not latest or houses < 15:
        return [], None
    if state is not None:
        old = state.get("mf") or {}
        if old.get("m") == latest and houses < (old.get("n") or 0) + 5:
            return [], None
    elif meta.get("built") != datetime.now(IST).strftime("%Y-%m-%d"):
        return [], None
    y, m = latest.split("-")
    mon = datetime(int(y), int(m), 1).strftime("%B %Y")
    A = (meta.get("audit") or [{}])[-1]
    S = [z for z in M["stocks"] if z["net"]]
    last = lambda z: z["net"][-1]
    buy = sorted((z for z in S if not z.get("ipo") and last(z) > 0), key=lambda z: -last(z))[:6]
    sell = sorted((z for z in S if last(z) < 0), key=lambda z: last(z))[:6]
    cr = lambda v: f"₹{abs(v):,.0f} Cr"
    out = [f"<b>🏦 Mutual-fund portfolios · {mon}</b> ({houses} fund houses read)"]
    if A.get("active_net") is not None:
        out.append(f"Active funds net {'bought' if A['active_net'] >= 0 else 'sold'} {cr(A['active_net'])} of Indian stocks")
    if buy:
        out.append("Most bought: " + ", ".join(f"{sym(z['s'])} {cr(last(z))}" for z in buy))
    if sell:
        out.append("Most sold: " + ", ".join(f"{sym(z['s'])} {cr(last(z))}" for z in sell))
    if wl:
        by_mf = {z["s"]: z for z in S}
        mine = [(s, by_mf[s]) for s in wl_symbols(wl) if s in by_mf and abs(by_mf[s].get("bp") or 0) >= 0.1]
        if mine:
            out.append("Your watchlists: " + ", ".join(
                f"{sym(s)} {'bought' if last(z) > 0 else 'sold'} {cr(last(z))} ({sgn(z.get('bp'), 2)} of the company)" for s, z in mine[:10]))
    return out, {"m": latest, "n": houses}


# ───────────────────────────────────────────── live (market hours)
def upx(path):
    for a in range(4):
        try:
            r = requests.get(f"{UPX}/{path}", headers={**UA, "Accept": "application/json"}, timeout=20)
            if r.status_code == 200:
                j = r.json()
                return (j.get("data") or {}).get("candles") or []
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 + 2 * a)
                continue
            return []
        except requests.RequestException:
            time.sleep(2)
    return []


def live(force=False):
    now = datetime.now(IST)
    open_, close_ = now.replace(hour=9, minute=15, second=0), now.replace(hour=15, minute=35, second=0)
    if not force and (now.weekday() >= 5 or not open_ <= now <= close_):
        print(f"{now:%a %H:%M} IST - market closed, nothing to do")
        return
    try:
        hol = {h["date"]: h.get("name", "") for h in json.loads((CFG / "nse" / "holidays.json").read_text()).get("trading", [])}
    except (OSError, ValueError):
        hol = {}
    if not force and now.strftime("%Y-%m-%d") in hol:
        print(f"NSE holiday today ({hol[now.strftime('%Y-%m-%d')]}) - nothing to do")
        return
    gid, wl, state = gist_load()
    if not wl:
        print("No synced watchlists (GIST_TOKEN missing or Sync not turned on)")
        return
    today = now.strftime("%Y-%m-%d")
    if state.get("date") != today:
        state = {"date": today, "sent": []}
    keys = {}
    kf = CFG / "upstox_keys.csv"
    if kf.exists():
        for line in kf.read_text().splitlines()[1:]:
            s, k = line.split(",", 1)
            keys[s] = k
    meta = wl.get("meta", {})
    frac = max(0.05, min(1.0, ((now - open_).total_seconds() / 60) / 375))
    alerts = []
    for s in wl_symbols(wl):
        k = keys.get(s)
        if not k:
            continue
        m = meta.get(s) or {}
        day = upx(f"intraday/{quote(k, safe='')}/days/1")
        if not day:
            continue
        ts, o, hi, lo, ltp, vol = day[0][:6]
        if str(ts)[:10] != today:  # holiday / pre-open: no candle for today yet
            continue
        hist = upx(f"{quote(k, safe='')}/days/1/{(now - timedelta(days=1)):%Y-%m-%d}/{(now - timedelta(days=90)):%Y-%m-%d}")
        hist = sorted(hist, key=lambda c: c[0])
        if not hist:
            continue
        prev = hist[-1][4]
        av = [c[5] for c in hist[-50:] if c[5]]
        pace = vol / (sum(av) / len(av) * frac) if av else None
        chg = (ltp / prev - 1) * 100
        vtxt = f", volume pace {pace:.1f}× normal" if pace else ""
        lists = ", ".join(lists_of(wl, s))

        def add(kind, txt):
            key = f"{s}:{kind}"
            if key not in state["sent"]:
                state["sent"].append(key)
                alerts.append(f"{txt} <i>({E(lists)})</i>")
        piv, stop, tgt = m.get("pivot"), m.get("stop"), m.get("target")
        if stop and ltp < stop:
            add("stop", f"🛑 {sym(s)} below your stop ₹{inr(stop)} — now ₹{inr(ltp)} ({sgn(chg, 2)} today)")
        if tgt and ltp >= tgt:
            add("target", f"🎯 {sym(s)} hit your target ₹{inr(tgt)} — now ₹{inr(ltp)}")
        if piv:
            if prev <= piv < ltp:
                ext = (ltp / piv - 1) * 100
                add("pivot", f"🚀 {sym(s)} crossed your pivot ₹{inr(piv)} — now ₹{inr(ltp)} ({sgn(ext)} above{', extended' if ext > 5 else ''}){vtxt}")
            elif 0 < (piv / ltp - 1) * 100 <= 1:
                add("near", f"👀 {sym(s)} within {(piv / ltp - 1) * 100:.1f}% of your pivot ₹{inr(piv)} — now ₹{inr(ltp)}{vtxt}")
        if abs(chg) >= MOVE_PCT:
            add("up" if chg > 0 else "down", f"{'📈' if chg > 0 else '📉'} {sym(s)} {sgn(chg, 1)} today at ₹{inr(ltp)}{vtxt}")
        time.sleep(0.15)
    if alerts:
        tg_send(f"<b>⏰ {now:%H:%M} · live watchlist alerts</b>\n" + "\n".join(alerts))
        state_save(gid, state)
    print(f"{now:%H:%M} IST - {len(alerts)} new alerts")


# ───────────────────────────────────────────── test
def test():
    global CHAT
    me = tg("getMe")
    bot = me.get("username", "?")
    print(f"This token belongs to the bot @{bot}  (https://t.me/{bot})")
    if not CHAT:
        hook = tg("getWebhookInfo")
        if hook.get("url"):                       # a webhook blocks getUpdates - remove it
            tg("deleteWebhook")
            print("Removed a webhook that was set on this bot")
        ups = tg("getUpdates")
        chats = {}
        for u in ups:
            for k in ("message", "edited_message", "my_chat_member", "channel_post"):
                ch = (u.get(k) or {}).get("chat")
                if ch:
                    chats[ch["id"]] = ch.get("first_name") or ch.get("title") or ch.get("username") or ""
        print(f"Messages waiting for @{bot}: {len(ups)}")
        if not chats:
            print(f"No chat found. In Telegram open https://t.me/{bot} (exactly this bot), press Start, "
                  f"send it 'hi', then run this test again within a few minutes.")
            print("If you messaged a bot with a different name, the TELEGRAM_BOT_TOKEN secret is from another bot.")
            return
        CHAT = str(list(chats)[-1])
        print(f"YOUR TELEGRAM_CHAT_ID IS: {CHAT}  ({list(chats.values())[-1]}) - save it as a repository secret")
    lines = ["<b>✅ PKC Sector Radar is connected to Telegram</b>"]
    try:
        gid, wl, _ = gist_load()
        if wl:
            n = len(wl_symbols(wl))
            lv = sum(1 for s, m in (wl.get("meta") or {}).items() if m and (m.get("pivot") or m.get("stop") or m.get("target")))
            lines.append(f"Found your synced watchlists: {len(wl.get('lists', []))} lists, {n} stocks, {lv} with pivot/stop/target set.")
        else:
            lines.append("Watchlists not found yet — add the GIST_TOKEN secret and turn on Sync devices on the Watchlists tab.")
    except Exception as e:
        lines.append(f"Couldn't read watchlists: {E(str(e))}")
    lines.append("You'll get an evening digest after each daily update, and live alerts every 15 minutes in market hours.")
    tg_send("\n".join(lines))
    print("Test message sent")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--evening", action="store_true")
    g.add_argument("--live", action="store_true")
    g.add_argument("--test", action="store_true")
    ap.add_argument("--force", action="store_true", help="live: run even outside market hours")
    a = ap.parse_args()
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN not set - Telegram alerts are off")
        return 0
    if not CHAT and not a.test:
        print("TELEGRAM_CHAT_ID not set - run the Telegram workflow once with mode 'test' to find it")
        return 0
    if a.test:
        test()
    elif a.evening:
        evening()
    else:
        live(a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
