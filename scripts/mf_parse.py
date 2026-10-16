"""Read any fund house's monthly portfolio spreadsheet into one standard shape.

Every SEBI-format portfolio sheet has a header row with the instrument name, ISIN, quantity and market
value, then sections (equity, debt, derivatives...). This reader finds those header rows itself, so it
works across fund houses without a template per file:

    parse(bytes, filename) -> list of blocks, one per scheme:
        {"scheme": name, "date": "YYYY-MM-DD" or None, "sheet": sheet name,
         "eq":  [(isin, name, qty, value_cr, pct)],         # equity shares (ISIN type 01, incl. partly paid)
         "fut": [(name, qty, value_cr)],                      # stock futures, quantity signed (short < 0)
         "unit": "lakh" | "crore" | "rupee" | "thousand" | "?", "total_cr": grand total if found}

Values are converted to ₹ crore. Quantities stay in shares. Nothing here guesses silently: anything the
reader cannot place is returned as an empty block, and the caller's checks (implied price vs market
price, holdings vs NSE shareholding) decide whether a block is trusted.
"""
import io
import re
import zipfile
import datetime as dt

ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


# ───────────────────────────────────────────── workbook → rows
def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, str):
        v = v.replace("\xa0", " ").strip()
        return v or None
    return v


def _calamine(data):
    """Fast reader for xlsx / xls / xlsb (python-calamine). None if unavailable or the file is not a workbook."""
    try:
        from python_calamine import CalamineWorkbook
    except ImportError:
        return None
    try:
        wb = CalamineWorkbook.from_filelike(io.BytesIO(data))
    except Exception:
        return None
    out = []
    for sn in wb.sheet_names:
        try:
            rows = wb.get_sheet_by_name(sn).to_python(skip_empty_area=False)
        except Exception:
            continue
        out.append((sn, [tuple(_clean(c) for c in r) for r in rows]))
    return out


