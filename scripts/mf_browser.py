"""Listers for fund houses whose sites only work in a real browser (their list APIs are encrypted).

Uses Playwright's headless Chromium. In the GitHub workflow:
    pip install playwright && python -m playwright install --with-deps chromium
Each function returns [{"url", "name"}] like the listers in mf_sources.py, or raises if the page did not load —
a fund house that fails is skipped for that run and retried on the next one, never saved half-read.
"""
import asyncio
import os
import re
import urllib.parse as up

from mf_sources import MONTH, month_of, day_of

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
SKIP = re.compile(r"liquid|overnight|money market|gilt|g-sec|sdl|crisil|ibx|bond|debt|credit risk|duration|floating|"
                  r"income plus|banking and psu|fixed (term|maturity)|fmp|gold|silver|fof|fund of fund|us specific|"
                  r"treasury|medium term|long term fund|short term|ultra short|dynamic term|constant maturity|"
                  r"corporate bond|^(?!.*equity).*savings fund", re.I)


CLEAR_JS = """() => { let n = 0;
  document.querySelectorAll('div.fixed.top-0.left-0.w-full.h-full').forEach(e => {
    if (e.querySelector('[role=dialog]')) { e.remove(); n++; } });          // festive / login pop-ups
  return n; }"""
LOADER_JS = "() => ![...document.querySelectorAll('img[src*=loader]')].some(i => i.offsetParent !== null)"


async def _settle(pg):
    """Close pop-ups that cover the page and wait for the loading spinner to go."""
    try:
        await pg.wait_for_function(LOADER_JS, timeout=30000)
    except Exception:
        pass
    await pg.evaluate(CLEAR_JS)


async def _click(pg, loc, timeout=8000):
    """Click; when a pop-up or the spinner still covers the page, clear it and click through JavaScript."""
    try:
        await loc.click(timeout=timeout)
    except Exception:
        await _settle(pg)
        await loc.evaluate("e => e.click()")


def _launch_kw():
    kw = {}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy and "127.0.0.1" in proxy:          # local sandbox proxy (not used on GitHub)
        kw["proxy"] = {"server": proxy}
    return kw


async def _bandhan_page(ctx, y, m):
    """A page on the portfolio list with year and month chosen. Returns (page, dropdowns, captured download urls)."""
    pg = await ctx.new_page()
    pg.set_default_timeout(10000)
    got = []

    async def route(rt):
        u = rt.request.url
        if "download-doc" in u:
            got.append(u)
            await rt.fulfill(status=204, body="")      # a 204 answer leaves the page where it is
        else:
            await rt.continue_()
    await pg.route("**/*", route)
    await pg.goto("https://bandhanmutual.com/statutory-disclosures/scheme-portfolios", wait_until="domcontentloaded", timeout=90000)
    await pg.wait_for_timeout(8000)
    await _settle(pg)
    await _click(pg, pg.get_by_role("button", name="Monthly and Half Yearly"))
    await pg.wait_for_timeout(2500)
    dd = pg.locator("button.w-full.flex.justify-between.items-center")
    if await dd.count() < 3:
        raise RuntimeError("Bandhan page layout changed (dropdowns not found)")
    for i, text in ((0, str(y)), (1, MONTH[m])):
        await _settle(pg)
        await _click(pg, dd.nth(i))
        await pg.wait_for_timeout(1000)
        await _click(pg, pg.locator("li").filter(has_text=re.compile(r"^\s*" + re.escape(text) + r"\s*$")).first)
        await pg.wait_for_timeout(2500)
    return pg, dd, got


async def _bandhan(y, m):
    from playwright.async_api import async_playwright
    out = []
    verbose = bool(os.environ.get("MF_VERBOSE"))
    async with async_playwright() as p:
        b = await p.chromium.launch(**_launch_kw())
        ctx = await b.new_context(user_agent=UA)
        pg, dd, _ = await _bandhan_page(ctx, y, m)
        await _settle(pg)
        await _click(pg, dd.nth(2))
        await pg.wait_for_timeout(1200)
        names = await pg.evaluate("""()=>[...document.querySelectorAll('li')].filter(e=>e.offsetParent!==null)
                                       .map(e=>e.innerText.trim()).filter(t=>/^Bandhan /.test(t))""")
        await pg.keyboard.press("Escape")
        await pg.close()
        if len(names) < 20:
            raise RuntimeError(f"Bandhan scheme list too short ({len(names)})")
        limit = int(os.environ.get("MF_BROWSER_LIMIT", "0") or 0)
        todo = [nm for nm in names if not SKIP.search(nm)]
        only = os.environ.get("MF_BROWSER_ONLY")
        if only:
            todo = [nm for nm in todo if re.search(only, nm, re.I)]
        if limit:
            todo = todo[:limit]

        async def grab(pg, dd, got, nm):
            """Select one scheme and collect its month-end file. True when a file was captured."""
            try:
                await _settle(pg)
                await _click(pg, dd.nth(2))
                await pg.wait_for_timeout(700)
                await _click(pg, pg.locator("li").filter(has_text=re.compile(r"^\s*" + re.escape(nm) + r"\s*$")).first)
                await pg.wait_for_timeout(2200)
                await _settle(pg)
            except Exception as e:
                if verbose:
                    print(f"   bandhan {nm[:50]}: could not select ({str(e)[:120]})", flush=True)
                await pg.keyboard.press("Escape")
                return False
            # one row per document: "<scheme> 30 September 2026" (month end) — skip mid-month / half-year rows
            rows = pg.locator("div.flex-1 > div")
            n, ok = await rows.count(), False
            for k in range(n):
                t = (await rows.nth(k).inner_text()).strip()
                if month_of(t) != (y, m) or (day_of(t) or 0) < 28 or re.search(r"half|fortnight", t, re.I):
                    continue
                before = len(got)
                try:
                    await _settle(pg)
                    await rows.nth(k).locator("xpath=../following-sibling::button[1]").click()
                    await pg.wait_for_timeout(1200)
                except Exception:
                    continue
                if len(got) > before:
                    q = dict(up.parse_qsl(up.urlsplit(got[-1]).query))
                    if q.get("filepath"):
                        out.append({"url": q["filepath"], "name": t}); ok = True
            if verbose:
                print(f"   bandhan {nm[:50]:50s} rows {n:2d} files {len(out)}", flush=True)
            return ok

        async def worker(chunk):
            """Its own page; returns the schemes it could not get (each is tried twice)."""
            try:
                wp, wdd, wgot = await _bandhan_page(ctx, y, m)
            except Exception as e:
                if verbose:
                    print(f"   bandhan worker could not open the page: {str(e)[:120]}", flush=True)
                return list(chunk)
            missed = [nm for nm in chunk if not await grab(wp, wdd, wgot, nm)]
            missed = [nm for nm in missed if not await grab(wp, wdd, wgot, nm)]
            await wp.close()
            return missed

        W = max(1, min(int(os.environ.get("MF_BROWSER_PAGES", "4") or 4), len(todo)))
        chunks = [todo[i::W] for i in range(W)]
        missed = [nm for part in await asyncio.gather(*(worker(c) for c in chunks)) for nm in part]
        no_file = len(missed)
        await b.close()
        if no_file > max(3, 0.15 * len(todo)):
            raise RuntimeError(f"Bandhan: no month-end file for {no_file} of {len(todo)} schemes ({', '.join(missed[:5])}...)")
    seen, uniq = set(), []
    for f in out:
        if f["url"] not in seen:
            seen.add(f["url"]); uniq.append(f)
    return uniq


def bandhan(y, m):
    return asyncio.run(_bandhan(y, m))
