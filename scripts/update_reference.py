"""Refresh reference files: sector classification and NSE index memberships.

Source: niftyindices.com constituent CSVs (official, free, reachable from cloud servers).
Writes:
  config/sectors.csv  -> Symbol, Company, Sector   (Nifty Total Market = ~750 stocks)
  config/indices.csv  -> Index, Symbols            (sectoral + thematic NSE indices)

If a download fails, the existing file is kept, so the daily job never breaks on this step.
Run:  python scripts/update_reference.py
"""
import io
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"
BASE = "https://niftyindices.com/IndexConstituent/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Universe for sector labels
SECTOR_SOURCES = ["ind_niftytotalmarket_list.csv", "ind_niftymicrocap250_list.csv"]

# Display name -> file. Equal-weight of constituents is shown on the site.
INDEX_FILES = {
    "Nifty Auto": "ind_niftyautolist.csv",
    "Nifty Bank": "ind_niftybanklist.csv",
    "Nifty Fin Services": "ind_niftyfinancelist.csv",
    "Nifty FMCG": "ind_niftyfmcglist.csv",
    "Nifty IT": "ind_niftyitlist.csv",
    "Nifty Media": "ind_niftymedialist.csv",
    "Nifty Metal": "ind_niftymetallist.csv",
    "Nifty Pharma": "ind_niftypharmalist.csv",
    "Nifty PSU Bank": "ind_niftypsubanklist.csv",
    "Nifty Realty": "ind_niftyrealtylist.csv",
    "Nifty Healthcare": "ind_niftyhealthcarelist.csv",
    "Nifty Consumer Durables": "ind_niftyconsumerdurableslist.csv",
    "Nifty Oil & Gas": "ind_niftyoilgaslist.csv",
    "Nifty Infra": "ind_niftyinfralist.csv",
    "Nifty Energy": "ind_niftyenergylist.csv",
    "Nifty PSE": "ind_niftypselist.csv",
    "Nifty CPSE": "ind_niftycpselist.csv",
    "Nifty Commodities": "ind_niftycommoditieslist.csv",
    "Nifty MNC": "ind_niftymnclist.csv",
    "Nifty Consumption": "ind_niftyconsumptionlist.csv",
    "Nifty Chemicals": "ind_niftychemicals_list.csv",
    "Nifty India Defence": "ind_niftyindiadefence_list.csv",
    "Nifty Capital Markets": "ind_niftycapitalmarkets_list.csv",
    "Nifty India Tourism": "ind_niftyindiatourism_list.csv",
    "Nifty India Digital": "ind_niftyindiadigital_list.csv",
    "Nifty Railways PSU": "ind_niftyindiarailwayspsu_list.csv",
    "Nifty India Manufacturing": "ind_niftyindiamanufacturing_list.csv",
    "Nifty Housing": "ind_niftyhousing_list.csv",
    "Nifty India Internet": "ind_niftyindiainternet_list.csv",
    "Nifty Cement": "ind_niftycement_list.csv",
    "Nifty Core Housing": "ind_niftycorehousing_list.csv",
    "Nifty Rural": "ind_niftyrural_list.csv",
    "Nifty Power": "ind_niftypower_list.csv",
    "Nifty Capital Goods": "ind_niftycapitalgoods_list.csv",
    "Nifty Mobility": "ind_niftymobility_list.csv",
    "Nifty New Age Consumption": "ind_niftyindianewageconsumption_list.csv",
    "Nifty IPO": "ind_niftyipo_list.csv",
    "Nifty MidSmall Healthcare": "ind_niftymidsmallhealthcare_list.csv",
    "Nifty MidSmall IT & Telecom": "ind_niftymidsmallitandtelecom_list.csv",
    # mid and small companies only: no existing group shares more than a quarter of their stocks
    "Nifty MidSmall Financial Services": "ind_niftymidsmallfinancailservice_list.csv",   # NSE's own spelling of the file
    "Nifty MidSmall India Consumption": "ind_niftymidsmallindiaconsumption_list.csv",
}


def get_csv(name):
    r = requests.get(BASE + name, headers=UA, timeout=30)
    r.raise_for_status()
    if not r.text.lstrip().startswith("Company"):
        raise ValueError(f"{name}: not a constituent CSV")
    return pd.read_csv(io.StringIO(r.text))


def main():
    CFG.mkdir(exist_ok=True)
    # Sectors
    try:
        frames = [get_csv(f) for f in SECTOR_SOURCES]
        d = pd.concat(frames).drop_duplicates("Symbol")
        d = d.rename(columns={"Company Name": "Company", "Industry": "Sector"})
        d[["Symbol", "Company", "Sector"]].sort_values("Symbol").to_csv(CFG / "sectors.csv", index=False)
        print(f"sectors.csv: {len(d)} stocks")
    except Exception as e:  # keep old file
        print(f"WARN sectors not refreshed: {e}", file=sys.stderr)

    # Indices
    rows, failed = [], []
    for name, f in INDEX_FILES.items():
        try:
            d = get_csv(f)
            rows.append((name, " ".join(d["Symbol"].astype(str))))
        except Exception as e:
            failed.append(f"{name} ({e})")
    if rows:
        old = CFG / "indices.csv"
        if failed and old.exists():  # keep previous membership for failed ones
            prev = pd.read_csv(old)
            got = {r[0] for r in rows}
            rows += [tuple(x) for x in prev.values if x[0] not in got]
        pd.DataFrame(rows, columns=["Index", "Symbols"]).to_csv(CFG / "indices.csv", index=False)
        print(f"indices.csv: {len(rows)} indices")
    if failed:
        print("WARN failed: " + "; ".join(failed), file=sys.stderr)


if __name__ == "__main__":
    main()
