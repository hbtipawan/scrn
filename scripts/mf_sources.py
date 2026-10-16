"""Where each fund house publishes its monthly portfolio, and how to list the files for a given month.

SEBI requires every fund house to publish the full portfolio of every scheme within 10 days of each
month end, on its own website. There is no central copy, so each site is handled here:

    SOURCES[code] = (name, lister)          lister(year, month) -> [{"url", "name"}] or [] if not out yet

A lister returns the files for the portfolio dated at the end of (year, month). Files are fetched by
http_get(), which uses a browser-like TLS fingerprint (several sites reject plain scripts).
Each lister is small on purpose: when a fund house redesigns its site, only its lister changes.
"""
import calendar
import html as _html
import json
import re
import time
import urllib.parse as up

try:
    from curl_cffi import requests as _cr
except ImportError:          # the GitHub workflow installs curl_cffi; plain requests is the fallback
    _cr = None
import requests as _rq

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_S = None


def session():
    global _S
    if _S is None:
        _S = _cr.Session(impersonate="chrome") if _cr else _rq.Session()
        if not _cr:
            _S.headers["User-Agent"] = UA
    return _S


PLAIN_HOSTS = {"www.assetmanagement.hsbc.co.in", "abcscprod.azureedge.net"}   # break with the browser fingerprint, fine with plain requests
_P = None


def _plain():
    global _P
    if _P is None:
        _P = _rq.Session(); _P.headers["User-Agent"] = UA
    return _P


def http(method, url, tries=3, timeout=60, **kw):
    """Request with retries. A host that fails with the browser fingerprint is retried with plain requests,
    and remembered for the rest of the run."""
    last = None
    host = up.urlsplit(url).netloc.lower()
    for k in range(tries):
        plain = host in PLAIN_HOSTS
        try:
            r = (_plain() if plain else session()).request(method, url, timeout=timeout, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(2 + 4 * k)
                continue
            return r
        except Exception as e:          # network hiccup or fingerprint trouble: retry, switching client once
            last = e
            if not plain and _cr is not None:
                try:
                    r = _plain().request(method, url, timeout=timeout, **kw)
                    if r.status_code < 500:
                        PLAIN_HOSTS.add(host)
                        return r
                except Exception:
                    pass
            time.sleep(2 + 4 * k)
    raise last


def http_get(url, **kw):
    return http("GET", url, **kw)


MONTH = list(calendar.month_name)          # ["", "January", ...]
MON3 = [m[:3] for m in MONTH]


def month_of(text):
    """(year, month) named in a file name / title, e.g. 'NIMF-MONTHLY-PORTFOLIO-31-July-25.xls'."""
    t = up.unquote(text or "").lower().replace("_", " ").replace("-", " ").replace(".", " ")
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    names = "|".join(sorted({m.lower() for m in MONTH[1:]} | {m.lower() for m in MON3[1:]} | {"sept"}, key=len, reverse=True))
    for m in re.finditer(rf"\b({names})[a-z]*\s*,?\s*(?:\d{{1,2}}\s*,?\s*)?((?:19|20)?\d{{2}})\b", t):
        mon = m.group(1)[:3]
        y = int(m.group(2)); y = y + 2000 if y < 100 else y
        if 2005 <= y <= 2100:
            return y, MON3.index(mon.capitalize())
    m = re.search(r"\b(\d{1,2})\s(\d{1,2})\s(20\d{2})\b", t)          # 30 09 2026
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(3)), int(m.group(2))
    m = re.search(r"\b(20\d{2})\s(\d{2})\s(\d{2})\b", t)               # 2026 09 30
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\b([0-3]?\d)\s([01]?\d)\s(\d{2})\b", t)                # 30 09 25
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
        return 2000 + int(m.group(3)), int(m.group(2))
    m = re.search(r"\b(\d{2})(\d{2})(20\d{2})\b", t)                   # 30092026
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
        return int(m.group(3)), int(m.group(2))
    return None


