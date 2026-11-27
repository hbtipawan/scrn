"""Test of the group labels shown on the Rotation tab (update 20). Writes config/group_label_evidence.json.

A group's label comes from two numbers the site already has: its RS rating today (1-99, ranked against the other
groups of its kind) and the change in that rating over the last 20 sessions (about 4 weeks):

  Leading    rating 70+, change 0 or more          Improving  rating 40-69, change +10 or more
  Holding    rating 70+, change -1 to -10          Middle     rating 40-69, change -9 to +9
  Fading     rating 70+, change -11 or worse       Slipping   rating 40-69, change -10 or worse
  Igniting   rating under 40, change +10 or more   Lagging    rating under 40, change under +10

Test: every 5th session with a full year of history behind it and 63 sessions after it, each group's index return
over the next 21 and 63 sessions minus the median group of the same kind on that day. Data: the site's own group
index files (docs/data/grp/*.json), built from today's membership, so the numbers are tendencies, not trades.

Run after a daily update:  python scripts/test_group_labels.py
"""
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GRP = ROOT / "docs" / "data" / "grp"
OUT = ROOT / "config" / "group_label_evidence.json"
ORDER = ["Leading", "Holding", "Fading", "Improving", "Middle", "Slipping", "Igniting", "Lagging"]


def label(rk, d4):
    return np.select([(rk >= 70) & (d4 >= 0), (rk >= 70) & (d4 >= -10), rk >= 70,
                      (rk >= 40) & (d4 >= 10), (rk >= 40) & (d4 <= -10), rk >= 40, d4 >= 10],
                     ["Leading", "Holding", "Fading", "Improving", "Slipping", "Middle", "Igniting"], "Lagging")


def dataset(u):
    cal = json.loads((GRP / "_common.json").read_text())["dates"]
    T = len(cal)
    recs = []
    for f in glob.glob(str(GRP / "*.json")):
        if f.endswith("_common.json"):
            continue
        g = json.loads(Path(f).read_text())
        x = g.get(u)
        if not x:
            continue
        i0 = g["i0"]
        c, rk = np.full(T, np.nan), np.full(T, np.nan)
        cc = np.array([np.nan if v is None else v for v in x["c"]], float)
        rr = np.array([np.nan if v is None else v for v in x["rk"]], float)
        c[i0:i0 + len(cc)], rk[i0:i0 + len(rr)] = cc, rr
        for t in range(260, T - 63, 5):
            if np.isnan(rk[t]) or np.isnan(rk[t - 20]) or np.isnan(c[t]) or np.isnan(c[t + 63]) or np.isnan(c[t + 21]):
                continue
            recs.append((cal[t], g["k"], rk[t], rk[t] - rk[t - 20], c[t + 21] / c[t] - 1, c[t + 63] / c[t] - 1))
    df = pd.DataFrame(recs, columns=["d", "k", "rk", "d4", "f21", "f63"])
    for h in ("f21", "f63"):
        df["x" + h[1:]] = df[h] - df.groupby(["d", "k"])[h].transform("median")
    df["L"] = label(df.rk.to_numpy(), df.d4.to_numpy())
    return df


def main():
    out = {"rules": {"Leading": "RS 70+, 4-week change 0 or more", "Holding": "RS 70+, change −1 to −10",
                     "Fading": "RS 70+, change −11 or worse", "Improving": "RS 40–69, change +10 or more",
                     "Middle": "RS 40–69, change −9 to +9", "Slipping": "RS 40–69, change −10 or worse",
                     "Igniting": "RS under 40, change +10 or more", "Lagging": "RS under 40, change under +10"},
           "method": ("Every 5th session with a year of history before it, each group's index return over the next 21 and "
                      "63 sessions minus the median group of the same kind that day. Groups use today's membership and "
                      "share stocks, so read these as tendencies."), "u": {}}
    for u in ("l", "a"):
        df = dataset(u)
        if df.empty:
            continue
        half = np.where(df.d < "2024-01-01", "a", "b")
        res = {}
        for lab in ORDER:
            g = df[df.L == lab]
            if not len(g):
                continue
            res[lab] = {"n": int(len(g)), "x21": round(float(g.x21.mean() * 100), 2), "x63": round(float(g.x63.mean() * 100), 2),
                        "med63": round(float(g.x63.median() * 100), 2), "beat63": round(float((g.x63 > 0).mean() * 100), 1),
                        "x63_a": round(float(g.x63[half[df.L == lab] == "a"].mean() * 100), 2),
                        "x63_b": round(float(g.x63[half[df.L == lab] == "b"].mean() * 100), 2)}
        out["u"][u] = res
        out["from"], out["to"] = str(df.d.min()), str(df.d.max())
        out["split"] = "2024-01-01"
    OUT.write_text(json.dumps(out, indent=1))
    for u, r in out["u"].items():
        print(u, {k: (v["x63"], v["beat63"]) for k, v in r.items()})


if __name__ == "__main__":
    main()