def read_sheets(data, filename=""):
    """[(sheet_name, [row tuples])] for xlsx / xls / xlsb / html-disguised-as-xls / csv."""
    head = data[:8]
    out = []
    if head[:2] == b"PK" or head[:4] == b"\xd0\xcf\x11\xe0":
        is_zip_of_books = False
        if head[:2] == b"PK":
            try:
                is_zip_of_books = not any(n.startswith("xl/") for n in zipfile.ZipFile(io.BytesIO(data)).namelist())
            except zipfile.BadZipFile:
                pass
        if not is_zip_of_books:
            got = _calamine(data)
            if got is not None:
                return got
    if head[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            names = zf.namelist()
        except zipfile.BadZipFile:
            names = []
        if any(n.startswith("xl/") for n in names):
            if any(n.endswith(".bin") and "worksheets" in n for n in names):
                return _read_xlsb(data)
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            for ws in wb.worksheets:
                try:
                    ws.reset_dimensions()
                except Exception:
                    pass
                rows = [tuple(_clean(c) for c in r) for r in ws.iter_rows(values_only=True)]
                out.append((ws.title, rows))
            wb.close()
            return out
        # a zip of several spreadsheets
        for n in names:
            if re.search(r"\.(xlsx?|xlsb|xlsm)$", n, re.I) and not n.startswith("__MACOSX"):
                for sn, rows in read_sheets(zf.read(n), n):
                    out.append((f"{n}::{sn}", rows))
        return out
    if head[:4] == b"\xd0\xcf\x11\xe0":
        import xlrd
        b = xlrd.open_workbook(file_contents=data, formatting_info=False, on_demand=True)
        for i in range(b.nsheets):
            sh = b.sheet_by_index(i)
            rows = []
            for r in range(sh.nrows):
                vals = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    v = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            v = xlrd.xldate.xldate_as_datetime(v, b.datemode)
                        except Exception:
                            pass
                    elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        v = None
                    vals.append(_clean(v))
                rows.append(tuple(vals))
            out.append((sh.name, rows))
        return out
    txt = data[:2000].lower()
    if b"<table" in data[:200000].lower() or b"<html" in txt:
        import pandas as pd
        for i, df in enumerate(pd.read_html(io.BytesIO(data), header=None)):
            out.append((f"table{i}", [tuple(_clean(v) for v in r) for r in df.itertuples(index=False)]))
        return out
    if filename.lower().endswith(".csv"):
        import csv
        rows = list(csv.reader(io.StringIO(data.decode("utf-8", "ignore"))))
        return [("csv", [tuple(_clean(v) for v in r) for r in rows])]
    raise ValueError(f"unknown file type: {filename} {head!r}")


def _read_xlsb(data):
    from pyxlsb import open_workbook
    out = []
    with open_workbook(io.BytesIO(data)) as wb:
        for sn in wb.sheets:
            with wb.get_sheet(sn) as sh:
                out.append((sn, [tuple(_clean(c.v) for c in r) for r in sh.rows()]))
    return out


# ───────────────────────────────────────────── helpers
def num(v):
    """Number from a cell: handles '1,23,456.7', '(123)', '-', '3.5%', 'Nil'."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return None
    s = str(v).strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("%", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    if s in ("", "-", "--", "nil", "Nil", "NIL", "NA", "N.A.", "N/A", "$", "#", "^", "*"):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def is_isin(v):
    return isinstance(v, str) and bool(ISIN_RE.match(v.strip().upper()))


def is_equity_isin(isin):
    """Ordinary or partly-paid equity shares of an Indian company: security type 01 (positions 8-9)."""
    return isin[:3] in ("INE", "IN9") and isin[7:9] == "01"


AS_ON = re.compile(r"as on|as at|as of|portfolio (statement )?(for|as)|month ended|ending on|statement as", re.I)


def find_date(texts):
    """Portfolio date from the rows above a header. Dates written next to 'as on' / 'portfolio as at' win; any
    other date (a merger notice, an SEBI approval) is used only when no such phrase exists.
    Returns (date or None, strong) where strong means it came from an 'as on' phrase or a date cell."""
    strong = [t for t in texts if isinstance(t, (dt.datetime, dt.date))] + \
             [t for t in texts if isinstance(t, str) and AS_ON.search(t) and len(t) < 160]
    d = _find_date(strong)
    if d:
        return d, True
    return _find_date([t for t in texts if isinstance(t, str) and len(t) < 160]), False


def _find_date(texts):
    for t in texts:
        if isinstance(t, (dt.datetime, dt.date)):
            d = t if isinstance(t, dt.date) else t.date()
            if 2000 < d.year < 2100:
                return d.isoformat()[:10]
    for t in texts:
        if not isinstance(t, str):
            continue
        s = t.lower()
        m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?[\s\-./,]+([a-z]{3,9})[\s\-./,']+(\d{2,4})", s)
        if m and m.group(2)[:3] in MONTHS:
            y = int(m.group(3)); y = y + 2000 if y < 100 else y
            try:
                return dt.date(y, MONTHS[m.group(2)[:3]], int(m.group(1))).isoformat()
            except ValueError:
                pass
        m = re.search(r"([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})", s)
        if m and m.group(1)[:3] in MONTHS:
            try:
                return dt.date(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2))).isoformat()
            except ValueError:
                pass
        m = re.search(r"(\d{1,2})[\-./](\d{1,2})[\-./](\d{4}|\d{2})\b", s)
        if m:
            y = int(m.group(3)); y = y + 2000 if y < 100 else y
            try:
                return dt.date(y, int(m.group(2)), int(m.group(1))).isoformat()
            except ValueError:
                pass
    return None


HDR_NAME = re.compile(r"name of (the )?(instrument|security|issuer)|instrument|security name|name of the (scrip|company)|issuer|company name|^name$|particulars|scrip", re.I)
HDR_QTY = re.compile(r"quantity|^qty|no\.? ?of (shares|units|securities)|holdings? \(?no|number of (shares|units)|units?$", re.I)
HDR_VAL = re.compile(r"market.*value|fair value|value.*(lakh|lac|crore|cr\b|rs|₹|inr)|^market value|^value|amount|mkt\.? ?val|market ?val", re.I)
HDR_PCT = re.compile(r"%|percent|to net assets|to nav|to aum|% of", re.I)


def unit_of(text):
    t = (text or "").lower().replace(" ", "")
    if "lakh" in t or "lac" in t:
        return "lakh"
    if "crore" in t or "(cr" in t or "rs.cr" in t or "₹cr" in t or "incr" in t or "inrcr" in t:
        return "crore"
    if "'000" in t or "000s" in t or "thousand" in t or "('000)" in t:
        return "thousand"
    if "inrs" in t or "(rs" in t or "rupee" in t or "(₹)" in t or "inr)" in t:
        return "rupee"
    return "?"


TO_CR = {"lakh": 0.01, "crore": 1.0, "rupee": 1e-7, "thousand": 1e-4}


def find_header(rows, start=0):
    """Index and column map of the next header row at/after start, or None."""
    for i in range(start, len(rows)):
        r = rows[i]
        cells = [(j, str(c)) for j, c in enumerate(r) if isinstance(c, str)]
        if len(cells) < 3:
            continue
        isin = [j for j, c in cells if re.search(r"\bisin\b", c, re.I)]
        qty = [j for j, c in cells if HDR_QTY.search(c) and not re.search(r"value|%", c, re.I)]
        val = [j for j, c in cells if HDR_VAL.search(c) and not re.search(r"%|percent|ytm|yield|ytc", c, re.I)]
        if not (isin and qty and val):
            continue
        pct = [j for j, c in cells if HDR_PCT.search(c) and re.search(r"net asset|nav|aum|%", c, re.I) and j not in val and not re.search(r"ytm|yield|ytc|coupon", c, re.I)]
        name = [j for j, c in cells if HDR_NAME.search(c) and j not in isin + qty + val]
        hdr_text = " ".join(c for _, c in cells)
        # look one row below for a units line ("(Rs. in Lakhs)") split from the header
        if i + 1 < len(rows):
            hdr_text += " " + " ".join(str(c) for c in rows[i + 1] if isinstance(c, str) and len(str(c)) < 40)
        return i, {"isin": isin[0], "qty": qty[0], "val": val[0], "pct": pct[0] if pct else None,
                   "name": name[0] if name else None,
                   "unit": unit_of(next((c for j, c in cells if j == val[0]), "")) if unit_of(next((c for j, c in cells if j == val[0]), "")) != "?" else unit_of(hdr_text)}
    return None


FUT_NAME = re.compile(r"[\-\s](\d{1,2}[\-\s/]?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\-\s/]?\d{2,4})\s*$|\bfut(ures?)?\b|\bfutidx|\bfutstk", re.I)
SUBTABLE = re.compile(r"details of|stock future|index future|derivative|hedg|option|swap|futures? position", re.I)
DERIV_SEC = re.compile(r"derivative|futures?\b|stock future|index future|hedg", re.I)
STOP_SEC = re.compile(r"^(grand total|total net assets|net assets)", re.I)
SCHEME_HINT = re.compile(r"\b(fund|scheme|etf|plan|portfolio of|portfolio statement of|index|fof|savings|hybrid|opportunit|bluechip|cap\b|bees|yoj(a)?na)", re.I)
JUNK_HINT = re.compile(r"mutual fund\.?$|asset management|investment manager|amc ltd|trustee|registered office|\bcin\b|e-?mail|website|"
                       r"back to index|^index$|^sr\.? ?no|^name of|portfolio statement as on|monthly portfolio statement|open[\s\-]?ended|"
                       r"suitable for|investors (should|understand)|risk[\s\-]?o[\s\-]?meter|^this product|^\W|seeking|consult their|"
                       r"half[\s\-]?yearly|fortnightly|^portfolio as on|^as on|^as at|^date|^notes?\b|^total|w\.e\.f|pursuant|"
                       r"risk of the|riskometer|\brisk\b.*\b(high|low|moderate)\b|benchmark|nav per unit|^plan\b|^option", re.I)
DESC_TAIL = re.compile(r"\s*[\(\[]\s*(an?|the)?\s*(open|close|interval)[\s\-]?ended.*$|\s*[-–:]\s*(an?\s+)?(open|close)[\s\-]?ended.*$", re.I)


def _short_name(t):
    t = re.sub(r"\s+", " ", t).strip()
    t = DESC_TAIL.sub("", t).strip(" -–:,")
    t = re.sub(r"\s*\((formerly|erstwhile|earlier|previously|\*?earlier)[^)]*\)?", "", t, flags=re.I).strip()
    return t


def _scheme_name(rows, upto, sheet, index_names=None):
    """Best scheme name for the block whose header is at row `upto`.

    Order: an explicit 'Scheme name:' label; the workbook's index sheet (sheet code -> scheme); the short line
    above the header that reads like a scheme name (AMC brand + Fund/ETF/...), skipping addresses, descriptions
    in brackets, suitability text and notices. Falls back to the sheet name."""
    cands = []
    for r in rows[max(0, upto - 15):upto]:
        strs = [c for c in r if isinstance(c, str)]
        for k, c in enumerate(strs):
            if re.fullmatch(r"\s*(scheme name|name of (the )?scheme|scheme)\s*[:\-]?\s*", c, re.I) and k + 1 < len(strs):
                return _short_name(strs[k + 1])
        for c in strs:
            if not 6 <= len(c) <= 250:
                continue
            t = re.sub(r"\s+", " ", c).strip()
            m = re.search(r"(?:scheme name|name of (?:the )?scheme|^scheme)\s*[:\-]\s*(.+)", t, re.I)
            if m and len(m.group(1)) > 4:
                return _short_name(m.group(1))
            m = re.search(r"portfolio (?:statement )?of (.+?)(?: as on| as at| for the| \(|$)", t, re.I)
            if m and len(m.group(1)) > 4 and SCHEME_HINT.search(m.group(1)):
                cands.append((3, _short_name(m.group(1))))
                continue
            s = _short_name(t)
            if not s or len(s) > 110 or JUNK_HINT.search(s) or not SCHEME_HINT.search(s):
                continue
            words = len(re.findall(r"[A-Za-z0-9&]+", s))
            pr = 2 if words >= 2 and re.search(r"\b(fund|etf|fof|bees|plan|scheme|portfolio)\b|index fund", s, re.I) else 1
            if not any(c == s for _, c in cands[-8:]):
                cands.append((pr, s))
    if index_names and sheet in index_names:
        return index_names[sheet]
    if cands:
        best = max(cands, key=lambda x: x[0])[0]
        top = [c for p, c in cands if p == best]
        return top[-1]                                         # the closest such line above the header
    return sheet


def index_map(sheets):
    """{sheet name: scheme name} from a workbook's index / contents sheet, when it has one."""
    names = {}
    for sn, _ in sheets:                       # a workbook inside a zip has sheets named "<file>::<sheet>"
        names[sn.strip().lower()] = sn
        names.setdefault(sn.split("::")[-1].strip().lower(), sn)
    out = {}
    for sn, rows in sheets:
        if not re.search(r"index|content|summary|scheme list|^sheet1$", sn.split("::")[-1], re.I):
            continue
        own = {sn.strip().lower(), sn.split("::")[-1].strip().lower()}
        for r in rows[:400]:
            strs = [str(c).strip() for c in r if isinstance(c, str) and str(c).strip()]
            code = next((names[s.lower()] for s in strs if s.lower() in names and s.lower() not in own), None)
            if not code:
                continue
            nm = max((s for s in strs if s.lower() not in names and SCHEME_HINT.search(s)), key=len, default=None)
            if nm and len(nm) > 6:
                out.setdefault(code, _short_name(nm))
    return out


def parse_rows(rows, sheet="", index_names=None):
    """All scheme blocks found in one sheet's rows."""
    blocks = []
    i = 0
    while True:
        h = find_header(rows, i)
        if not h:
            break
        hi, cols = h
        nxt = find_header(rows, hi + 1)
        end = nxt[0] if nxt else len(rows)
        # a second header for the same scheme (e.g. a derivatives table) shares the scheme name
        if cols["unit"] == "?":                      # "(Market value in Lacs)" written in a title line above the header
            above = " ".join(str(c) for r in rows[max(0, hi - 15):hi] for c in r if isinstance(c, str) and len(str(c)) < 200)
            cols["unit"] = unit_of(above)
        name = _scheme_name(rows, hi, sheet, index_names)
        texts = [c for r in rows[max(0, hi - 15):hi + 1] for c in r if c is not None]
        date, strong = find_date(texts)
        eq, fut, deriv, total, nameless = [], [], False, None, 0
        for r in rows[hi + 1:end]:
            cells = [c for c in r if c is not None]
            if not cells:
                continue
            row_text = " ".join(str(c) for c in cells if isinstance(c, str))
            lead = next((str(c) for c in cells if isinstance(c, str)), "")
            if STOP_SEC.search(lead.strip()) and total is None:
                v = num(r[cols["val"]]) if cols["val"] < len(r) else None
                total = v
            isin = None
            for j in ([cols["isin"]] + list(range(len(r)))):
                if j < len(r) and is_isin(r[j]):
                    isin = str(r[j]).strip().upper(); break
            if isin is None and num(r[cols["qty"]] if cols["qty"] < len(r) else None) is None:
                # a heading row: derivatives start, or a fresh equity / debt section begins
                if DERIV_SEC.search(row_text):
                    deriv = True
                elif re.search(r"listed|equity|shares|debt|money market|treps|reverse repo|bonds?\b|debentures|government", row_text, re.I) \
                        and not re.search(r"total|hedg", row_text, re.I):
                    deriv = False
                continue
            qty = num(r[cols["qty"]]) if cols["qty"] < len(r) else None
            val = num(r[cols["val"]]) if cols["val"] < len(r) else None
            pct = num(r[cols["pct"]]) if cols["pct"] is not None and cols["pct"] < len(r) else None
            nm = None
            if cols["name"] is not None and cols["name"] < len(r) and isinstance(r[cols["name"]], str):
                nm = r[cols["name"]]
            if not nm:
                strs = [c for c in r if isinstance(c, str) and not is_isin(c) and len(c) > 2]
                nm = max(strs, key=len) if strs else None
            # a futures / options line: in a derivatives section, named like "HDFC BANK LTD.-27-Oct-2026" / "... FUT",
            # or a negative quantity (a short). These never count as shares held.
            fut_row = deriv or bool(FUT_NAME.search(nm or "")) or (qty is not None and qty < 0)
            if isin and not fut_row:
                if is_equity_isin(isin) and qty is not None and val is not None:
                    eq.append((isin, nm, qty, val, pct))
            elif isin and not is_equity_isin(isin):
                continue                                         # debt / money market line that happens to end in a date
            elif fut_row and qty is not None and val is not None and qty != 0 and (nm or isin):
                if re.search(r"\boption|\bcall\b|\bput\b|\bce\b|\bpe\b", row_text, re.I):
                    continue                                     # options: not a position in shares
                sgn = -1 if (qty < 0 or val < 0 or re.search(r"\bshort\b|\bsell\b", row_text, re.I)) else 1
                fut.append((isin if isin and is_equity_isin(isin) else "", nm, sgn * abs(qty), sgn * abs(val)))
            elif qty is not None and val is not None and nm and re.search(r"futures?|\bfut\b", nm, re.I):
                sgn = -1 if (qty < 0 or val < 0 or re.search(r"\bshort\b", row_text, re.I)) else 1
                fut.append(("", nm, sgn * abs(qty), sgn * abs(val)))
        blocks.append({"scheme": name, "date": date, "date_strong": strong, "sheet": sheet, "unit": cols["unit"], "eq": eq,
                       "fut": fut, "total": total, "pct_scale": None})
        i = end
    # merge consecutive blocks of the same scheme (a derivatives table with its own header)
    merged = []
    for b in blocks:
        same_sheet = merged and b["sheet"] == merged[-1]["sheet"]
        sub_table = SUBTABLE.search(b["scheme"] or "") or (not b["eq"] and b["fut"])
        if same_sheet and (b["scheme"] == merged[-1]["scheme"] or sub_table):
            m = merged[-1]
            m["eq"] += b["eq"]; m["fut"] += b["fut"]
            m["total"] = m["total"] if m["total"] is not None else b["total"]
            if not m.get("date_strong") and b.get("date_strong"):
                m["date"], m["date_strong"] = b["date"], True
            m["date"] = m["date"] or b["date"]
        else:
            merged.append(b)
    return merged


def price_unit(eq, px):
    """Unit of the value column decided by market prices: the unit under which value / quantity matches the
    NSE close for most holdings. Returns (unit, share of holdings within 10%) or (None, 0) if no prices."""
    best = (None, 0.0, 9.9)
    rows = [(v, q, px[i[:9]]) for i, _, q, v, _ in eq if q and v and i[:9] in px and px[i[:9]] > 0]
    if len(rows) < 3:
        return None, 0.0
    import math
    for u, f in TO_CR.items():
        rs = sorted(v * f * 1e7 / (q * c) for v, q, c in rows)
        med = rs[len(rs) // 2]
        if med <= 0:
            continue
        near = sum(1 for r in rs if 0.9 <= r <= 1.1) / len(rs)
        if abs(math.log(med)) < best[2]:
            best = (u, near, abs(math.log(med)))
    return (best[0], best[1]) if best[2] < math.log(1.25) else (None, 0.0)


def parse(data, filename="", default_unit=None, px=None):
    """Parse a whole file. Values are converted to ₹ crore.

    The unit comes from the header text ("Rs. in Lakhs"), and is checked against market prices when `px`
    ({isin[:9]: close on the portfolio date}) is given: if value / quantity only matches the close under a
    different unit, the price-backed unit wins and the block is flagged (b["unit_note"])."""
    out = []
    sheets = read_sheets(data, filename)
    idx = index_map(sheets)
    for sheet, rows in sheets:
        for b in parse_rows(rows, sheet, idx):
            unit = b["unit"] if b["unit"] != "?" else (default_unit or "?")
            b["unit_note"] = ""
            if px and b["eq"]:
                pu, near = price_unit(b["eq"], px)
                if pu and pu != unit:
                    b["unit_note"] = f"header unit {unit} disagrees with prices; using {pu} ({near:.0%} of holdings within 10%)"
                    unit = pu
                b["price_match"] = near
            f = TO_CR.get(unit)
            b["unit"] = unit
            if f is None:
                b["eq_raw"] = b["eq"]
                b["eq"] = []
            else:
                b["eq"] = [(i, n, q, v * f, p) for i, n, q, v, p in b["eq"]]
                b["fut"] = [(i, n, q, v * f) for i, n, q, v in b["fut"]]
                if b["total"] is not None:
                    b["total"] *= f
            ps = [p for *_, p in b["eq"] if p is not None]
            if ps and max(abs(p) for p in ps) <= 1.0 and sum(ps) <= 1.5:
                b["pct_scale"] = 100.0
                b["eq"] = [(i, n, q, v, p * 100 if p is not None else None) for i, n, q, v, p in b["eq"]]
            out.append(b)
    return out


# ───────────────────────────────────────────── futures → underlying ISIN
_STOP = {"ltd", "limited", "the", "co", "company", "corporation", "corp", "of", "india", "and", "inc", "plc", "pvt",
         "futures", "future", "fut", "stock", "stk", "equity", "short", "long", "sell", "buy", "&", "industries", "ind"}
_MON = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "january", "february",
        "march", "april", "june", "july", "august", "september", "october", "november", "december"}


def name_key(s):
    s = (s or "").lower()
    s = re.sub(r"\d{1,2}[\-./ ]\d{1,2}[\-./ ]\d{2,4}", " ", s)
    s = re.sub(r"\d{1,2}[\-./ ]?[a-z]{3,9}[\-./ ]?\d{2,4}", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in _STOP and t not in _MON and not t.isdigit()]
    return " ".join(toks)


def match_futures(eq, fut, name_map=None):
    """{isin: signed futures qty} by matching futures names to the scheme's own equity names first,
    then to a wider name→ISIN map. Index futures and unmatched rows are returned separately."""
    own = {}
    for isin, nm, *_ in eq:
        k = name_key(nm)
        if k:
            own.setdefault(k, isin)
    got, miss = {}, []
    for isin0, nm, q, v in fut:
        if isin0:
            got[isin0] = got.get(isin0, 0) + q
            continue
        k = name_key(nm)
        if re.search(r"\bnifty\b|\bsensex\b|\bbank ?nifty\b|\bfinnifty\b|\bindex\b", (nm or "").lower()):
            continue
        isin = own.get(k) or (name_map or {}).get(k)
        if not isin and k:
            # prefix match: "hdfc bank" vs "hdfc bank ltd" already handled; try containment both ways
            for kk, ii in own.items():
                if kk and (kk.startswith(k) or k.startswith(kk)) and min(len(kk), len(k)) >= 4:
                    isin = ii; break
        if isin:
            got[isin] = got.get(isin, 0) + q
        else:
            miss.append((nm, q, v))
    return got, miss