def day_of(text):
    """Day of month in a title like 'as on 30th September 2026' / 'September 30, 2026' / '30.09.2026', else None."""
    t = up.unquote(text or "").lower()
    names = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-_.,]*(?:{names})[a-z]*", t) or re.search(rf"(?:{names})[a-z]*[\s\-_.,]*(\d{{1,2}})(?:st|nd|rd|th)?\b[\s,]*\d{{4}}", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,2})[\-./ ](\d{1,2})[\-./ ](20\d{2})\b", t)
    return int(m.group(1)) if m else None


def month_end(y, m):
    return calendar.monthrange(y, m)[1]


def _links(html_text, base, pat=r"\.(?:xlsx?|xlsb|zip)(?:\?|$)"):
    out = []
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html_text, re.S | re.I):
        href = _html.unescape(m.group(1)).strip()
        if re.search(pat, href, re.I):
            out.append((up.urljoin(base, href), re.sub(r"<[^>]+>|\s+", " ", _html.unescape(m.group(2))).strip()))
    return out


def _pick_month(links, y, m, must=None, exclude=r"fortnight|half[\s\-_]?year|weekly|daily|factsheet|riskometer|risk[\s\-_]?o[\s\-_]?meter|sid|kim"):
    """Links whose name or URL names (y, m)."""
    out = []
    for url, text in links:
        key = f"{text} {up.unquote(url.rsplit('/', 1)[-1])}"
        if must and not re.search(must, key, re.I):
            continue
        if exclude and re.search(exclude, key, re.I):
            continue
        if month_of(text) == (y, m) or month_of(url.rsplit("/", 1)[-1]) == (y, m):
            out.append({"url": url, "name": text or up.unquote(url.rsplit("/", 1)[-1])})
    seen, uniq = set(), []
    for f in out:
        if f["url"] not in seen:
            seen.add(f["url"]); uniq.append(f)
    return uniq


_PAGES = {}


def _page_links(url, timeout=90):
    if url not in _PAGES:
        _PAGES[url] = _links(http_get(url, timeout=timeout).text, url)
    return _PAGES[url]


def static_lister(page, must, exclude=r"fortnight|half[\s\-_]?year|weekly|overlap|factsheet|risk|aaum|performance|complaint|dashboard",
                  one=False, prefer=None):
    """Lister for fund houses that list every monthly file as a plain link on one page.
    must / exclude are matched against the link text + decoded file name; the month comes from either."""
    def lister(y, m):
        out, seen = [], set()
        for u, t in _page_links(page):
            fname = up.unquote(u.split("?")[0].rsplit("/", 1)[-1])
            if not re.search(r"\.(xlsx?|xlsb|zip)$", fname, re.I):          # viewfile.php?file=NAME.xlsx
                q = dict(up.parse_qsl(up.urlsplit(u).query))
                fname = q.get("file") or q.get("filename") or up.unquote(u)
            key = f"{t} {up.unquote(u)}"
            if not re.search(must, key, re.I) or (exclude and re.search(exclude, key, re.I)):
                continue
            if (month_of(fname) or month_of(up.unquote(u)) or month_of(t)) != (y, m):
                continue
            k = fname.lower()
            if prefer:                                   # same file on two hosts: keep the preferred host
                k = re.sub(r"^.*?(in_mf|nj-mf)", r"\1", k)
            if k in seen:
                continue
            seen.add(k)
            out.append({"url": u, "name": t if len(t) > 12 and not re.fullmatch(r"(?i)download|view|click here", t) else fname})
        if prefer:
            out.sort(key=lambda f: 0 if re.search(prefer, f["url"], re.I) else 1)
        return out[:1] if one else out
    return lister


