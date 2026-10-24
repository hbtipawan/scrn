/* vcp-engine.js — the VCP breakout scanner, an exact JavaScript port of vcp_core.analyze_vcp
   (the Jul-2026 audited version of the VCP app). Only the VCP breakout scanner is ported;
   the reversal scanner is not used.
   Same trend gates, near-high and 52-week-low filters, base detectors (flat, wedge, high tight flag,
   cup with handle, Darvas box, pocket pivot, episodic pivot), score weights and A/B/C grades.
   Python details that can change a result are reproduced too: pandas' rolling mean, numpy's pairwise
   sums and Python's round-half-to-even.
   Each result also carries a "g" block (where the base starts and ends, trendlines, cup rims...) for
   drawing the chart. It is read-only geometry and never changes a result.
   Runs in the browser (window.VCPE) and in node (module.exports). */
(function (root) {
  "use strict";

  function tfParams(tf) {
    return tf === "Weekly"
      ? { maf: 10, mam: 30, mal: 40, win: 52, mom: 26, funnel: 15, epw: 13 }
      : { maf: 50, mam: 150, mal: 200, win: 252, mom: 126, funnel: 30, epw: 65 };
  }

  // ---------- Python / numpy / pandas arithmetic, reproduced exactly ----------
  const ok = x => x !== null && x !== undefined && !Number.isNaN(x);   // vcp_core._ok
  const isfin = Number.isFinite;

  // Python round(x, nd): round half to even, on the exact binary value
  function pyRound(x, nd) {
    nd = nd || 0;
    if (!isfin(x)) return x;
    if (nd === 0) {
      const f = Math.floor(x), d = x - f;
      if (d > 0.5) return f + 1;
      if (d < 0.5) return f;
      return f % 2 === 0 ? f : f + 1;
    }
    if (x === 0) return 0;
    const neg = x < 0, s = Math.abs(x).toFixed(100);      // exact decimal expansion
    const dot = s.indexOf("."), ip = s.slice(0, dot), fr = s.slice(dot + 1);
    const keep = fr.slice(0, nd), nxt = fr.charCodeAt(nd) - 48, rest = fr.slice(nd + 1);
    let up;
    if (nxt > 5) up = true;
    else if (nxt < 5) up = false;
    else if (/[1-9]/.test(rest)) up = true;
    else up = (Number((ip + keep).slice(-1)) % 2) === 1;    // exact tie: to even
    let digits = BigInt(ip + keep);
    if (up) digits += 1n;
    let str = digits.toString();
    if (str.length <= nd) str = "0".repeat(nd - str.length + 1) + str;
    const v = Number(str.slice(0, str.length - nd) + "." + str.slice(str.length - nd));
    return neg ? -v : v;
  }

  // round() on a numpy float64 (np.round): rint(x * 10^nd) / 10^nd — differs from Python's round() on ~3% of values
  function npRound(x, nd) {
    if (!isfin(x)) return x;
    const f = Math.pow(10, nd || 0);
    return pyRound(x * f, 0) / f;
  }
  const RND = (k, x, nd) => (k === "py" ? pyRound(x, nd) : npRound(x, nd));

  // numpy's pairwise summation (np.sum / np.mean on float64), over x[a..b] inclusive, NaN read as `nanv`
  function pw(x, a, n, nanz) {
    const g = j => { const v = x[a + j]; return (nanz && v !== v) ? 0 : v; };
    if (n < 8) {
      let r = 0;
      for (let j = 0; j < n; j++) r += g(j);
      return r;
    } else if (n <= 128) {
      let r0 = g(0), r1 = g(1), r2 = g(2), r3 = g(3), r4 = g(4), r5 = g(5), r6 = g(6), r7 = g(7), j = 8;
      for (; j < n - (n % 8); j += 8) {
        r0 += g(j); r1 += g(j + 1); r2 += g(j + 2); r3 += g(j + 3);
        r4 += g(j + 4); r5 += g(j + 5); r6 += g(j + 6); r7 += g(j + 7);
      }
      let res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7));
      for (; j < n; j++) res += g(j);
      return res;
    }
    let n2 = Math.floor(n / 2);
    n2 -= n2 % 8;
    return pw(x, a, n2, nanz) + pw(x, a + n2, n - n2, nanz);
  }
  const npSum = (x, a, b) => pw(x, a, b - a + 1, false);
  function nanmean(x, a, b) {          // np.nanmean over x[a..b]
    let cnt = 0;
    for (let j = a; j <= b; j++) if (x[j] === x[j]) cnt++;
    if (!cnt) return NaN;
    return pw(x, a, b - a + 1, true) / cnt;
  }
  function nanmax(x, a, b) {
    let m = NaN;
    for (let j = a; j <= b; j++) { const v = x[j]; if (v === v && !(v <= m)) m = v; }
    return m;
  }
  function nanmin(x, a, b) {
    let m = NaN;
    for (let j = a; j <= b; j++) { const v = x[j]; if (v === v && !(v >= m)) m = v; }
    return m;
  }
  const clip01 = v => (v < 0 ? 0 : v > 1 ? 1 : v);     // np.clip(v, 0, 1)

  // pandas Series.rolling(w).mean() — Kahan running sum, same-value shortcut, min_periods = w
  function rollMean(x, w) {
    const N = x.length, out = new Float64Array(N);
    let nobs = 0, sum = 0, cAdd = 0, cRem = 0, neg = 0, same = 0, prev = N ? x[0] : NaN;
    for (let i = 0; i < N; i++) {
      const s = Math.max(0, i - w + 1);
      if (i > 0) {
        const s0 = Math.max(0, i - w);
        for (let j = s0; j < s; j++) {                   // remove
          const val = x[j];
          if (val === val) {
            nobs--; const y = -val - cRem, t = sum + y; cRem = t - sum - y; sum = t;
            if (val < 0 || Object.is(val, -0)) neg--;
          }
        }
      }
      const val = x[i];                                   // add
      if (val === val) {
        nobs++; const y = val - cAdd, t = sum + y; cAdd = t - sum - y; sum = t;
        if (val < 0 || Object.is(val, -0)) neg++;
        if (val === prev) same++; else same = 1;
        prev = val;
      }
      let r;
      if (nobs >= w && nobs > 0) {
        if (same >= nobs) r = prev;
        else {
          r = sum / nobs;
          if (neg === 0 && r < 0) r = 0;
          else if (neg === nobs && r > 0) r = 0;
        }
      } else r = NaN;
      out[i] = r;
    }
    return out;
  }

  // ---------- data ----------
  // bars: {o,h,l,c,v} arrays (already cleaned like screener_core.clean_df), oldest first
  function prepare(bars) {
    const F = k => (bars[k] instanceof Float64Array ? bars[k] : Float64Array.from(bars[k], Number));
    const A = { o: F("o"), h: F("h"), l: F("l"), c: F("c"), v: F("v"), _m: {} };
    A.n = A.c.length;
    return A;
  }
  function smaOf(A, k, w) {
    const key = k + w;
    return A._m[key] || (A._m[key] = rollMean(A[k], w));
  }

  // ---------- base detectors (vcp_core, line by line) ----------
  function tightBase(A, end, maxTight) {
    const c = A.c[end]; let hi = A.h[end], lo = A.l[end], k = 1;
    if (c <= 0 || !(isfin(hi) && isfin(lo)) || (hi - lo) / c > maxTight) return [0, hi, lo];
    for (let j = end - 1; j > Math.max(-1, end - 40); j--) {
      if (!(isfin(A.h[j]) && isfin(A.l[j]))) break;
      const nhi = Math.max(hi, A.h[j]), nlo = Math.min(lo, A.l[j]);
      if ((nhi - nlo) / c > maxTight) break;
      hi = nhi; lo = nlo; k++;
    }
    return [k, hi, lo];
  }

  function funnel(A, end, F, c) {
    const w = Math.max(Math.floor(F / 3), 1);
    const rp = (a, b) => {
      a = Math.max(a, 0);
      if (b < a) return NaN;
      return (nanmax(A.h, a, b) - nanmin(A.l, a, b)) / c;
    };
    return [rp(end - F + 1, end - 2 * w), rp(end - 2 * w + 1, end - w), rp(end - w + 1, end), w];
  }

  function flatBase(A, end, c, maxTight, minBase, F, vol50) {
    const [bk, piv, blo] = tightBase(A, end, maxTight);
    if (bk < minBase || piv <= 0) return null;
    const tight = (piv - blo) / c;
    const [r1, r2, r3, w] = funnel(A, end, F, c);
    if (!ok(r1) || r1 <= 0 || !ok(r3)) return null;
    const contr = r3 / r1;
    if (contr > 1.0) return null;
    const dry = (ok(vol50) && vol50 > 0) ? nanmean(A.v, end - bk + 1, end) / vol50 : 1.0;
    if (dry > 1.0) return null;
    return { bk, piv, blo, tight, contr, dry, type: "Flat", k: { t: "np", c: "np", p: "np", b: "np" },
      g: { kind: "flat", a: end - bk + 1, b: end, f: [Math.max(end - F + 1, 0), end - 2 * w + 1, end - w + 1, end], fr: [r1, r2, r3] } };
  }

  function fit(y, a, L) {                   // vcp_core._fit on x = 0..L-1, y = arr[a..a+L-1]
    if (L < 2) return [0.0, y[a + L - 1], 0.0];
    const x = new Float64Array(L), yy = new Float64Array(L);
    for (let j = 0; j < L; j++) { x[j] = j; yy[j] = y[a + j]; }
    const xm = npSum(x, 0, L - 1) / L, ym = npSum(yy, 0, L - 1) / L;
    const t = new Float64Array(L);
    for (let j = 0; j < L; j++) { const d = x[j] - xm; t[j] = d * d; }
    const sxx = npSum(t, 0, L - 1);
    if (sxx <= 0) return [0.0, ym, 0.0];
    for (let j = 0; j < L; j++) t[j] = (x[j] - xm) * (yy[j] - ym);
    const sxy = npSum(t, 0, L - 1);
    const slope = sxy / sxx, icpt = ym - slope * xm;
    for (let j = 0; j < L; j++) { const d = yy[j] - (slope * x[j] + icpt); t[j] = d * d; }
    const ssr = npSum(t, 0, L - 1);
    for (let j = 0; j < L; j++) { const d = yy[j] - ym; t[j] = d * d; }
    const sst = npSum(t, 0, L - 1);
    const r2 = sst > 0 ? 1.0 - ssr / sst : 0.0;
    return [slope, icpt, r2];
  }

  function gtTuple(a, b) {                  // Python tuple comparison a > b
    for (let j = 0; j < a.length; j++) { if (a[j] > b[j]) return true; if (a[j] < b[j]) return false; }
    return false;
  }

  function wedgeBase(A, end, c, maxTight, minBase, sLo, sHi, vol50) {
    const maxLen = 40, minR2 = 0.35;
    let best = null;
    for (let L = minBase + 2; L <= Math.min(maxLen, end + 1); L++) {
      const s = end - L + 1;
      if (s < 0) break;
      let bad = false;
      for (let j = s; j <= end; j++) if (A.l[j] !== A.l[j] || A.h[j] !== A.h[j]) { bad = true; break; }
      if (bad) continue;
      const [slLo, icLo, r2Lo] = fit(A.l, s, L), [slHi, icHi, r2Hi] = fit(A.h, s, L);
      const wS = icHi - icLo, wE = (slHi * (L - 1) + icHi) - (slLo * (L - 1) + icLo);
      if (wS <= 0 || wE <= 0) continue;
      const contr = wE / wS;
      if (contr > 0.92) continue;
      const band = wE / c;
      if (band > maxTight) continue;
      const sup = slLo / c * 100.0, res = slHi / c * 100.0;
      const asc = (sup >= sLo && r2Lo >= minR2 && slHi <= slLo * 1.05);
      const desc = ((-res) >= sLo && r2Hi >= minR2 && slLo >= -Math.abs(slHi) * 0.5);
      let type, key, lineq;
      if (asc && sup <= sHi) { type = "Ascending"; key = sup; lineq = r2Lo; }
      else if (desc && (-res) <= sHi) { type = "Descending"; key = res; lineq = r2Hi; }
      else continue;
      const piv = nanmax(A.h, s, end), blo = nanmin(A.l, s, end);
      if (piv <= 0) continue;
      const dry = (ok(vol50) && vol50 > 0) ? nanmean(A.v, s, end) / vol50 : 1.0;
      if (dry > 1.0) continue;
      const cand = { bk: L, piv, blo, tight: band, contr, dry, type, slope: npRound(key, 3), lineq: pyRound(lineq, 2), k: { t: "np", c: "py", p: "py", b: "py" },
        g: { kind: "wedge", a: s, b: end, lo: [icLo, slLo], hi: [icHi, slHi] } };
      const rank = [lineq, 1.0 - contr, L / maxLen];
      if (best === null || gtTuple(rank, best[0])) best = [rank, cand];
    }
    return best ? best[1] : null;
  }

  function htfBase(A, end, c, vol50, thrustMin, flagMax) {
    const flagMinLen = 4, flagMaxLen = 30, poleWin = 45;
    let best = null;
    for (let Lf = flagMinLen; Lf <= Math.min(flagMaxLen, end - poleWin); Lf++) {
      const s = end - Lf + 1;
      if (s - poleWin < 0) continue;
      const fhi = nanmax(A.h, s, end), flo = nanmin(A.l, s, end);
      if (fhi <= 0) continue;
      const depth = (fhi - flo) / fhi;
      if (depth > flagMax) continue;
      const poleLow = nanmin(A.l, s - poleWin, s - 1);
      if (poleLow <= 0) continue;
      const thrust = fhi / poleLow - 1.0;
      if (thrust < thrustMin) continue;
      const contr = fhi > poleLow ? (fhi - flo) / (fhi - poleLow) : 1.0;
      if (contr > 0.5) continue;
      const dry = (ok(vol50) && vol50 > 0) ? nanmean(A.v, s, end) / vol50 : 1.0;
      if (dry > 1.0) continue;
      let pj = s - poleWin;
      for (let j = s - poleWin; j < s; j++) if (A.l[j] < A.l[pj]) pj = j;
      const cand = { bk: Lf, piv: fhi, blo: flo, tight: depth, contr: pyRound(contr, 2), dry, type: "HiTightFlag", k: { t: "py", c: "py", p: "py", b: "py" },
        pole: pyRound(thrust * 100, 1), g: { kind: "htf", a: s, b: end, p: pj, pl: poleLow } };
      const rank = [thrust, 1.0 - depth, 1.0 - contr];
      if (best === null || gtTuple(rank, best[0])) best = [rank, cand];
    }
    return best ? best[1] : null;
  }

  function cupHandle(A, end, c, vol50, minDepth, maxDepth, handleMax, hmin, hmax, cmin, cmax) {
    const h = A.h, l = A.l, v = A.v;
    let best = null;
    for (let Hf = hmin; Hf <= hmax; Hf++) {
      const hs = end - Hf + 1;
      if (hs - cmin < 0) break;
      const hHi = nanmax(h, hs, end), hLo = nanmin(l, hs, end);
      if (hHi <= 0) continue;
      const hDepth = (hHi - hLo) / hHi;
      if (hDepth > handleMax) continue;
      for (let Lc = cmin; Lc <= Math.min(cmax, hs); Lc++) {
        const cs = hs - Lc;
        if (cs < 0) break;
        let bad = false;                                  // seg_l = l[cs:hs]
        for (let j = cs; j < hs; j++) if (l[j] !== l[j]) { bad = true; break; }
        if (Lc < 3 || bad) continue;
        const lrim = nanmax(h, cs, cs + 2), rrim = hHi;
        const cupHi = Math.max(lrim, rrim), cupLo = nanmin(l, cs, hs - 1);
        if (cupHi <= 0 || cupLo <= 0) continue;
        const depth = (cupHi - cupLo) / cupHi;
        if (depth < minDepth || depth > maxDepth) continue;
        if (!(0.88 * lrim <= rrim && rrim <= 1.08 * lrim)) continue;
        let bo = 0;
        for (let j = 1; j < Lc; j++) if (l[cs + j] < l[cs + bo]) bo = j;
        if (bo < 0.25 * Lc || bo > 0.75 * Lc) continue;
        const thr = cupLo + 0.20 * depth * cupHi;
        let cnt = 0;
        for (let j = cs; j < hs; j++) if (l[j] <= thr) cnt++;
        if (cnt < Math.max(0.30 * Lc, 4)) continue;
        const m0 = Math.trunc(0.30 * Lc), m1 = Math.min(Math.trunc(0.70 * Lc) + 1, Lc);
        if (m1 - m0 <= 0 || (nanmean(l, cs + m0, cs + m1 - 1) - cupLo) > 0.35 * depth * cupHi) continue;
        if (hLo < cupLo + 0.5 * depth * cupHi) continue;
        if (hDepth > 0.5 * depth) continue;
        const dry = (ok(vol50) && vol50 > 0) ? nanmean(v, hs, end) / vol50 : 1.0;
        if (dry > 1.0) continue;
        const contr = hDepth / depth;
        const cand = { bk: Hf, piv: hHi, blo: hLo, tight: hDepth, contr: pyRound(contr, 2), dry, type: "CupHandle", k: { t: "py", c: "py", p: "py", b: "py" },
          depth: pyRound(depth * 100, 1), note: "cup " + pyRound(depth * 100, 0) + "%",
          g: { kind: "cup", a: cs, b: end, hs: hs, bot: cs + bo, lo: cupLo, lr: lrim } };
        const rank = [depth, 1.0 - contr, Lc / cmax];
        if (best === null || gtTuple(rank, best[0])) best = [rank, cand];
        break;
      }
    }
    return best ? best[1] : null;
  }

  function darvasBox(A, end, c, vol50, conf, maxAge, minPct, maxPct) {
    const h = A.h, l = A.l, v = A.v;
    let ct = null;
    for (let j = end - conf; j > Math.max(end - conf - maxAge, conf); j--) {
      if (h[j] >= h[j - 1]) {
        let all = true;
        for (let k = 1; k <= conf; k++) if (!(h[j] >= h[j + k])) { all = false; break; }
        if (all) { ct = j; break; }
      }
    }
    if (ct === null) return null;
    const top = h[ct];
    let cf = null;
    for (let j = ct + 1; j <= end - conf; j++) {
      let all = true;
      for (let k = 1; k <= conf; k++) if (!(l[j] <= l[j + k])) { all = false; break; }
      if (all) { cf = j; break; }
    }
    if (cf === null) return null;
    const bot = l[cf];
    if (bot <= 0 || top <= bot) return null;
    if (nanmax(h, ct + 1, end) > top) return null;
    if (nanmin(l, cf, end) < bot) return null;
    const pct = (top - bot) / bot;
    if (pct < minPct || pct > maxPct) return null;
    const dry = (ok(vol50) && vol50 > 0) ? nanmean(v, ct, end) / vol50 : 1.0;
    return { bk: Math.max(end - ct, conf), piv: top, blo: bot, tight: pct, contr: pyRound(Math.min(pct / maxPct, 1.0), 2),
      dry: (ok(vol50) && vol50 > 0) ? npRound(dry, 2) : 1.0, type: "DarvasBox", k: { t: "py", c: "py", p: "py", b: "py" }, note: "box " + pyRound(pct * 100, 0) + "%", g: { kind: "darvas", a: ct, b: end, f: cf } };
  }

  function pocketPivot(A, end, c, vol50, maxExt) {
    const cl = A.c, lo = A.l, vv = A.v, lookback = 10;
    if (end < lookback + 1) return null;
    if (cl[end] <= cl[end - 1]) return null;
    let thr = 0.0, any = false;
    for (let j = end - lookback; j < end; j++) if (cl[j] < cl[j - 1]) { if (!any || vv[j] > thr) thr = vv[j]; any = true; }
    if (!any) thr = 0.0;
    if (!(vv[end] > thr)) return null;
    const ma10 = nanmean(cl, end - 9, end);
    if (ma10 <= 0) return null;
    if (!((lo[end] <= ma10 && ma10 <= c) || Math.abs((c - ma10) / ma10) <= maxExt)) return null;
    const dayrange = c > 0 ? (c - lo[end]) / c : 0;
    if (dayrange <= 0) return null;
    const volratio = thr > 0 ? vv[end] / thr : 2.0;
    return { bk: 1, piv: npRound(c, 2), blo: pyRound(lo[end], 2), tight: dayrange, contr: 0.5,
      dry: (ok(vol50) && vol50 > 0) ? npRound(thr / vol50, 2) : 1.0, type: "PocketPivot", k: { t: "np", c: "py", p: "np", b: "py" },
      note: "vol " + pyRound(volratio, 1).toFixed(1) + "x", g: { kind: "pp", a: end, b: end, ma10, thr } };
  }

  function episodicPivot(A, end, vol50, moveMin, gapMin, volMin, dormWin, dormMax) {
    const o = A.o, cl = A.c, hi = A.h, lo = A.l, vv = A.v, volLookback = 10;
    if (end < dormWin + 5) return null;
    const pc = cl[end - 1];
    if (pc <= 0 || !(ok(vol50) && vol50 > 0)) return null;
    const c = cl[end], H = hi[end], L = lo[end];
    const move = c / pc - 1.0, gap = o[end] / pc - 1.0, volr = vv[end] / vol50, rng = H - L;
    if (rng <= 0 || c <= 0) return null;
    const closePos = (c - L) / rng;
    if (move < moveMin) return null;
    if (volr < volMin) return null;
    if (closePos < 0.5) return null;
    if (gap < gapMin && move < moveMin * 1.5) return null;
    if (vv[end] < nanmax(vv, end - volLookback, end - 1)) return null;
    const base0 = cl[end - 1 - dormWin];
    const preRun = base0 > 0 ? (pc / base0 - 1.0) : 0.0;
    if (preRun > dormMax) return null;
    const t = new Float64Array(dormWin);
    for (let j = 0; j < dormWin; j++) { const k = end - dormWin + j, d = cl[k] > 0 ? cl[k] : NaN; t[j] = (hi[k] - lo[k]) / d; }
    const preAdr = nanmean(t, 0, dormWin - 1);
    const note = gap >= 0.01
      ? `gap +${pyRound(gap * 100, 0)}% · +${pyRound(move * 100, 0)}% · ${pyRound(volr, 1).toFixed(1)}x vol`
      : `+${pyRound(move * 100, 0)}% · ${pyRound(volr, 1).toFixed(1)}x vol`;
    return { type: "EpisodicPivot", piv: pyRound(H, 2), blo: pyRound(L, 2), bk: dormWin, tight: rng / c, contr: preRun,
      dry: preAdr, gap, move, volr, close_pos: closePos, note, g: { kind: "ep", a: end - dormWin, b: end, e: end } };
  }

  // ---------- the scanner: vcp_core.analyze_vcp on bar i (bars after i are never read) ----------
  const DEFAULTS = {
    tf: "Daily", near_high_pct: 0.12, max_tight: 0.05, min_base: 3, strictness: "Strict", nifty_mom_ret: 0.0,
    low_dist_on: true, low_dist_min: 30.0, low_dist_max: null,
    wedge_on: false, wedge_slope_min: 0.05, wedge_slope_max: 0.80,
    htf_on: false, htf_thrust_min: 0.80, htf_flag_max: 0.25,
    cup_on: false, cup_min_depth: 0.12, cup_max_depth: 0.40, cup_handle_max: 0.15,
    darvas_on: false, darvas_min_pct: 0.03, darvas_max_pct: 0.40,
    pp_on: false, pp_max_ext: 0.05,
    ep_on: false, ep_move_min: 0.10, ep_gap_min: 0.05, ep_vol_min: 3.0, ep_dorm_max: 0.30,
    short_history: false
  };

  function options(opt) { const o = Object.assign({}, DEFAULTS, opt || {}); o.__full = true; return o; }

  function analyze(A, i, opt) {
    const o = (opt && opt.__full) ? opt : options(opt);
    const tf = o.tf;
    let p = tfParams(tf);
    const n = i + 1;
    const fullNeed = Math.max(p.mal, p.win) + 5;
    let short = false, roffF = 10, roffL = 20;
    if (n < fullNeed) {
      const floor = tf !== "Weekly" ? 60 : 40;
      if (!o.short_history || n < floor) return null;
      short = true;
      const scale = (n - 5) / Math.max(p.mal, p.win);
      p = Object.assign({}, p);
      for (const k of ["maf", "mam", "mal", "win", "mom", "funnel", "epw"]) p[k] = Math.max(3, pyRound(p[k] * scale));
      p.mam = Math.max(p.mam, p.maf + 1);
      p.mal = Math.max(p.mal, p.mam + 1);
      p.win = Math.max(p.win, p.mal);
      roffF = Math.max(1, pyRound(10 * scale)); roffL = Math.max(1, pyRound(20 * scale));
    }
    const C = A.c, c = C[i];
    const MAF = smaOf(A, "c", p.maf), MAM = smaOf(A, "c", p.mam), MAL = smaOf(A, "c", p.mal), V50 = smaOf(A, "v", 50);
    const maf = MAF[i], mam = MAM[i], mal = MAL[i];
    if (!(ok(c) && ok(maf) && ok(mam) && ok(mal)) || c <= 0) return null;
    const vol50 = V50[i];
    const geo = (g, extra) => Object.assign({ i, short, maf: p.maf, mam: p.mam, mal: p.mal, win: p.win }, g, extra || {});
    const nret = o.nifty_mom_ret || 0.0;

    if (o.ep_on) {
      const ep = episodicPivot(A, i, vol50, o.ep_move_min, o.ep_gap_min, o.ep_vol_min, p.epw, o.ep_dorm_max);
      if (ep) {
        const hi52 = nanmax(A.h, i - p.win + 1, i), lo52 = nanmin(A.l, i - p.win + 1, i);
        const nh = hi52 > 0 ? (hi52 - c) / hi52 : 0.0;
        const dl = (ok(lo52) && lo52 > 0) ? (c / lo52 - 1.0) * 100.0 : null;
        const mom = p.mom, sret = (i - mom >= 0 && C[i - mom] > 0) ? (c / C[i - mom] - 1) : 0.0;
        const rs = sret - nret;
        const parts = [25 * clip01(ep.move / 0.20), 25 * clip01(ep.volr / 6.0), 15 * clip01(Math.max(ep.gap, 0) / 0.12),
          15 * clip01(1 - ep.contr / Math.max(o.ep_dorm_max, 1e-9)), 20 * clip01(ep.close_pos)];
        const sc = pyRound(parts[0] + parts[1] + parts[2] + parts[3] + parts[4]);
        const gr = sc >= 75 ? "A" : sc >= 60 ? "B" : "C";
        return {
          close: npRound(c, 2), status: "Breakout", grade: gr, score: sc,
          base_len: ep.bk, tightness: npRound(ep.tight * 100, 1), contraction: npRound(ep.contr, 2), dryup: pyRound(ep.dry, 2),
          near_high: npRound(nh * 100, 1), low_dist: dl !== null ? npRound(dl, 1) : null, rs: npRound(rs * 100, 1),
          pivot: ep.piv, stop: ep.blo, dist_pivot: npRound((ep.piv - c) / c * 100, 2), vol_surge: npRound(ep.volr, 2),
          target: npRound(c + 2 * (c - ep.blo), 2), base_type: "EpisodicPivot", slope: null, pole: null, note: ep.note,
          short_hist: short, g: geo(ep.g, { gap: ep.gap, move: ep.move, volr: ep.volr, cp: ep.close_pos, sc: parts, v50: vol50, hi52, lo52 })
        };
      }
    }
    const mafRising = maf > MAF[i - roffF], malRising = mal > MAL[i - roffL];
    if (o.strictness === "Strict") {
      if (!(c > maf && maf > mam && mam > mal && malRising)) return null;
    } else if (o.strictness === "Relaxed") {
      if (!(c > mam && maf > mam && mafRising)) return null;
    } else {
      if (!(c > maf && c > mam && c > mal && maf > mam && mafRising)) return null;
    }
    const hi52 = nanmax(A.h, i - p.win + 1, i), lo52 = nanmin(A.l, i - p.win + 1, i);
    const nh = (hi52 - c) / hi52;
    if (nh > o.near_high_pct) return null;
    const distLow = (ok(lo52) && lo52 > 0) ? (c / lo52 - 1.0) * 100.0 : null;
    if (o.low_dist_on && distLow !== null) {
      if (distLow < o.low_dist_min) return null;
      if (o.low_dist_max !== null && o.low_dist_max !== undefined && distLow > o.low_dist_max) return null;
    }
    const volSurge = (ok(vol50) && vol50 > 0) ? A.v[i] / vol50 : 0;
    const F = p.funnel;
    let status = null, base = null;
    const co = flatBase(A, i, c, o.max_tight, o.min_base, F, vol50);
    if (co && c <= co.piv * 1.001 && c >= co.piv * (1 - 0.06)) { status = "Coiling"; base = co; }
    else {
      const bo = flatBase(A, i - 1, c, o.max_tight, o.min_base, F, vol50);
      if (bo && c > bo.piv && volSurge >= 2.5) { status = "Breakout"; base = bo; }
    }
    let baseType = "Flat", slope = null, pole = null, note = null;
    if (base === null && o.wedge_on) {
      const wc = wedgeBase(A, i, c, o.max_tight, o.min_base, o.wedge_slope_min, o.wedge_slope_max, vol50);
      if (wc && c <= wc.piv * 1.001 && c >= wc.piv * (1 - 0.06)) { status = "Coiling"; base = wc; }
      else {
        const wb = wedgeBase(A, i - 1, c, o.max_tight, o.min_base, o.wedge_slope_min, o.wedge_slope_max, vol50);
        if (wb && c > wb.piv && volSurge >= 2.5) { status = "Breakout"; base = wb; }
      }
      if (base !== null) { baseType = base.type; slope = base.slope; }
    }
    if (base === null && o.htf_on) {
      const hc = htfBase(A, i, c, vol50, o.htf_thrust_min, o.htf_flag_max);
      if (hc && c <= hc.piv * 1.001 && c >= hc.piv * (1 - 0.08)) { status = "Coiling"; base = hc; }
      else {
        const hb = htfBase(A, i - 1, c, vol50, o.htf_thrust_min, o.htf_flag_max);
        if (hb && c > hb.piv && volSurge >= 2.5) { status = "Breakout"; base = hb; }
      }
      if (base !== null) { baseType = "HiTightFlag"; pole = base.pole === undefined ? null : base.pole; }
    }
    if (base === null && o.cup_on) {
      const wk = tf === "Weekly";
      const [hmn, hmx, cmn, cmx] = wk ? [2, 8, 6, 45] : [3, 25, 18, 130];
      const cc = cupHandle(A, i, c, vol50, o.cup_min_depth, o.cup_max_depth, o.cup_handle_max, hmn, hmx, cmn, cmx);
      if (cc && c <= cc.piv * 1.001 && c >= cc.piv * (1 - 0.06)) { status = "Coiling"; base = cc; }
      else {
        const cb = cupHandle(A, i - 1, c, vol50, o.cup_min_depth, o.cup_max_depth, o.cup_handle_max, hmn, hmx, cmn, cmx);
        if (cb && c > cb.piv && volSurge >= 2.5) { status = "Breakout"; base = cb; }
      }
      if (base !== null) { baseType = "CupHandle"; note = base.note === undefined ? null : base.note; }
    }
    if (base === null && o.darvas_on) {
      const dc = darvasBox(A, i, c, vol50, 3, 60, o.darvas_min_pct, o.darvas_max_pct);
      if (dc && c <= dc.piv * 1.001 && c >= dc.piv * (1 - 0.06)) { status = "Coiling"; base = dc; }
      else {
        const db = darvasBox(A, i - 1, c, vol50, 3, 60, o.darvas_min_pct, o.darvas_max_pct);
        if (db && c > db.piv && c <= db.piv * 1.04 && volSurge >= 2.5) { status = "Breakout"; base = db; }
      }
      if (base !== null) { baseType = "DarvasBox"; note = base.note === undefined ? null : base.note; }
    }
    if (base === null && o.pp_on) {
      const pp = pocketPivot(A, i, c, vol50, o.pp_max_ext);
      if (pp) { status = "Breakout"; base = pp; baseType = "PocketPivot"; note = pp.note; }
    }
    if (base === null) return null;
    const mom = p.mom, sret = (i - mom >= 0 && C[i - mom] > 0) ? (c / C[i - mom] - 1) : 0.0;
    const rs = sret - nret;
    const tightRef = baseType === "HiTightFlag" ? o.htf_flag_max : baseType === "CupHandle" ? o.cup_handle_max
      : baseType === "DarvasBox" ? o.darvas_max_pct : o.max_tight;
    const sTight = 14 * Math.max(0, 1 - base.tight / tightRef);
    const sContr = 12 * clip01(1 - base.contr);
    const sDry = 10 * clip01((1 - base.dry) / 0.5);
    const sNear = 18 * Math.max(0, 1 - nh / o.near_high_pct);
    const sBase = 8 * clip01((base.bk - o.min_base) / 8);
    const sRs = 18 * clip01(0.5 + rs / 0.5);
    const sSurge = status === "Breakout"
      ? 10 * ((2.5 <= volSurge && volSurge <= 4.0) ? 1.0 : (volSurge > 1.5 ? 0.5 : 0.0))
      : 10 * clip01((1 - base.dry) / 0.5);
    const sTrend = 10;
    const score = pyRound(sTight + sContr + sDry + sNear + sBase + sRs + sSurge + sTrend);
    const grade = score >= 75 ? "A" : score >= 60 ? "B" : "C";
    const K = base.k;
    return {
      close: npRound(c, 2), status, grade, score,
      base_len: Math.trunc(base.bk), tightness: RND(K.t, base.tight * 100, 1), contraction: RND(K.c, base.contr, 2),
      dryup: npRound(base.dry, 2), near_high: npRound(nh * 100, 1), low_dist: distLow !== null ? npRound(distLow, 1) : null,
      rs: npRound(rs * 100, 1), pivot: RND(K.p, base.piv, 2), stop: RND(K.b, base.blo, 2),
      dist_pivot: npRound((base.piv - c) / c * 100, 2), vol_surge: npRound(volSurge, 2),
      target: npRound(c + 2 * (c - base.blo), 2), base_type: baseType, slope, pole, note, short_hist: short,
      g: geo(base.g, { vs: volSurge, hi52, lo52, v50: vol50, sc: [sTight, sContr, sDry, sNear, sBase, sRs, sSurge, sTrend],
        ma: [maf, mam, mal, MAF[i - roffF], MAL[i - roffL]], roff: [roffF, roffL] })
    };
  }

  // weekly bars from daily bars, like upstox_data.to_weekly (pandas resample W-FRI: week ends on Friday)
  function toWeekly(dates, bars) {
    const out = { d: [], o: [], h: [], l: [], c: [], v: [] };
    let key = null;
    for (let j = 0; j < dates.length; j++) {
      const t = new Date(dates[j] + "T00:00:00Z"), dow = t.getUTCDay();
      const add = (5 - dow + 7) % 7, fri = new Date(t.getTime() + add * 864e5).toISOString().slice(0, 10);
      if (fri !== key) {
        key = fri; out.d.push(fri); out.o.push(bars.o[j]); out.h.push(bars.h[j]); out.l.push(bars.l[j]);
        out.c.push(bars.c[j]); out.v.push(bars.v[j]);
      } else {
        const k = out.d.length - 1;
        out.h[k] = Math.max(out.h[k], bars.h[j]); out.l[k] = Math.min(out.l[k], bars.l[j]);
        out.c[k] = bars.c[j]; out.v[k] += bars.v[j];
      }
    }
    return out;
  }

  // screener_core.clean_df: last bar per date, positive OHLC, high/low clamped to open/close, no bar wider than 50% of close
  function cleanBars(B) {
    const keep = [], seen = new Map();
    for (let j = 0; j < B.d.length; j++) seen.set(B.d[j], j);            // keep="last"
    const out = { d: [], o: [], h: [], l: [], c: [], v: [] };
    for (let j = 0; j < B.d.length; j++) {
      if (seen.get(B.d[j]) !== j) continue;
      const o = B.o[j], h = B.h[j], l = B.l[j], c = B.c[j];
      if (!(o > 0 && h > 0 && l > 0 && c > 0)) continue;
      const hh = Math.max(h, o, c), ll = Math.min(l, o, c);
      if (!((hh - ll) <= 0.50 * c)) continue;
      out.d.push(B.d[j]); out.o.push(o); out.h.push(hh); out.l.push(ll); out.c.push(c); out.v.push(B.v[j]);
    }
    return out;
  }

  const API = { analyze, options, prepare, tfParams, rollMean, pyRound, npRound, DEFAULTS, toWeekly, cleanBars, _int: { pw, nanmean, fit, tightBase, flatBase } };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  else root.VCPE = API;
})(typeof window !== "undefined" ? window : this);
