"""Chart patterns for the Patterns tab: strict, rule-based detectors, run every evening on the liquid universe.

What it finds (in the order the site lists them - by how each did on NSE 2005-26, config/pattern_evidence.json):
  vcp     VCP (Minervini): Stage 2 stock, base of 6+ weeks starting at a peak, 2-6 pullbacks each shallower than the
          last and a week or longer, higher lows, last pullback under 10%, volume drying up; breakout = close above the
          last pullback's high
  scallop inverted descending scallop  ihs  inverse head and shoulders   bigw  Big W     tb  triple bottom
  rectb   rectangle bottom             chs  complex H&S bottom           3rv   three rising valleys
  rectt   rectangle top                rb   rounding bottom              barr  bump-and-run reversal bottom
  ee      Eve & Eve double bottom      cwh  cup with handle              (too few cases on NSE to judge)
  hst     head-and-shoulders top: a sell warning (close below the neckline)

Each detector is the exact code used in the 2005-26 study (Bulkowski's identification guidelines, Minervini for VCP,
O'Neil for cup with handle), on daily bars, using only data up to the breakout day: earlier swing points come from a
fractal zig-zag and must be confirmed before the breakout; the last swing point is taken in real time. Checked by
cutting each stock's history at the signal day and re-running (identical signals).

Two lists:
  broke out  the first close through the pattern's confirmation level in the last WINDOW sessions
  forming    the pattern is complete except for that close, and the close it needs is at most NEAR above today's.
             Found by adding one hypothetical session (today's close moved up, or down for the H&S top) and asking
             the same detectors whether that close would confirm a pattern that passes every rule; the lowest such
             close is the trigger shown on the site.

Input: PFULL (symbol, date, open, high, low, close, volume; about 6 years), the liquid universe, RS ratings for the last
sessions. Output: docs/data/patterns.json and docs/data/pat/<n>.json (candles for each listed stock's chart).
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

LN = np.log
SCALES = (4, 6, 9, 13)
WINDOW = 10            # "broke out" = in the last 10 sessions
NEAR = 0.05            # "forming" = needs a close at most 5% away
HIST = 900             # daily bars used per stock (patterns span at most ~330 sessions plus the 252-day averages)
MARGIN = 60            # extra sessions evaluated before the window so spacing rules (one signal per 10 days) match a full run


# ═════════════════════════════════ shared helpers ═════════════════════════════════
def zigzag(lo, hi, k):
    """fractal swing points at scale k (k bars each side; the last k bars use what exists), alternating low/high."""
    n = len(lo)
    s = pd.Series(lo); h = pd.Series(hi)
    mn = s.rolling(2 * k + 1, center=True, min_periods=k + 1).min().to_numpy()
    mx = h.rolling(2 * k + 1, center=True, min_periods=k + 1).max().to_numpy()
    piv = []
    for i in range(k, n):
        isl, ish = lo[i] <= mn[i], hi[i] >= mx[i]
        if isl and ish:
            continue
        if isl:
            piv.append((i, -1, lo[i]))
        elif ish:
            piv.append((i, 1, hi[i]))
    out = []
    for p in piv:                                   # alternate, keeping the more extreme of same-type neighbours
        if out and out[-1][1] == p[1]:
            if (p[1] == -1 and p[2] < out[-1][2]) or (p[1] == 1 and p[2] > out[-1][2]):
                out[-1] = p
        else:
            out.append(p)
    return out


def template_fit(C, iL, iR, PB, top):
    """Best fit of closes iL..iR to an ideal U: y = |(x - xb)/side|^k, bottom xb in [0.25, 0.75], k in [1, 4].
    Returns (rmse, k, xb). y = 0 at the low PB, 1 at the rim level `top`; x = 0 at iL, 1 at iR."""
    c = C[iL:iR + 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        y = np.clip((c - PB) / (top - PB), -0.2, 1.3)
    x = np.linspace(0, 1, len(c))
    best = (9, None, None)
    for xb in np.linspace(0.25, 0.75, 21):
        side = np.where(x < xb, xb, 1 - xb)
        u = np.abs((x - xb) / side)
        for k in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0):
            r = np.sqrt(np.mean((y - u ** k) ** 2))
            if r < best[0]:
                best = (r, k, xb)
    return best


def lip_support(H, iL, PL, lo=10, hi=3, lvl=0.97):
    return int((H[max(0, iL - lo):iL + hi + 1] >= lvl * PL).sum())


class Bars:
    def __init__(self, d):
        self.H, self.L, self.C, self.O = (d[c].to_numpy(float) for c in ("high", "low", "close", "open"))
        self.V = d["volume"].to_numpy(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            self.hi, self.lo, self.cl = LN(self.H), LN(self.L), LN(self.C)
        self.n = len(self.C)
        r = np.abs(np.diff(self.cl))
        self.big = np.r_[0, (r > LN(1.35)).astype(int)].cumsum()          # one-day moves over 35%: data error / corporate action
        self.zz = {k: zigzag(self.lo, self.hi, k) for k in SCALES}
        self.v50 = pd.Series(self.V).rolling(50, min_periods=30).mean().shift(1).to_numpy()

    def clean(self, a, b):
        return bool(self.big[b] - self.big[max(0, a - 1)] == 0)

    def width(self, i, Hgt, side=10, frac=0.2, low=True):
        """bars within `side` sessions of a swing whose low (high) is within frac*Hgt of it - Eve (wide) vs Adam (spike)."""
        a, b = max(0, i - side), min(self.n, i + side + 1)
        if low:
            return int((self.lo[a:b] <= self.lo[i] + frac * Hgt).sum())
        return int((self.hi[a:b] >= self.hi[i] - frac * Hgt).sum())

    def prior_high(self, i, w=63):
        a = max(0, i - w)
        return self.hi[a:i + 1].max() if i - a >= 20 else np.nan

    def prior_low(self, i, w=63):
        a = max(0, i - w)
        return self.lo[a:i + 1].min() if i - a >= 20 else np.nan


def dedupe(found, recs, key="t", win=5, better=lambda a, b: a["Hgt"] > b["Hgt"]):
    """keep one pattern per breakout window."""
    for r in recs:
        near = [x for x in found if abs(x[key] - r[key]) <= win]
        if not near:
            found.append(r)
        elif all(better(r, x) for x in near):
            for x in near:
                found.remove(x)
            found.append(r)
    return found


# ═════════════════════════════════ detectors (2005-26 study code) ═════════════════════════════════
# t_from: only patterns whose breakout can fall on or after t_from - MARGIN are worked out (a speed-up for the daily run;
# the caller keeps t >= t_from). Upper bounds on the breakout day are exact, so nothing near the window is skipped.
def double_bottoms(B, t_from=0):
    lo, hi, cl = B.lo, B.hi, B.cl
    out = []
    for k in SCALES:
        for (b1, typ, b1l) in B.zz[k]:
            if typ != -1 or b1 + 130 < t_from - MARGIN:
                continue
            start = b1 + k + 1
            P, Ph = None, -np.inf
            res = None
            for i in range(b1 + 1, min(B.n, b1 + 131)):
                if lo[i] < b1l - LN(1.06):
                    break
                if P is not None and i >= start and i - P >= 2:
                    if cl[i] > Ph:
                        b2 = P + 1 + int(np.argmin(lo[P + 1:i]))
                        res = (i, P, b2)
                        break
                elif P is not None and cl[i] > Ph:
                    break                                   # rallied straight through: no second bottom
                if hi[i] > Ph:
                    P, Ph = i, hi[i]
            if res is None:
                continue
            i, P, b2 = res
            b2l = lo[b2]
            low = min(b1l, b2l)
            Hgt = Ph - low
            rec = dict(t=i, B1=b1, P=P, B2=b2, k=k, Hgt=Hgt, level=Ph, RSl=low,
                       diff=abs(b1l - b2l), gap=b2 - b1, rise=Ph - b1l, wait=i - b2,
                       prior=(B.prior_high(b1) - Ph) / Hgt if Hgt > 0 else np.nan,
                       prior30=(hi[max(0, b1 - 30):b1 + 1].max() - Ph) / Hgt if Hgt > 0 else np.nan,
                       w1=B.width(b1, Hgt), w2=B.width(b2, Hgt), clean=B.clean(b1, i),
                       pts=[(b1, b1l, "B1"), (P, Ph, ""), (b2, b2l, "B2")], lines=[((P, Ph), (i, Ph))])
            a = max(0, b1 - 126)                            # Big W: tall, straight left side
            A = a + int(np.argmax(hi[a:b1 + 1]))
            rec["A"] = A; rec["left"] = (hi[A] - b1l) / (Ph - b1l) if Ph > b1l else np.nan
            if b1 - A >= 10:
                x = np.arange(A, b1 + 1); y = cl[A:b1 + 1]
                rec["straight"] = float(np.corrcoef(x, y)[0, 1] ** 2)
            else:
                rec["straight"] = np.nan
            rec["left_len"] = b1 - A
            rec["b1_lowest"] = bool(lo[A:b1 + 1].min() >= b1l - 1e-12)
            out.append(rec)
    return dedupe([], out, better=lambda a, b: a["k"] > b["k"])


def three_valleys(B, t_from=0):
    lo, hi, cl = B.lo, B.hi, B.cl
    out = []
    for k in SCALES:
        z = B.zz[k]
        for j in range(len(z) - 2):
            (v1, t1, v1l), (p1, t2, p1h), (v2, t3, v2l) = z[j], z[j + 1], z[j + 2]
            if not (t1 == -1 and t2 == 1 and t3 == -1) or v2 + 130 < t_from - MARGIN:
                continue
            start = v2 + k + 1
            P2, P2h = None, -np.inf
            res = None
            floor = min(v1l, v2l) - LN(1.06)
            for i in range(v2 + 1, min(B.n, v2 + 131)):
                if lo[i] < floor:
                    break
                top = max(p1h, P2h)
                if P2 is not None and i >= start and i - P2 >= 2 and cl[i] > top:
                    v3 = P2 + 1 + int(np.argmin(lo[P2 + 1:i]))
                    res = (i, P2, v3)
                    break
                if cl[i] > p1h and (P2 is None or i - P2 < 2):
                    break
                if hi[i] > P2h:
                    P2, P2h = i, hi[i]
            if res is None:
                continue
            i, P2, v3 = res
            v3l = lo[v3]
            top = max(p1h, P2h)
            vals = np.array([v1l, v2l, v3l])
            Hgt = top - vals.min()
            rec = dict(t=i, V1=v1, P1=p1, V2=v2, P2=P2, V3=v3, k=k, Hgt=Hgt, level=top, RSl=vals.min(),
                       spread=vals.max() - vals.min(), d12=v2 - v1, d23=v3 - v2, wait=i - v3,
                       r1=(p1h - max(v1l, v2l)) / Hgt, r2=(P2h - max(v2l, v3l)) / Hgt,
                       up12=v2l - v1l, up23=v3l - v2l,
                       prior=(B.prior_high(v1) - top) / Hgt if Hgt > 0 else np.nan,
                       w1=B.width(v1, Hgt), w2=B.width(v2, Hgt), w3=B.width(v3, Hgt), clean=B.clean(v1, i),
                       pts=[(v1, v1l, "V1"), (p1, p1h, ""), (v2, v2l, "V2"), (P2, P2h, ""), (v3, v3l, "V3")],
                       lines=[((p1 if p1h >= P2h else P2, top), (i, top))])
            out.append(rec)
    return dedupe([], out, better=lambda a, b: a["k"] > b["k"])


def complex_hs(B, t_from=0):
    lo, hi, cl = B.lo, B.hi, B.cl
    out = []
    for k in SCALES:
        z = B.zz[k]
        for m in (3, 4):                                  # confirmed valleys; one more valley is taken in real time
            for j in range(len(z) - 2 * (m - 1)):
                seq = z[j:j + 2 * (m - 1) + 1]
                if [x[1] for x in seq] != [-1, 1] * (m - 1) + [-1]:
                    continue
                vals = [x for x in seq if x[1] == -1]; pks = [x for x in seq if x[1] == 1]
                lastv = vals[-1][0]; start = lastv + k + 1
                if lastv + 130 < t_from - MARGIN:
                    continue
                floor = min(v[2] for v in vals)
                Pn, Pnh = None, -np.inf
                res = None
                for i in range(lastv + 1, min(B.n, lastv + 131)):
                    if lo[i] < floor:
                        break
                    if Pn is not None and i >= start and i - Pn >= 2:
                        vr = Pn + 1 + int(np.argmin(lo[Pn + 1:i]))
                        V = vals + [(vr, -1, lo[vr])]; PK = pks + [(Pn, 1, Pnh)]
                        mn = min(v[2] for v in V); top = max(p[2] for p in PK)
                        hb = [x for x, v in enumerate(V) if v[2] <= mn + 0.12 * (top - mn)]
                        ok = hb[0] > 0 and hb[-1] < len(V) - 1 and hb == list(range(hb[0], hb[-1] + 1)) and len(hb) <= 2
                        if ok:
                            L_arm = max(PK[:hb[0]], key=lambda p: p[2]); R_arm = max(PK[hb[-1]:], key=lambda p: p[2])
                            s_ = (R_arm[2] - L_arm[2]) / (R_arm[0] - L_arm[0])
                            lvl = (L_arm[2] + s_ * (i - L_arm[0])) if s_ <= 0 else R_arm[2]
                            if cl[i] > lvl:
                                res = (i, V, PK, hb, L_arm, R_arm, s_, lvl)
                                break
                        elif cl[i] > top:
                            break
                    elif Pn is not None and cl[i] > max(p[2] for p in pks + [(Pn, 1, Pnh)]):
                        break
                    if hi[i] > Pnh:
                        Pn, Pnh = i, hi[i]
                if res is None:
                    continue
                i, V, PK, hb, L_arm, R_arm, s_, lvl = res
                neck = lambda x: L_arm[2] + s_ * (x - L_arm[0])
                headlow = min(V[x][2] for x in hb); hc = float(np.mean([V[x][0] for x in hb]))
                Hgt = neck(hc) - headlow
                if Hgt <= 0:
                    continue
                sh = [x for x in range(len(V)) if x not in hb]
                nleft, nright = hb[0], len(V) - 1 - hb[-1]
                sds = [(neck(V[x][0]) - V[x][2]) / Hgt for x in sh]
                prom = (min(V[x][2] for x in sh) - headlow) / Hgt
                tl = hc - V[0][0]; trr = V[-1][0] - hc
                prev = np.arange(R_arm[0] + 1, i)
                first = not (len(prev) and (cl[R_arm[0] + 1:i] > (neck(prev) if s_ <= 0 else R_arm[2])).any())
                mid_ok = True
                if len(hb) == 2:                          # two heads: the peak between them is a real rally, below the neckline
                    pm = PK[hb[0]]
                    mid_ok = (pm[2] - headlow) >= 0.25 * Hgt and pm[2] <= neck(pm[0])
                out.append(dict(t=i, k=k, m=len(V), nheads=len(hb), nleft=nleft, nright=nright,
                                complex=(len(hb) >= 2) or (nleft + nright >= 3), Hgt=Hgt, level=lvl, RSl=headlow,
                                sd_min=min(sds), sd_max=max(sds), head=prom, osym=abs(V[0][2] - V[-1][2]) / Hgt,
                                tratio=trr / tl if tl > 0 else np.nan, W=V[-1][0] - V[0][0], first=first, mid_ok=mid_ok,
                                wait=i - V[-1][0], prior=(B.prior_high(V[0][0]) - neck(V[0][0])) / Hgt,
                                slope=(R_arm[2] - L_arm[2]) / Hgt, clean=B.clean(V[0][0], i),
                                pts=[(v[0], v[2], "H" if x in hb else "S") for x, v in enumerate(V)] + [(p[0], p[2], "") for p in PK],
                                lines=[((L_arm[0], L_arm[2]), (i, neck(i)))]))
    return dedupe([], out, better=lambda a, b: a["k"] > b["k"])


RECT_LENS = (20, 25, 30, 40, 50, 60, 80, 100, 130, 160, 200, 250)


def _distinct(a):
    r = []
    for x in a:
        if not r or x - r[-1] >= 3:
            r.append(x)
    return r


def rectangles(B, ks=3, t_from=0):
    lo, hi, cl, n = B.lo, B.hi, B.cl, B.n
    mx = pd.Series(hi).rolling(2 * ks + 1, center=True, min_periods=ks + 1).max().to_numpy()
    mn = pd.Series(lo).rolling(2 * ks + 1, center=True, min_periods=ks + 1).min().to_numpy()
    sh = (hi >= mx); sl = (lo <= mn)
    hh20 = pd.Series(hi).rolling(20).max().shift(1).to_numpy()
    out = []
    last = -99
    for t in range(max(260, t_from - MARGIN), n):
        if not (cl[t] > hh20[t] and cl[t - 1] <= hh20[t - 1]) or t - last < 10:
            continue
        best = None
        for Ln in RECT_LENS:
            s, e = t - Ln, t - 1                          # window [s, e]
            if s < 70:
                break
            top, bot = hi[s:e + 1].max(), lo[s:e + 1].min()
            h = top - bot
            if not (LN(1.04) <= h <= LN(1.30)):
                continue
            if not cl[t] > top:
                continue
            idx = np.arange(s, e + 1 - ks)                # swing touches, confirmed by e
            th = idx[sh[s:e + 1 - ks] & (hi[s:e + 1 - ks] >= top - 0.20 * h)]
            tb = idx[sl[s:e + 1 - ks] & (lo[s:e + 1 - ks] <= bot + 0.20 * h)]
            th, tb = _distinct(th), _distinct(tb)        # distinct touches: at least 3 sessions apart
            if not ((len(th) >= 3 and len(tb) >= 2) or (len(th) >= 2 and len(tb) >= 3)):
                continue
            mid = s + Ln / 2                              # side to side: both lines touched in each half
            halves = (any(x < mid for x in th) and any(x >= mid for x in th) and any(x < mid for x in tb) and any(x >= mid for x in tb))
            allt = sorted(th + tb)
            if allt[0] - s > 0.25 * Ln or e - allt[-1] > 0.25 * Ln:
                continue
            x = np.arange(Ln); sl_ = np.polyfit(x, cl[s:e + 1], 1)[0] * Ln     # flat: no drift of the closes across the box
            if abs(sl_) > 0.35 * h:
                continue
            pre_lo, pre_hi = lo[max(0, s - 63):s].min(), hi[max(0, s - 63):s].max()   # trend into the box (63 sessions before)
            into = "up" if (bot - pre_lo) >= 0.5 * h and (bot - pre_lo) > (pre_hi - top) else ("down" if (pre_hi - top) >= 0.5 * h else "none")
            best = dict(t=t, s=s, Ln=Ln, Hgt=h, level=top, RSl=bot, ntop=len(th), nbot=len(tb), drift=sl_ / h, into=into, halves=halves,
                        clean=B.clean(s, t), pts=[(x_, hi[x_], "") for x_ in th] + [(x_, lo[x_], "") for x_ in tb],
                        lines=[((s, top), (t, top)), ((s, bot), (t, bot))])
        if best is not None:
            out.append(best); last = t
    return out


def rounding_bottoms(B, t_from=0):
    lo, hi, cl, n = B.lo, B.hi, B.cl, B.n
    out = []
    hh20 = pd.Series(hi).rolling(20).max().shift(1).to_numpy()
    C = np.exp(cl)
    last = -99
    for t in range(max(330, t_from - MARGIN), n):
        if not (cl[t] > hh20[t]) or t - last < 10:
            continue
        seg = hi[t - 326:t][::-1]                         # t-1 back
        rec_ = np.flatnonzero(seg >= np.maximum.accumulate(seg) - 1e-12)
        cand = [t - 1 - r for r in rec_ if hi[t - 1 - r] < cl[t]]
        if not cand:
            continue
        L = min(cand)                                     # the farthest high that the close clears (the left rim)
        if not (cl[t - 1] <= hi[L]):
            continue
        Ln = t - L
        if not (35 <= Ln <= 325):
            continue
        b = L + int(np.argmin(lo[L:t])); PB = lo[b]
        depth = hi[L] - PB
        if not (LN(1.12) <= depth <= LN(1.60)):
            continue
        rm, kk, xb = template_fit(C, L, t, np.exp(PB), np.exp(hi[L]))
        bpos = (b - L) / Ln
        lpeak = bool(hi[L] >= hi[max(0, L - 15):L + 1].max() - 1e-12)
        out.append(dict(t=t, L=L, b=b, Ln=Ln, Hgt=depth, level=hi[L], RSl=PB, rmse=rm, kexp=kk, bpos=bpos, lpeak=lpeak,
                        wB=B.width(b, depth, side=20), clean=B.clean(L, t),
                        pts=[(L, hi[L], "rim"), (b, PB, "low")], lines=[((L, hi[L]), (t, hi[L]))]))
        last = t
    return out


def inv_desc_scallops(B, t_from=0):
    lo, hi, cl, n = B.lo, B.hi, B.cl, B.n
    out = []
    Cm = np.exp(-cl)
    for k in (6, 9, 13):
        z = B.zz[k]
        for j in range(len(z) - 2):
            (a, t1, al), (b, t2, bh), (c, t3, cl_) = z[j], z[j + 1], z[j + 2]
            if not (t1 == -1 and t2 == 1 and t3 == -1):
                continue
            if not cl_ < al:                                # descending: ends below where it started
                continue
            if c + 2 * (c - a) + 59 < t_from - MARGIN:
                continue
            start = c + k + 1
            res = None
            for i in range(c + 1, min(n, c + 2 * (c - a) + 60)):
                if lo[i] < cl_:
                    break
                if cl[i] > bh:
                    if i >= start:
                        res = i
                    break
            if res is None:
                continue
            i = res
            up, dn = bh - al, bh - cl_
            W = c - a
            back = np.flatnonzero(lo[b:c + 1] <= al)
            c1 = b + int(back[0]) if len(back) else c
            rm, kk, xb = template_fit(Cm, a, c1, np.exp(-bh), np.exp(-al)) if c1 - a >= 8 else (9, None, None)
            topw = float((hi[a:c1 + 1] >= bh - 0.2 * up).mean()) if c1 > a else 0.0
            out.append(dict(t=i, A=a, Bp=b, Cv=c, k=k, W=W, Hgt=dn, level=bh, RSl=cl_, ratio=up / dn, rmse=rm, kexp=kk, topw=topw,
                            wait=i - c, clean=B.clean(a, i), pts=[(a, al, "A"), (b, bh, "B"), (c, cl_, "C")], lines=[((b, bh), (i, bh))]))
    return dedupe([], out, better=lambda a, b: a["rmse"] < b["rmse"])


def barr_bottoms(B, t_from=0):
    lo, hi, cl, n = B.lo, B.hi, B.cl, B.n
    out = []
    for k in (6, 9, 13):
        z = B.zz[k]
        highs = [p for p in z if p[1] == 1]
        for x, (A, _, Ah) in enumerate(highs):
            if A + 299 < t_from - MARGIN:
                continue
            for (T2, _, T2h) in highs[x + 1:x + 6]:      # second touch of the down-sloping line: a later swing high
                if T2 - A < 15 or T2h >= Ah:
                    continue
                s = (T2h - Ah) / (T2 - A)
                line = lambda i: Ah + s * (i - A)
                seg = np.arange(A, T2 + 1)
                if (hi[A:T2 + 1] > line(seg) + 1e-9).any():
                    continue
                res = None
                for i in range(T2 + 1, min(n, A + 300)):
                    if cl[i] > line(i):
                        res = i
                        break
                if res is None:
                    continue
                t = res
                if (hi[T2 + 1:t] > line(np.arange(T2 + 1, t)) + LN(1.01)).any():
                    continue
                Ln = t - A
                if Ln < 40:
                    continue
                dist = line(np.arange(A, t)) - lo[A:t]
                q = max(5, Ln // 4)
                lead_h = dist[:q].max()
                bidx = int(np.argmax(dist)); bump_h = dist[bidx]; bot = A + bidx
                outside = np.flatnonzero(dist[:bidx + 1] <= lead_h)      # the bump starts where price leaves the lead-in channel
                bstart = A + (outside[-1] if len(outside) else 0)
                lead_len = bstart - A
                if bot - bstart < 3:
                    continue
                lead_slope = -s
                bump_slope = (lo[bstart] - lo[bot]) / (bot - bstart)
                out.append(dict(t=t, A=A, T2=T2, k=k, Ln=Ln, Hgt=bump_h, level=line(t), RSl=lo[bot], lead_h=lead_h, bump_h=bump_h,
                                ratio=bump_h / lead_h if lead_h > 0 else np.nan, lead_len=lead_len, bot=bot, bstart=bstart,
                                steep=bump_slope / lead_slope if lead_slope > 0 else np.nan,
                                run=t - bot, clean=B.clean(A, t),
                                pts=[(A, Ah, "A"), (T2, T2h, ""), (bstart, lo[bstart], "bump"), (bot, lo[bot], "low")],
                                lines=[((A, Ah), (t, line(t)))]))
                break
    return dedupe([], out, better=lambda a, b: a["ratio"] > b["ratio"])


def pct_zigzag(hi, lo, a, b, thr):
    """percentage zig-zag on [a, b): alternating swing highs/lows with reversals of at least thr (log)."""
    piv = [(a, 1, hi[a])]; mode = -1                     # start at the base high, look for a low
    cur_i, cur_v = a, lo[a]
    for i in range(a + 1, b):
        if mode == -1:
            if lo[i] < cur_v:
                cur_i, cur_v = i, lo[i]
            if hi[i] - cur_v >= thr:
                piv.append((cur_i, -1, cur_v)); mode = 1; cur_i, cur_v = i, hi[i]
        else:
            if hi[i] > cur_v:
                cur_i, cur_v = i, hi[i]
            if cur_v - lo[i] >= thr:
                piv.append((cur_i, 1, cur_v)); mode = -1; cur_i, cur_v = i, lo[i]
    piv.append((cur_i, mode, cur_v))
    return piv


def vcps(B, rs=None, t_from=0):
    """VCP (Minervini): the base starts at a peak (no higher high in the 10 sessions before it); every contraction lasts at
    least a week (5 sessions high to next high, 3+ high to low); all base highs up to 325 sessions back are tried, nearest
    first, at four swing sizes."""
    lo, hi, cl, n, V = B.lo, B.hi, B.cl, B.n, B.V
    C = B.C
    s50 = pd.Series(C).rolling(50).mean().to_numpy(); s150 = pd.Series(C).rolling(150).mean().to_numpy()
    s200 = pd.Series(C).rolling(200).mean().to_numpy()
    hi252 = pd.Series(B.H).rolling(252, min_periods=200).max().to_numpy(); lo252 = pd.Series(B.L).rolling(252, min_periods=200).min().to_numpy()
    hh5 = pd.Series(hi).rolling(5).max().shift(1).to_numpy()
    out = []; last = -99
    for t in range(max(260, t_from - MARGIN), n):
        if not cl[t] > hh5[t] or t - last < 10:
            continue
        if not ((C[t] > s150[t] > s200[t]) and (s50[t] > s150[t]) and (C[t] > s50[t])):
            continue
        seg = hi[max(0, t - 326):t][::-1]
        recs = np.flatnonzero(seg >= np.maximum.accumulate(seg) - 1e-12)
        H0s = [t - 1 - r for r in recs if 15 <= r + 1 <= 325]
        found = None
        for H0 in H0s:
            if H0 >= 10 and hi[H0] < hi[H0 - 10:H0].max() - 1e-12:
                continue                                  # the left side of a base is a peak: no higher high in the 10 sessions before
            for thr in (1.03, 1.045, 1.06, 1.08):        # coarser swing filters merge the small wiggles inside a long base
                piv = pct_zigzag(hi, lo, H0, t, LN(thr))
                pairs = [(piv[x], piv[x + 1]) for x in range(len(piv) - 1) if piv[x][1] == 1 and piv[x + 1][1] == -1]
                if not (2 <= len(pairs) <= 6):
                    continue
                depths = [ph[2] - pl[2] for ph, pl in pairs]
                pivot = pairs[-1][0][2]
                if not (cl[t] > pivot and cl[t - 1] <= pivot):
                    continue
                if not (all(depths[x + 1] < depths[x] for x in range(len(depths) - 1)) and depths[0] >= LN(1.10) and depths[-1] <= LN(1.10)):
                    continue
                ends = [pairs[x + 1][0][0] for x in range(len(pairs) - 1)] + [t]
                durs = [e - ph[0] for (ph, pl), e in zip(pairs, ends)]
                falls = [pl[0] - ph[0] for ph, pl in pairs]
                if min(durs) < 5 or min(falls) < 3:
                    continue
                found = dict(H0=H0, pairs=pairs, depths=depths, pivot=pivot, durs=durs)
                break
            if found:
                break
        if not found:
            continue
        d = found["depths"]; pairs = found["pairs"]; H0 = found["H0"]
        lows = [pl[2] for ph, pl in pairs]
        fc_start = pairs[-1][0][0]
        vol_last = V[fc_start:t].mean(); vol_base = V[H0:t].mean()
        tt = (C[t] > s150[t] > s200[t]) and (s200[t] > s200[t - 21]) and (s50[t] > s150[t]) and (C[t] > s50[t]) \
            and (C[t] >= 1.30 * lo252[t]) and (C[t] >= 0.75 * hi252[t])
        h0sup = int((hi[max(0, H0 - 10):H0 + 4] >= hi[H0] - LN(1.03)).sum())
        out.append(dict(t=t, H0=H0, nT=len(d), d1=d[0], dlast=d[-1], higher_lows=all(lows[x + 1] > lows[x] for x in range(len(lows) - 1)),
                        h0sup=h0sup, weeks=(t - H0) / 5, vol_rel50=vol_last / B.v50[t] if B.v50[t] > 0 else np.nan,
                        vol_dry=vol_last / vol_base if vol_base > 0 else np.nan,
                        trend_template=bool(tt), rs=(rs[t] if rs is not None else np.nan),
                        Hgt=hi[H0] - min(lows), level=found["pivot"], RSl=pairs[-1][1][2], clean=B.clean(H0, t),
                        depths=[float(x) for x in d],
                        pts=[(H0, hi[H0], "")] + [(ph[0], ph[2], "") for ph, pl in pairs[1:]] + [(pl[0], pl[2], f"T{x+1}") for x, (ph, pl) in enumerate(pairs)],
                        lines=[((pairs[-1][0][0], found["pivot"]), (t, found["pivot"]))]))
        last = t
    return out


# ── head and shoulders (bottom = inverse H&S; top = the same detector on the mirror image) ──
HSP = dict(scales=(4, 6, 9, 13, 19), head_min=0.20, sh_sym=0.25, t_lo=0.5, t_hi=2.0, sd_lo=0.30, sd_hi=0.85,
           neck_slope=0.40, w_min=15, w_max=250, h_min=np.log(1.06), prior=0.5, guard=0.35, rs_wait=10)


def hs_detect(lo, hi, cl, V, t_from=0, P=HSP):
    """lo/hi/cl: log prices (or mirrored for tops). One pattern per breakout (cleanest across scales)."""
    n = len(cl)
    r = np.abs(np.diff(cl)); big = np.r_[0, (r > np.log(1 + P["guard"])).astype(int)].cumsum()
    found = {}
    for k in P["scales"]:
        zz = zigzag(lo, hi, k)
        for j in range(len(zz) - 2):
            (LS, tL, LSl), (A1, tA, A1h), (HD, tH, HDl) = zz[j], zz[j + 1], zz[j + 2]
            if not (tL == -1 and tA == 1 and tH == -1):
                continue
            if not (HDl < LSl):
                continue
            if lo[LS:A1 + 1].min() < LSl - 1e-12 or hi[LS:HD + 1].max() > A1h + 1e-12:
                continue
            start = HD + k + 1                       # head confirmed
            if start >= n:
                continue
            d1 = HD - LS
            imax = min(n - 1, HD + int(P["t_hi"] * d1) + max(P["rs_wait"], d1) + 1)
            if imax < t_from - MARGIN:
                continue
            A2 = None; A2h = -np.inf
            res = None
            for i in range(HD + 1, imax + 1):
                if lo[i] < HDl:                       # undercut the head: no pattern
                    break
                if i >= start and A2 is not None:
                    RSi = A2 + 1 + int(np.argmin(lo[A2 + 1:i])) if i - A2 >= 2 else None
                    if RSi is not None:
                        s = (A2h - A1h) / (A2 - A1)
                        level = A1h + s * (i - A1) if s <= 0 else A2h
                        if cl[i] > level:
                            res = (i, A2, A2h, RSi, s, level)
                            break
                if hi[i] > A2h:
                    A2, A2h = i, hi[i]
            if res is None:
                continue
            i, A2, A2h, RS, s, level = res
            RSl = lo[RS]
            if RSl <= HDl:
                continue
            neck = lambda x: A1h + s * (x - A1)
            prev = np.arange(A2 + 1, i)              # the first close above the confirmation level after the right armpit
            if len(prev) and (cl[A2 + 1:i] > (neck(prev) if s <= 0 else A2h)).any():
                continue
            Hgt = neck(HD) - HDl
            if Hgt < P["h_min"]:
                continue
            hp = (min(LSl, RSl) - HDl) / Hgt
            sdL, sdR = (neck(LS) - LSl) / Hgt, (neck(RS) - RSl) / Hgt
            sym = abs(LSl - RSl) / Hgt
            d2 = RS - HD
            tr = d2 / d1 if d1 > 0 else np.inf
            slope = abs(A2h - A1h) / Hgt
            W = RS - LS
            p0 = max(0, LS - 63)
            prior = (hi[p0:LS + 1].max() - neck(LS)) / Hgt if LS - p0 >= 20 else np.nan
            wait = i - RS
            ok = dict(head=hp >= P["head_min"], sym=sym <= P["sh_sym"], time=P["t_lo"] <= tr <= P["t_hi"],
                      sd=(P["sd_lo"] <= sdL <= P["sd_hi"]) and (P["sd_lo"] <= sdR <= P["sd_hi"]),
                      slope=slope <= P["neck_slope"], width=P["w_min"] <= W <= P["w_max"],
                      prior=bool(prior >= P["prior"]), wait=wait <= max(P["rs_wait"], d2),
                      guard=big[i] - big[max(0, LS - 1)] == 0)
            if not all(ok.values()):
                continue
            xs = [LS, A1, HD, A2, RS, i]; ys = [LSl, A1h, HDl, A2h, RSl, cl[i]]     # cleanliness vs the ideal zig-zag
            ideal = np.interp(np.arange(LS, i + 1), xs, ys)
            rmse = float(np.sqrt(np.mean((cl[LS:i + 1] - ideal) ** 2)) / Hgt)
            rec = dict(t=i, LS=LS, A1=A1, HD=HD, A2=A2, RS=RS, k=k, Hgt=Hgt, symm=sym, W=W, rmse=rmse, level=level,
                       LSl=LSl, A1h=A1h, HDl=HDl, A2h=A2h, RSl=RSl, s=s, clean=True,
                       pts=[(LS, LSl, "S"), (A1, A1h, ""), (HD, HDl, "H"), (A2, A2h, ""), (RS, RSl, "S")],
                       lines=[((A1, A1h), (i, neck(i)))])
            near = [kk for kk in found if abs(kk - i) <= 5]     # one pattern per breakout day: keep the cleanest across scales
            if near:
                best = min(near, key=lambda kk: found[kk]["rmse"])
                if rec["rmse"] < found[best]["rmse"]:
                    for kk in near:
                        del found[kk]
                    found[i] = rec
            else:
                found[i] = rec
    return [found[k] for k in sorted(found)]


def ihs(B, t_from=0):
    return hs_detect(B.lo, B.hi, B.cl, B.V, t_from)


def hst(B, t_from=0):
    """head-and-shoulders top: the bottom detector on the mirror image; prices are flipped back for display."""
    out = hs_detect(-B.hi, -B.lo, -B.cl, B.V, t_from)
    for p in out:
        p["mirror"] = True
    return out


# ── cup with handle (O'Neil / Bulkowski), on raw prices ──
CWP = dict(h_min=5, h_max=60, h_depth_min=0.02, h_depth_max=0.12, cup_min=35, cup_max=325, depth_min=0.12, depth_max=0.35,
           lip_lo=0.93, lip_hi=1.03, bpos_lo=0.15, bpos_hi=0.85, u_zone=0.40, u_share=0.30, guard=0.35, wedge=0.0005,
           spike=1.04, rmse=0.16, lipsup=3)


def cups(B, t_from=0, P=CWP):
    """shape rules here; the O'Neil quality rules (prior uptrend, lip near the 6-month high, breakout and handle volume)
    are applied as rules, exactly as in the study."""
    O, H, L, C, V = B.O, B.H, B.L, B.C, B.V
    n = len(C)
    if n < 120:
        return []
    r = np.abs(np.diff(C) / C[:-1])
    big = np.r_[0, (r > P["guard"]).astype(int)].cumsum()
    v50 = pd.Series(V).rolling(50, min_periods=30).mean().shift(1).to_numpy()
    hh5 = pd.Series(H).rolling(5).max().shift(1).to_numpy()
    out = []
    last_t = -999
    for t in range(max(60, t_from - MARGIN), n):
        if not (C[t] > hh5[t]):                        # must clear at least a 5-day high (the handle)
            continue
        if t - last_t < 10:
            continue
        lo_ = max(0, t - 1 - P["h_max"])
        seg = H[lo_:t][::-1]                             # t-1 back
        sufmax = np.maximum.accumulate(seg)
        recs = np.flatnonzero(seg >= sufmax - 1e-12)     # backward records = candidate right lips
        found = None
        for k in recs:
            iR = t - 1 - k
            hl = t - 1 - iR                              # handle length (sessions R+1..t-1)
            if hl < P["h_min"]:
                continue
            PR = H[iR]
            if not (C[t] > PR and C[t - 1] <= PR):
                continue
            PH = L[iR + 1:t].min(); iH = iR + 1 + int(np.argmin(L[iR + 1:t]))
            hd = 1 - PH / PR
            if not (P["h_depth_min"] <= hd <= P["h_depth_max"]):
                continue
            a = max(0, iR - P["cup_max"])                # left lip: past a dip of depth_min, then the nearest high at lip level
            lows_b = L[a:iR][::-1]
            runmin = np.minimum.accumulate(lows_b)
            dip = np.flatnonzero(runmin <= PR * (1 - P["depth_min"]))
            if not len(dip):
                continue
            jd = dip[0]
            highs_b = H[a:iR][::-1]
            lipk = np.flatnonzero(highs_b[jd:] >= P["lip_lo"] * PR)
            if not len(lipk):
                continue
            j0 = iR - 1 - (jd + lipk[0])
            w0 = max(0, j0 - 20)
            iL = w0 + int(np.argmax(H[w0:j0 + 1]))
            PL = H[iL]
            cl = iR - iL
            if not (P["cup_min"] <= cl <= P["cup_max"]):
                continue
            if not (P["lip_lo"] <= PR / PL <= P["lip_hi"]):
                continue
            if hl > max(P["h_min"], 0.5 * cl):
                continue
            iB = iL + int(np.argmin(L[iL:iR + 1])); PB = L[iB]
            if H[iB:iR + 1].max() > PR:                  # R must be the highest point of the right side
                continue
            depth = 1 - PB / PL
            if not (P["depth_min"] <= depth <= P["depth_max"]):
                continue
            bpos = (iB - iL) / cl
            if not (P["bpos_lo"] <= bpos <= P["bpos_hi"]):
                continue
            top = min(PL, PR)
            zone = PB + P["u_zone"] * (top - PB)
            ushare = float((C[iL:iR + 1] <= zone).mean())
            if ushare < P["u_share"]:
                continue
            if PH < PB + 0.5 * (PR - PB):              # handle in the upper half
                continue
            x = np.arange(hl)
            slope = np.polyfit(x, L[iR + 1:t] / PR, 1)[0] if hl >= 3 else 0.0
            if slope > P["wedge"]:                       # rising-low (wedging) handle
                continue
            sixm = H[max(0, iL - 126):iL + 1].max() / PL if iL >= 60 else np.nan
            if not (sixm <= 10):
                continue
            nb = np.r_[H[max(0, iL - 10):max(0, iL - 1)], H[iL + 2:iL + 11]]
            if len(nb) and PL > P["spike"] * nb.max():
                continue
            rm, kk, xb = template_fit(C, iL, iR, PB, min(PL, PR))
            if rm > P["rmse"]:
                continue
            ls = lip_support(H, iL, PL)
            if ls < P["lipsup"]:
                continue
            p0 = max(0, iL - 250)
            prior = PL / L[p0:iL + 1].min() - 1 if iL - p0 >= 60 else np.nan
            if not (prior >= -1):                        # the study's shape run skipped these (no year of history before the cup)
                continue
            vx = V[t] / v50[t] if v50[t] > 0 else np.nan
            if not (vx >= 0):
                continue
            if big[t] - big[max(0, iL - 1)] > 0:
                continue
            hv = V[iR + 1:t].mean() / v50[iR] if v50[iR] > 0 else np.nan
            if not (hv <= 1e9):
                continue
            found = dict(t=t, iL=iL, iB=iB, iR=iR, iH=iH, PL=PL, PB=PB, PR=PR, PH=PH, depth=depth, prior=prior, vx=vx, hvol=hv,
                         sixm=sixm, clean=True, Hgt=math.log(PR / PB), level=math.log(PR), RSl=math.log(PH),
                         pts=[(iL, math.log(PL), "lip"), (iB, math.log(PB), "low"), (iR, math.log(PR), "lip"), (iH, math.log(PH), "handle")],
                         lines=[((iR, math.log(PR)), (t, math.log(PR)))])
            break
        if found:
            out.append(found)
            last_t = t
    return out


# ═════════════════════════════════ rules (as numbers; identical to the study) ═════════════════════════════════
def _eve_eve(p):
    return (p["diff"] <= LN(1.06) and 10 <= p["gap"] <= 60 and p["rise"] >= LN(1.10) and p["wait"] <= max(15, p["gap"])
            and p["prior"] >= 1.0 and p["prior30"] >= 0.75 and p["Hgt"] >= LN(1.12) and p["w1"] >= 8 and p["w2"] >= 8)


def _big_w(p):
    return (p["diff"] <= LN(1.06) and 10 <= p["gap"] <= 60 and p["rise"] >= LN(1.10) and p["wait"] <= max(15, p["gap"])
            and p["left"] >= 2.0 and p["straight"] >= 0.70 and 15 <= p["left_len"] <= 126 and p["b1_lowest"] and p["Hgt"] >= LN(1.12))


def _triple_bottom(p):
    return (p["spread"] <= min(LN(1.05), 0.25 * p["Hgt"]) and p["r1"] >= 0.4 and p["r2"] >= 0.4 and p["d12"] >= 8 and p["d23"] >= 8
            and p["d12"] + p["d23"] <= 250 and p["prior"] >= 0.5 and p["up12"] >= -LN(1.02) and p["up12"] + p["up23"] >= -LN(1.02)
            and p["Hgt"] >= LN(1.10) and p["wait"] <= max(15, p["d23"]))


def _three_rising(p):
    w = (p["w1"], p["w2"], p["w3"])
    return (p["up12"] >= LN(1.02) and p["up23"] >= LN(1.02) and max(w) <= 2.5 * min(w) and p["r1"] >= 0.3 and p["r2"] >= 0.3
            and p["d12"] >= 6 and p["d23"] >= 6 and p["d12"] + p["d23"] <= 200 and p["Hgt"] >= LN(1.08) and p["wait"] <= max(15, p["d23"]))


def _complex_hs(p):
    return (p["complex"] and p["first"] and p["mid_ok"] and p["sd_min"] >= 0.25 and p["sd_max"] <= 0.85 and p["head"] >= 0.2
            and p["osym"] <= 0.25 and 0.5 <= p["tratio"] <= 2.0 and 25 <= p["W"] <= 250 and p["Hgt"] >= LN(1.10) and p["prior"] >= 0.5
            and abs(p["slope"]) <= 0.4 and p["wait"] <= 20)


def _rect_ok(p):
    return p["halves"] and LN(1.05) <= p["Hgt"] <= LN(1.20) and abs(p["drift"]) <= 0.25


def _rounding_bottom(p):
    return (p["rmse"] <= 0.16 and 0.2 <= p["bpos"] <= 0.8 and p["kexp"] is not None and p["kexp"] >= 1.25 and 40 <= p["Ln"] <= 325
            and p["wB"] >= 8 and p["lpeak"])


def _scallop(p):
    return (0.3 <= p["ratio"] <= 0.85 and p["rmse"] <= 0.18 and p["kexp"] is not None and p["kexp"] >= 2.0 and p["topw"] >= 0.25
            and 15 <= p["W"] <= 200 and p["Hgt"] >= LN(1.10) and p["wait"] <= p["W"])


def _barr(p):
    return (p["ratio"] >= 2.5 and p["lead_len"] >= max(20, 0.25 * p["Ln"]) and p["steep"] >= 2.5 and 40 <= p["Ln"] <= 300
            and p["run"] >= 5 and p["Hgt"] >= LN(1.15))


def _vcp(p):
    return (2 <= p["nT"] <= 6 and LN(1.10) <= p["d1"] <= LN(1.40) and p["dlast"] <= LN(1.10) and 6 <= p["weeks"] <= 65
            and p["vol_rel50"] < 1 and p["trend_template"] and p["rs"] >= 70 and p["h0sup"] >= 2 and p["higher_lows"])


def _hs_final(p):
    return p["Hgt"] >= LN(1.10) and p["W"] >= 20 and p["symm"] <= 0.20 and p["rmse"] <= 0.22


def _cwh(p):
    return p["prior"] >= 0.30 and p["sixm"] <= 1.05 and p["vx"] >= 1.4 and p["hvol"] <= 1.10


def _safe(rule):
    def f(p):
        try:
            return bool(rule(p))
        except (TypeError, KeyError):
            return False
    return f


# (id, detector, rule, kind)  - the order here is only for running; the site orders by config/pattern_evidence.json
PATTERNS = [
    ("vcp", "vcp", _safe(_vcp), "buy"),
    ("scallop", "scallop", _safe(_scallop), "buy"),
    ("ihs", "ihs", _safe(_hs_final), "buy"),
    ("bigw", "double", _safe(_big_w), "buy"),
    ("tb", "valleys", _safe(_triple_bottom), "buy"),
    ("rectb", "rect", _safe(lambda p: p["into"] == "down" and _rect_ok(p)), "buy"),
    ("chs", "chs", _safe(_complex_hs), "buy"),
    ("3rv", "valleys", _safe(_three_rising), "buy"),
    ("rectt", "rect", _safe(lambda p: p["into"] == "up" and _rect_ok(p)), "buy"),
    ("rb", "rbottom", _safe(_rounding_bottom), "buy"),
    ("barr", "barr", _safe(_barr), "buy"),
    ("ee", "double", _safe(_eve_eve), "buy"),
    ("cwh", "cup", _safe(_cwh), "buy"),
    ("hst", "hst", _safe(_hs_final), "sell"),
]
DETECT = {"vcp": vcps, "scallop": inv_desc_scallops, "ihs": ihs, "double": double_bottoms, "valleys": three_valleys,
          "rect": rectangles, "chs": complex_hs, "rbottom": rounding_bottoms, "barr": barr_bottoms, "cup": cups, "hst": hst}
BUY_DET = [k for k in DETECT if k != "hst"]


def run(B, dets, rs, t_from):
    """{detector: [records with t >= t_from]}"""
    res = {}
    for k in dets:
        f = DETECT[k]
        pats = f(B, rs=rs, t_from=t_from) if k == "vcp" else f(B, t_from=t_from)
        res[k] = [p for p in pats if p["t"] >= t_from]
    return res


def hits(B, dets, rs, t_from):
    """[(pattern id, record)] that pass every rule (and the one-day-move data guard)"""
    found = run(B, dets, rs, t_from)
    out = []
    for pid, det, rule, kind in PATTERNS:
        if det not in found:
            continue
        for p in found[det]:
            if p.get("clean", True) and rule(p):
                out.append((pid, p))
    return out


# ═════════════════════════════════ daily scan ═════════════════════════════════
def with_bar(d, close, vol):
    """d plus one hypothetical session that closes at `close` (opens at today's close; high/low span both)."""
    c0 = float(d["close"].iloc[-1])
    row = {"date": "next", "open": c0, "high": max(c0, close), "low": min(c0, close), "close": close, "volume": vol}
    return pd.concat([d, pd.DataFrame([row])], ignore_index=True)


def trigger(d, pid, det, rule, sign, g_hi, rs, vol):
    """lowest close (highest for the H&S top) in (today, today*(1+g_hi)] that confirms pattern `pid` tomorrow, by bisection"""
    c0 = float(d["close"].iloc[-1])
    def ok(g):
        dd = with_bar(d, c0 * (1 + sign * g), vol)
        B = Bars(dd)
        r = np.r_[rs, rs[-1]] if rs is not None else None
        return [p for q, p in hits(B, [det], r, len(dd) - 1) if q == pid]
    lo, hi = 0.0, g_hi
    best = ok(hi)
    if not best:
        return None
    for _ in range(7):
        mid = (lo + hi) / 2
        m = ok(mid)
        if m:
            hi, best = mid, m
        else:
            lo = mid
    return hi, best[0]


def scan_stock(d, rs):
    """d: one stock's last HIST sessions (date, open, high, low, close, volume); rs: RS rating per row (NaN where unknown).
    Returns broke-out hits [(pid, rec, None)] and forming hits [(pid, rec, gap)] (gap = % move the trigger needs)."""
    n = len(d)
    B = Bars(d)
    out = [(pid, p, None) for pid, p in hits(B, list(DETECT), rs, n - WINDOW)]
    v50 = B.v50[-1] if np.isfinite(B.v50[-1]) else float(d["volume"].iloc[-30:].mean())
    vol = 2.0 * v50                                     # a breakout-sized volume for the hypothetical session
    c0 = float(d["close"].iloc[-1])
    seen = set()
    for sign, dets in ((1, BUY_DET), (-1, ["hst"])):
        for g in (NEAR, 0.02):
            dd = with_bar(d, c0 * (1 + sign * g), vol)
            r = np.r_[rs, rs[-1]] if rs is not None else None
            for pid, p in hits(Bars(dd), dets, r, n):
                if pid in seen:
                    continue
                seen.add(pid)
                det, rule = next((dt, ru) for q, dt, ru, _ in PATTERNS if q == pid)
                tr = trigger(d, pid, det, rule, sign, g, rs, vol)
                if tr:
                    out.append((pid, tr[1], tr[0]))
    return out


# ═════════════════════════════════ output ═════════════════════════════════
def rd(v):
    if v is None or not np.isfinite(v):
        return None
    v = round(float(v), 0 if v >= 1000 else 1 if v >= 100 else 2)
    return int(v) if v == int(v) else v


def plain(o):
    """numpy numbers -> plain Python (json cannot write numpy ints); non-finite floats -> None"""
    if isinstance(o, dict):
        return {k: plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [plain(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    return o


def card(pid, p, d, gap, kind):
    """everything the site shows for one pattern on one stock"""
    n = len(d)
    mir = p.get("mirror", False)
    px = (lambda y: math.exp(-y)) if mir else (lambda y: math.exp(y))
    dates = d["date"].tolist()
    t = p["t"]
    fm = gap is not None
    last_real = n - 1
    dt = lambda i: dates[i] if i < n else "next"
    level = px(p["level"])
    stop = px(p["RSl"])
    if pid == "cwh":
        target = p["PR"] + (p["PR"] - p["PB"])
        ht = p["PR"] / p["PB"] - 1
    elif pid == "vcp":
        target = None
        ht = math.exp(p["Hgt"]) - 1
    else:
        target = level * math.exp(-p["Hgt"]) if mir else level * math.exp(p["Hgt"])
        ht = math.exp(p["Hgt"]) - 1
    first = int(min([a for a, _, _ in p["pts"]] + [l[0][0] for l in p["lines"]]))
    t = int(t)
    c_now = float(d["close"].iloc[-1])
    row = {"id": pid, "st": "fm" if fm else ("bd" if kind == "sell" else "bo"),
           "d": None if fm else dt(t), "ago": None if fm else last_real - t,
           "lvl": rd(level), "stop": rd(stop), "tgt": rd(target) if target is not None else None,
           "ht": round(ht * 100, 1), "wk": round((t - first) / 5, 1), "start": dt(first),
           "pts": [[dt(int(i)), rd(px(y)), lab] for i, y, lab in p["pts"]],
           "lines": [[[dt(int(a[0])), rd(px(a[1]))], [dt(min(int(b[0]), last_real)), rd(px(a[1] + (b[1] - a[1]) * (min(int(b[0]), last_real) - a[0]) / max(1e-9, b[0] - a[0])))]]
                     for a, b in p["lines"]]}
    if fm:
        trig = c_now * (1 - gap) if kind == "sell" else c_now * (1 + gap)
        if abs(trig / level - 1) < 0.003:          # the bisection lands a hair past the level: show the level itself
            trig = level
        row["trig"] = rd(trig)
        row["gap"] = round(abs(trig / c_now - 1) * 100, 2)
    else:
        row["since"] = round((c_now / level - 1) * 100, 1)                # today's close vs the confirmation level
        # failed since: closed back below the pattern low (above the right shoulder for an H&S top)
        row["fail"] = bool(c_now > stop) if kind == "sell" else bool(c_now < stop)
    if pid == "vcp":
        row["nT"] = p["nT"]
        row["dep"] = [round((math.exp(x) - 1) * 100, 1) for x in p["depths"]]
    # small chart for the cards: closes from 15 sessions before the pattern, points and lines by position in that window
    a = max(0, first - 15)
    m_lines = []
    for (i0, y0), (i1, y1) in p["lines"]:
        j1 = min(int(i1), last_real)
        y1c = y0 + (y1 - y0) * (j1 - i0) / max(1e-9, i1 - i0)
        m_lines.append([[int(i0) - a, rd(px(y0))], [j1 - a, rd(px(y1c))]])
    row["m"] = {"c": [rd(x) for x in d["close"].iloc[a:].tolist()], "p": [[int(i) - a, rd(px(y)), lab] for i, y, lab in p["pts"]],
                "l": m_lines, "b": None if fm else int(t) - a}
    return row, first


def build(PFULL, U, rs_hist, last, out_dir, evidence=None):
    """PFULL: long price table; U: liquid symbols; rs_hist: DataFrame (dates x symbols) of RS ratings for recent sessions."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.json"):
        f.unlink()
    uset = set(U)
    P = PFULL[PFULL.symbol.isin(uset)].sort_values(["symbol", "date"])
    rows, files, nfile = [], {}, 0
    stats = {"stocks": 0, "short": 0}
    for sym, g in P.groupby("symbol", sort=True):
        d = g[["date", "open", "high", "low", "close", "volume"]].dropna(subset=["open", "high", "low", "close"])
        d = d[(d.close > 0) & (d.low > 0) & (d.high >= d.low)].drop_duplicates("date").tail(HIST).reset_index(drop=True)
        d["volume"] = d["volume"].fillna(0)
        if len(d) < 300 or d["date"].iloc[-1] != last:
            stats["short"] += 1
            continue
        stats["stocks"] += 1
        rs = rs_hist[sym].reindex(d["date"]).to_numpy(dtype=float) if sym in rs_hist.columns else np.full(len(d), np.nan)
        try:
            found = scan_stock(d, rs)
        except Exception as e:                       # one bad series must not stop the run
            print(f"patterns: {sym} skipped ({type(e).__name__}: {e})")
            continue
        if not found:
            continue
        firsts = []
        for pid, p, gap in found:
            kind = "sell" if pid == "hst" else "buy"
            try:
                row, first = card(pid, p, d, gap, kind)
                row = plain(row)
                json.dumps(row, allow_nan=False)            # a row that cannot be written is dropped, not the run
            except (TypeError, ValueError, KeyError, IndexError) as e:
                print(f"patterns: {sym} {pid} left out ({type(e).__name__}: {e})")
                continue
            row["s"] = sym
            rows.append(row)
            firsts.append(first)
        if not firsts:
            continue
        # candles for the chart window: from 40 sessions before the earliest pattern point, at least a year
        a = max(0, min(min(firsts) - 40, len(d) - 260))
        w = d.iloc[a:]
        files[sym] = nfile
        (out_dir / f"{nfile}.json").write_text(json.dumps({
            "s": sym, "d": w["date"].tolist(), "o": [rd(x) for x in w.open], "h": [rd(x) for x in w.high],
            "l": [rd(x) for x in w.low], "c": [rd(x) for x in w.close], "v": [int(x) for x in w.volume]}, separators=(",", ":")))
        nfile += 1
    order = (evidence or {}).get("order") or [q for q, *_ in PATTERNS]
    rk = {q: i for i, q in enumerate(order)}
    rows.sort(key=lambda r: (rk.get(r["id"], 99), {"bo": 0, "bd": 0, "fm": 1}[r["st"]], r["ago"] if r["ago"] is not None else r.get("gap", 0)))
    per_stock = {}
    for r in rows:
        per_stock.setdefault(r["s"], []).append(r["id"])
    summary = {k: sum(1 for r in rows if r["st"] == k) for k in ("bo", "fm", "bd")}
    print(f"patterns: {stats['stocks']} stocks scanned ({stats['short']} skipped: short history or no bar today) -> "
          f"{summary['bo']} breakouts in {WINDOW} sessions, {summary['fm']} forming, "
          f"{summary['bd']} H&S-top breakdowns; " + ", ".join(f"{q}={sum(1 for r in rows if r['id'] == q)}" for q in order))
    return plain({"asof": last, "window": WINDOW, "near": NEAR * 100, "rows": rows, "files": files, "evidence": evidence,
                  "scanned": stats["stocks"]}), per_stock