# ════════════════════════════════════════════════ fund houses
def baroda(y, m):
    """Baroda BNP Paribas: the page shows only the newest file; older ones come from its 'load more' AJAX call,
    filtered by the month the file was uploaded (the month after the portfolio date, sometimes later)."""
    page = "https://www.barodabnpparibasmf.in/downloads/monthly-portfolio-scheme"
    r = http("GET", page)
    csrf = re.search(r'name="csrf_test_name" value="([^"]+)"', r.text)
    cat = re.search(r'id="category" value="(\d+)"', r.text)
    if not csrf or not cat:
        raise RuntimeError("Baroda BNP page layout changed")
    base = "https://www.barodabnpparibasmf.in/"
    out = []
    uy, um = y, m
    for _ in range(2):                                       # uploaded next month, or the one after
        um += 1
        if um == 13:
            uy, um = uy + 1, 1
        r2 = http("POST", base + "ajax-load-more-documents-new", headers={"X-Requested-With": "XMLHttpRequest", "Referer": page},
                  data={"csrf_test_name": csrf.group(1), "cnt": "48", "pagination": "0", "send_category": cat.group(1),
                        "send_year": str(uy), "send_month": str(um), "remaining_cnt": "0"})
        links = _links(r2.json().get("data", ""), base)
        out = [f for f in _pick_month(links, y, m, must=r"monthly[_\s\-]*portfolio")]
        if out:
            break
    seen, uniq = set(), []
    for f in out:
        if f["url"] not in seen:
            seen.add(f["url"]); uniq.append({"url": f["url"], "name": up.unquote(f["url"].rsplit("/", 1)[-1])})
    return uniq[:1]


def sbi(y, m):
    r = http("POST", "https://www.sbimf.com/ajaxcall/CMS/GetSchemePortfolioSheets",
             json={"FundId": 0, "PSYear": str(y), "PSMonth": MONTH[m], "PSFrequency": "Monthly"})
    links = _links(r.text, "https://www.sbimf.com/")
    return [f for f in _pick_month(links, y, m, must=r"all[\s\-]+schemes?\b")][:1]


def hdfc(y, m):
    base = "https://cms.hdfcfund.com/en/hdfc/api/v2/disclosures/"
    hdr = {"origin": "https://www.hdfcfund.com", "referer": "https://www.hdfcfund.com/"}
    out = []
    for fy in sorted({y, y - 1} if m <= 3 else {y, y + 1}):       # the site files Jan-Mar under either year
        r = http("POST", base + "monthfortportfolio", data={"year": str(fy), "type": "monthly", "month": str(m)}, headers=hdr)
        try:
            files = r.json()["data"]["files"]
        except Exception:
            continue
        best = {}
        for f in files:
            title = f.get("title") or f["file"]["filename"]
            if month_of(title) != (y, m):
                continue
            key = re.sub(r"[^a-z0-9]+", " ", re.sub(r"\.xlsx?$|_\d+$", "", title.lower())).strip()
            fid = int(f.get("file_id") or 0)
            if key not in best or fid > best[key][0]:          # a re-upload replaces the earlier file
                best[key] = (fid, {"url": f["file"]["url"], "name": title})
        out = [v for _, v in best.values()]
        if out:
            break
    return out


def icici(y, m):
    full = MONTH[m]
    for folder in (MON3[m], full):
        u = (f"https://www.icicipruamc.com/blob/downloads/Files/Monthly%20Portfolio%20Disclosures/{y}/{folder}/"
             f"Monthly-Portfolio-Disclosure-{full}-{y}.zip")
        r = http("HEAD", u, allow_redirects=True)
        if r.status_code == 200:
            return [{"url": u, "name": f"Monthly-Portfolio-Disclosure-{full}-{y}.zip"}]
    return []


_NIPPON = None


def nippon(y, m):
    global _NIPPON
    if _NIPPON is None:
        u = "https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures"
        _NIPPON = _links(http_get(u).text, u)
    return _pick_month([(u, t) for u, t in _NIPPON if re.search(r"monthly[\-_ ]+portfolio", u, re.I)], y, m,
                       exclude=r"fortnight|risk")[:1]


_KOTAK = None


def kotak(y, m):
    """Consolidated SEBI portfolio (all schemes, one workbook) from the forms & downloads list."""
    global _KOTAK
    if _KOTAK is None:
        _KOTAK = []
        for page in range(1, 8):
            r = http_get("https://www.kotakmf.com/api/kotakapi/forms/user/getsubheaderList/417",
                         params={"option": "51", "pagination": "1", "pageSize": "100", "pageNumber": str(page)})
            items = (r.json() or {}).get("subHeaderList") or []
            _KOTAK += items
            if len(items) < 100:
                break
    out = []
    for it in _KOTAK:
        t = it.get("subHeaderTitle") or ""
        if re.search(r"consolidated", t, re.I) and not re.search(r"fortnight", t, re.I) and month_of(t) == (y, m) and it.get("content"):
            out.append({"url": "https://vatseelabs-s3.kotakmf.com/" + up.quote(it["content"]), "name": t})
    return out[:1]


def axis(y, m):
    h = {"origin": "https://www.axismf.com", "referer": "https://www.axismf.com/statutory-disclosures"}
    tok = http("POST", "https://www.axismf.com/cms/token", json={}, headers=h).json()["data"]["token"]
    r = http("POST", "https://www.axismf.com/cms/get-scheme-documents", headers={**h, "authorization": tok},
             json={"sdType": "yearMonthSchemeDocs", "sdID": "sdMonthSchemePortfolio", "year": str(y), "month": MONTH[m], "schemeCode": "Consolidated"})
    docs = ((r.json() or {}).get("data") or {}).get("documentList") or []
    out = [{"url": d["docuementURL"], "name": d["documentName"]} for d in docs
           if re.match(r"\s*monthly\s+portfolio", d.get("documentName") or "", re.I) and month_of(d["documentName"]) == (y, m)]
    return out[:1]


_ABSL = None


def absl(y, m):
    global _ABSL
    if _ABSL is None:
        u = ("https://mutualfund.adityabirlacapital.com/postlogin/CustomApi/Resources/FactsheetAccordionById?id=3ccab227-9de5-4494-b78d-2b4f7c0c054a"
             "&ctype=%2Fsitecore%2Fcontent%2FRoot%2FBSL%2FLibrary%2FLists%2FFAQ%2FCustomer%20Types%2FIndividual&month=%20&year=0")
        _ABSL = http_get(u, headers={"x-requested-with": "XMLHttpRequest", "content-type": "application/json"}).json()["AccordionList"]
    out = [{"url": re.sub(r"^https?://abcscprod\.azureedge\.net", "https://mutualfund.adityabirlacapital.com", x["pdfUrl"]),
            "name": x["ResourceLink"]} for x in _ABSL
           if re.match(r"monthly portfolios? as on", x.get("ResourceLink") or "", re.I) and month_of(x["ResourceLink"]) == (y, m)]
    return out[:1]


_MIRAE = None


def mirae(y, m):
    """Per-scheme workbooks; the list API pages newest first."""
    global _MIRAE
    if _MIRAE is None:
        _MIRAE = []
        h = {"x-requested-with": "XMLHttpRequest", "referer": "https://www.miraeassetmf.co.in/downloads/portfolio", "origin": "https://www.miraeassetmf.co.in"}
        for pg in range(1, 5):
            r = http("POST", "https://www.miraeassetmf.co.in/AjaxService/GetDownloadsData", headers=h,
                     json={"request": {"modulename": "portfolio_tab1", "pgno": pg, "pgsize": 500}})
            d = r.json().get("Data") or []
            _MIRAE += d
            if len(d) < 500 or all((month_of(x["Title"]) or (0, 0)) < (2025, 1) for x in d[-20:]):
                break
    out = []
    for x in _MIRAE:
        t = x.get("Title") or ""
        if month_of(t) == (y, m) and (day_of(t) or 0) >= 28:
            out.append({"url": up.urljoin("https://www.miraeassetmf.co.in/", x["URL"]), "name": t})
    return out


_DSP = None


def dsp(y, m):
    global _DSP
    if _DSP is None:
        u = "https://www.dspim.com/mandatory-disclosures/portfolio-disclosures"
        _DSP = _links(http_get(u).text, u)
    return _pick_month([(u, t) for u, t in _DSP if re.search(r"month[\-_ ]?end", u, re.I)], y, m)[:1]


def uti(y, m):
    r = http_get("https://www.utimf.com/api/get-consolidate-portfolio-disclosure", params={"year": str(y), "month": MONTH[m]})
    rows = (r.json() or {}).get("rows") or []
    return [{"url": x.get("url") or x.get("doc"), "name": x.get("name")} for x in rows
            if (x.get("url") or x.get("doc")) and re.search(r"consolidat", x.get("name") or "", re.I)][:1]


_TATA = None


def tata(y, m):
    """The list sits in the page's React payload as {field_document_title, field_media_document} rows."""
    global _TATA
    if _TATA is None:
        t = http_get("https://www.tatamutualfund.com/schemes-related/portfolio").text.replace('\\"', '"')
        _TATA = re.findall(r'"field_document_title":"([^"]+)","field_media_document":"(https?://[^"]+)"', t)
    out = []
    for title, url in _TATA:
        if re.match(r"\s*portfolio as on", title, re.I) and month_of(title) == (y, m) and (day_of(title) or 0) >= 28 \
                and re.search(r"\.xlsx?$", url, re.I) and not re.search(r"fortnight", title + url, re.I):
            out.append({"url": url, "name": title})
    return out[:1]


_PPFAS = None


def ppfas(y, m):
    global _PPFAS
    if _PPFAS is None:
        u = "https://amc.ppfas.com/downloads/portfolio-disclosure/"
        _PPFAS = _links(http_get(u).text, u)
    return _pick_month([(u, t) for u, t in _PPFAS if t.strip().lower() == "consolidated"], y, m)[:1]


_MOSL = None


def motilal(y, m):
    global _MOSL
    if _MOSL is None:
        r = http_get("https://www.motilaloswalmf.com/content/aem-cloud-dept-backend-motilal-oswal/api/search-documents.json",
                     params={"year": "", "category": "month end portfolio", "month": "", "type": "mf"})
        _MOSL = r.json().get("results") or []
    out = []
    for d in _MOSL:
        title, path = d.get("title") or "", d.get("path") or ""
        if re.match(r"\s*scheme portfolio details", title, re.I) and month_of(title) == (y, m) and re.search(r"\.xlsx?$", path, re.I) \
                and not re.search(r"fortnight|forthnight|half", title + path, re.I):
            out.append({"url": "https://www.motilaloswalmf.com" + up.quote(path), "name": title,
                        "rank": 0 if re.search(r"portfolioholding|scheme-portfolio-details", path, re.I) else 1})
    return sorted(out, key=lambda f: f["rank"])       # candidates; the fetcher keeps the first whose own date matches


def invesco(y, m):
    import xml.etree.ElementTree as ET
    ns = {"a": "http://schemas.datacontract.org/2004/07/SitefinityWebApp.Models"}
    want = f"{m:02d}/{y % 100:02d}"
    out = []
    for cls in ("equity", "hybrid", "index-funds", "exchange-traded-fund"):
        # a class that fails to load must fail the whole month: a partial list would read as funds selling out
        r = http_get("https://invescomutualfund.com/api/CompleteMonthlyHoldings", params={"year": str(y), "classification": cls}, tries=4)
        root = ET.fromstring(r.content)
        for it in root.findall("a:clsCompleteMonthlyHoldings", ns):
            nm = (it.findtext("a:Name", default="", namespaces=ns) or "").strip()
            if (it.findtext(f"a:{MON3[m]}Name", default="", namespaces=ns) or "").strip() == want:
                u = (it.findtext(f"a:{MON3[m]}Url", default="", namespaces=ns) or "").strip()
                if u:
                    out.append({"url": u, "name": f"Invesco India {nm} {MONTH[m]} {y}"})
    return out


def canara(y, m):
    """Server-rendered list, 10 schemes a page: ?filteryear=YYYY&filtermonth=MM&pagination=N."""
    base = "https://www.canararobeco.com/documents/statutory-disclosures/scheme-dashboard/scheme-monthly-portfolio/"
    out, seen = [], set()
    for page in range(1, 8):
        t = http_get(base, params={"filteryear": str(y), "filtermonth": f"{m:02d}", "pagination": str(page)}).text
        new = 0
        for u, txt in _links(t, base):
            f = up.unquote(u.rsplit("/", 1)[-1])
            if u in seen or not re.search(r"canara[\-\s]robeco", f, re.I) or month_of(f) != (y, m):
                continue
            if re.search(r"\d{1,2}(st|nd|rd|th)[\-\s]|dashboard|overlap|fortnight", f, re.I):
                continue
            seen.add(u); new += 1
            out.append({"url": u, "name": txt if txt.lower() != "download" else f})
        if not new or not re.search(rf"pagination={page + 1}\b", t):
            break
    return out


_HSBC = None


def hsbc(y, m):
    """Per-scheme workbooks under /portfolios/document-DDMMYYYY/ on the information library page."""
    global _HSBC
    if _HSBC is None:
        u = "https://www.assetmanagement.hsbc.co.in/en/mutual-funds/investor-resources/information-library"
        _HSBC = _links(http_get(u, timeout=120).text, u)
    tag = f"document-{month_end(y, m):02d}{m:02d}{y}/"
    out, seen = [], set()
    for u, t in _HSBC:
        if tag in u and u not in seen and not re.search(r"fortnight", u, re.I):
            seen.add(u); out.append({"url": u, "name": t})
    return out


_FRANK = None


def franklin(y, m):
    global _FRANK
    if _FRANK is None:
        t = http_get("https://www.franklintempletonindia.com/api/literature/v1/responseLitJson", params={"type": "report"}, timeout=120).text
        _FRANK = re.findall(r'\{"id":"MONTHLY-PORTFOLIO-DSCLR","documentId":"[^"]+","dctermsTitle":"([^"]+)","dctermsType":"[^"]*",'
                            r'"frkReferenceDate":"[^"]*","literatureHref":"([^"]+)"', t)
    out = [{"url": "https://www.franklintempletonindia.com/download" + h, "name": t} for t, h in _FRANK
           if re.match(r"\s*isin as on", t, re.I) and month_of(t) == (y, m) and re.search(r"\.xlsx?$", h, re.I)]
    return out[:1]


def quant(y, m):
    cat = "MONTHLY PORTFOLIO - FUND - WISE"
    h = {"content-type": "application/json; charset=utf-8", "x-requested-with": "XMLHttpRequest",
         "referer": "https://quantmutual.com/statutory-disclosures", "origin": "https://quantmutual.com"}
    r = http("POST", "https://quantmutual.com/statutorydisclosures.aspx/displaydisclouser2",
             data=json.dumps({"id": str(m), "cat": cat, "tab": str(y)}), headers=h)
    d = (r.json() or {}).get("d", "") if r.status_code == 200 else ""
    return [{"url": u, "name": t} for u, t in _links(d, "https://quantmutual.com/") if month_of(u.rsplit("/", 1)[-1]) == (y, m)]


_WOAK = None


def whiteoak(y, m):
    """Strapi CMS list, newest first; one workbook per scheme."""
    global _WOAK
    if _WOAK is None:
        _WOAK = []
        for pg in range(1, 30):
            r = http_get("https://cms.whiteoakamc.com/api/scheme-portfolios",
                         params={"pagination[page]": pg, "pagination[pageSize]": 100, "sort[0]": "published_date:desc",
                                 "sort[1]": "id:desc", "populate": "*"})
            d = r.json()
            _WOAK += d.get("data") or []
            meta = (d.get("meta") or {}).get("pagination") or {}
            if pg >= meta.get("pageCount", 0):
                break
    out = []
    for x in _WOAK:
        a = x.get("attributes") or {}
        if (a.get("period") or "").lower() != "monthly" or month_of(a.get("doc_name") or "") != (y, m):
            continue
        f = (((a.get("doc_file") or {}).get("data") or {}).get("attributes") or {})
        u = f.get("url") or a.get("doc_link")
        if u:
            out.append({"url": u, "name": a.get("doc_name") or f.get("name")})
    return out


_PGIM = None


def pgim(y, m):
    """Disclosure API: tabs Equity / Debt / Fund of Funds, one workbook per scheme."""
    global _PGIM
    if _PGIM is None:
        r = http("POST", "https://www.pgimindia.com/api/v1/brochure/published/disclosure",
                 json={"headerId": 2, "sectionId": "SECTION_747960037", "source": "W", "branchCode": None})
        _PGIM = [(t.get("tabName"), c) for t in (r.json().get("data") or []) for c in (t.get("content") or [])]
    out = []
    for tab, c in _PGIM:
        if tab not in ("Equity", "Debt"):
            continue
        try:
            ym = (int(c.get("year")), MONTH.index(str(c.get("month")).strip().capitalize()))
        except (TypeError, ValueError):
            ym = month_of(c.get("title") or "")
        if ym == (y, m) and c.get("pdfPath"):
            out.append({"url": c["pdfPath"].replace(" ", "%20"), "name": c.get("title")})
    return out


_SUND = None


def sundaram(y, m):
    """AjaxPro method on the portfolio page returns every month's links (equity & FoF file + fixed-income file)."""
    global _SUND
    if _SUND is None:
        page = "https://www.sundarammutual.com/Monthly-Fortnightly-Adhoc-Portfolios"
        t = http_get(page).text
        mm = re.search(r'src="(/ajax/Modules_Disclosure_Monthly_Fortnightly_Adhoc_Portfolios,[^"]+\.ashx)"', t)
        if not mm:
            raise RuntimeError("Sundaram page layout changed")
        u = "https://www.sundarammutual.com" + mm.group(1) + "?_method=GetCategory&_session=no"
        r = http("POST", u, data="Catid=Monthly", headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Referer": page})
        body = r.text.strip().strip("'").replace("\\'", "'")
        _SUND = _links(body, "https://www.sundarammutual.com/")
    return [{"url": u, "name": t} for u, t in _SUND if re.search(r"monthly portfolio", t, re.I) and month_of(t) == (y, m)]


def lic(y, m):
    """Consolidated monthly portfolio (equity file + debt file) from the downloads form."""
    h = {"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.licmf.com/downloads/monthly-portfolio",
         "Origin": "https://www.licmf.com"}
    http_get("https://www.licmf.com/downloads/monthly-portfolio")
    r = http("POST", "https://www.licmf.com/downloads/consolidated-portfolio-files", headers=h,
             data={"id": "639", "month": str(m), "year": str(y)})
    return [{"url": u.replace(" ", "%20"), "name": up.unquote(u.rsplit("/", 1)[-1])}
            for u, t in _links(r.text, "https://www.licmf.com/") if re.search(r"monthly", u, re.I)]


_BOI = None


def boi(y, m):
    """Document library API (folder 'MONTHLY PORTFOLIO'); one consolidated workbook a month."""
    global _BOI
    if _BOI is None:
        h = {"Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest",
             "Referer": "https://www.boimf.in/investor-corner", "Origin": "https://www.boimf.in"}
        http_get("https://www.boimf.in/investor-corner")
        r = http("POST", "https://www.boimf.in/AjaxService.asmx/GetDocuments", headers=h,
                 data=json.dumps({"pagno": 0, "category": None, "fromDate": None, "toDate": None, "LibraryName": "InvestorCorner",
                                  "folderName": "MONTHLY PORTFOLIO", "CategoryValue": "no"}))
        _BOI = json.loads(r.json()["d"]).get("Documents") or []
    return [{"url": d["FolderUrl"], "name": d.get("DocName")} for d in _BOI
            if month_of(d.get("DocName") or "") == (y, m) and re.search(r"\.xlsx?(\?|$)", d.get("FolderUrl") or "", re.I)][:1]


_BAJAJ = None


def bajaj(y, m):
    """WordPress media library: the consolidated 'Bajaj Finserv Mutual Fund_Monthly Portfolio as on ...' workbook
    (older months sit under /sites/default/files on the previous site; those are found the same way)."""
    global _BAJAJ
    if _BAJAJ is None:
        _BAJAJ = []
        for pg in range(1, 6):
            r = http_get("https://www.bajajamc.com/wp-json/wp/v2/media",
                         params={"search": "Bajaj Finserv Mutual Fund_Monthly Portfolio", "per_page": 100, "page": pg})
            d = r.json() if r.status_code == 200 else []
            _BAJAJ += d
            if len(d) < 100:
                break
    out = []
    for x in sorted(_BAJAJ, key=lambda x: x.get("date") or "", reverse=True):         # newest upload first
        t = _html.unescape((x.get("title") or {}).get("rendered") or "")
        if re.match(r"\s*bajaj[\s_\-]*finserv[\s_\-]*mutual[\s_\-]*fund[\s_\-]*monthly[\s_\-]*portfolio", t, re.I) and \
                month_of(t.replace("_", " ")) == (y, m):
            out.append({"url": x.get("source_url"), "name": t})
    return out[:1]


_360 = None


def one360(y, m):
    """File links sit in the downloads page's Next.js payload (S3, hashed names)."""
    global _360
    if _360 is None:
        t = http_get("https://www.360.one/asset/mutual-funds/downloads/").text.replace("\\/", "/")
        _360 = sorted(set(re.findall(r'https?://[a-zA-Z0-9.\-/]+/IN_MF_MONTHLY_PORTFOLIO_[A-Za-z0-9_\-]+\.xlsx?', t)))
    return [{"url": u, "name": u.rsplit("/", 1)[-1]} for u in _360 if month_of(u.rsplit("/", 1)[-1]) == (y, m)][-1:]


def _browser(name):
    """Lister that needs a real browser (mf_browser.py, Playwright). Imported only when used."""
    def lister(y, m):
        import mf_browser
        return getattr(mf_browser, name)(y, m)
    return lister


SOURCES = {
    "sbi": ("SBI Mutual Fund", sbi),
    "icici": ("ICICI Prudential Mutual Fund", icici),
    "hdfc": ("HDFC Mutual Fund", hdfc),
    "nippon": ("Nippon India Mutual Fund", nippon),
    "kotak": ("Kotak Mahindra Mutual Fund", kotak),
    "axis": ("Axis Mutual Fund", axis),
    "absl": ("Aditya Birla Sun Life Mutual Fund", absl),
    "uti": ("UTI Mutual Fund", uti),
    "mirae": ("Mirae Asset Mutual Fund", mirae),
    "dsp": ("DSP Mutual Fund", dsp),
    "tata": ("Tata Mutual Fund", tata),
    "ppfas": ("PPFAS Mutual Fund", ppfas),
    "motilal": ("Motilal Oswal Mutual Fund", motilal),
    "invesco": ("Invesco Mutual Fund", invesco),
    "canara": ("Canara Robeco Mutual Fund", canara),
    "hsbc": ("HSBC Mutual Fund", hsbc),
    "franklin": ("Franklin Templeton Mutual Fund", franklin),
    "quant": ("Quant Mutual Fund", quant),
    "bandhan": ("Bandhan Mutual Fund", _browser("bandhan")),
    "whiteoak": ("WhiteOak Capital Mutual Fund", whiteoak),
    "sundaram": ("Sundaram Mutual Fund", sundaram),
    "lic": ("LIC Mutual Fund", lic),
    "boi": ("Bank of India Mutual Fund", boi),
    "bajaj": ("Bajaj Finserv Mutual Fund", bajaj),
    "360one": ("360 ONE Mutual Fund", one360),
    "pgim": ("PGIM India Mutual Fund", pgim),
    "baroda": ("Baroda BNP Paribas Mutual Fund",
               baroda),
    "groww": ("Groww Mutual Fund", static_lister("https://www.growwmf.in/statutory-disclosure/portfolio", r"monthly\s*portfolio")),
    "helios": ("Helios Mutual Fund", static_lister("https://www.heliosmf.in/portfolio-disclosure/", r"monthly[\-_\s]*portfolio")),
    "shriram": ("Shriram Mutual Fund",
                static_lister("https://www.shriramamc.in/investor-statutory-disclosures", r"monthly[\-_\s]*portfolio[\-_\s]*shriram", one=True)),
    "nj": ("NJ Mutual Fund", static_lister("https://downloads.njmutualfund.com/njmf_download.php?nme=127", r"monthly[\-_\s]*portfolio")),
    "capitalmind": ("Capitalmind Mutual Fund",
                    static_lister("https://capitalmindmf.com/statutory-disclosures.html", r"_monthly_portfolio_disclosure_")),
    "oldbridge": ("Old Bridge Mutual Fund", static_lister("https://oldbridgemf.com/statutory-disclosures.html", r"_portfolio_|monthly_portfolio",
                                                          exclude=r"fortnight|half[\s\-_]?year|overlap|financial|risk|aaum|dashboard|voting")),
    "angelone": ("Angel One Mutual Fund", static_lister("https://www.angelonemf.com/downloads", r"monthly[\-_\s]*portfolio")),
    "samco": ("Samco Mutual Fund", static_lister("https://www.samcomf.com/StatutoryDisclosure", r"in_mf_monthly_portfolio_",
                                                 prefer=r"samcomf\.com/amc-document-download")),
}
