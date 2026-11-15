"""Themes: which stocks belong to each investment theme, built from the master classification
(config/classification_master.csv, read by classify.py) the way index providers build thematic indices:

  * a theme takes every company whose master SECTOR or INDUSTRY is the theme's core business, and
  * a short, named list of companies from other industries with a large business in the theme
    (e.g. Havells in Wires & Cables, Bharat Forge in Defence), then
  * named exclusions where a label does not fit the theme (each reviewed by hand, reason given).

compute.py calls build() every day, so a new listing joins its themes as soon as the master file has it.
config/themes.csv is the same lists written out (used only when the master file is missing).
"""
# theme = (sectors, industries, add symbols, drop symbols)
# a stock joins when its master SECTOR is in sectors, or its master INDUSTRY is in industries, or it is in add;
# then drop removes reviewed mistakes.
T = {}
def th(name, sec=(), ind=(), add=(), drop=()):
    T[name] = dict(sec=set(sec), ind=set(ind), add=set(add.split() if isinstance(add, str) else add),
                   drop=set(drop.split() if isinstance(drop, str) else drop))

th("Wires & Cables", sec=["Cables"], ind=["Cables Power", "Cables Telecom", "Cables Telephone", "Copper Wires"],
   add="HAVELLS")
th("Data Centres & Cloud", ind=["Data Centre"], add="RAILTEL TATACOMM BHARTIARTL")
th("Defence", sec=["Aerospace and Defence", "Ship Building"],
   ind=["Aerospace and Defence Equipment", "Industrial Explosives", "Shipbuilding and Repairs", "Shipyards Dockrepairing"],
   add="HBLENGINE BHARATFORG")
th("Jewellery & Gold", sec=["Diamond Gems and Jewellery"], ind=["Lab Grown Diamonds", "Finance and Investments Gold Loan"])
th("EMS / Electronics Manufacturing", ind=["EMS"], add="ELIN IKIO NETWEB")
th("Nuclear Power", add="NTPC BHEL LT WALCHANNAG MTARTECH HCC TATAPOWER KSB AZAD")
th("Drones & Space", add="IDEAFORGE ZENTEC DCXINDIA PARAS ASTRAMICRO MTARTECH APOLLO CENTUM AVANTEL DATAPATTNS")
th("Shipbuilding & Maritime", sec=["Ship Building", "Shipping", "Marine Port and Services"],
   ind=["Shipbuilding and Repairs", "Shipyards Dockrepairing", "Shipping", "Shipping and Dredging", "Marine Port and Services"],
   add="SWANCORP")
th("CDMO / CRDMO", ind=["Pharma CRAMS"], add="COHANCE GLAND JUBLPHARMA AARTIPHARM")
th("Sugar & Ethanol", sec=["Sugar"], ind=["Sugar", "Sugar Integrated", "Sugar Others", "Biofuel"], add="PRAJIND")
th("Capital Markets", sec=["Stock and Commodity Brokers", "Financial Services"],
   ind=["Exchanges", "Capital Markets RTA", "Finance Capital Markets", "Finance Capital Markets Brokers",
        "Finance Capital Markets Wealth Management", "Finance AMC", "NBFC Asset Management Companies",
        "Securities and Commodities Trading Services", "Finance Investment Bankers"])
th("Railways", sec=["Railways"], ind=["Railways", "Railways Kavach and Springs"], add="RVNL IRCON CONCOR BEML RKFORGE")
th("Travel & Hospitality", ind=["Hotels", "Hotels Resorts", "Resorts", "Airport Restaurants and Lounges", "E Commerce Platform Travel",
                                "Travel Agencies", "Transport Airlines", "Air Transport Service", "Amusement Parks"],
   sec=["Air Transport Service"], add="IRCTC TBOTEK INDIGO")
th("QSR & Restaurants", ind=["Quick Service Restaurant"])
th("Power T&D", ind=["Power Transmission and Equipment", "Capital Goods Transformers", "Electrical Equipment and HVDC",
                     "Transmission Line Towers and Equipment", "Capital Goods Switchgear", "Electrical Switchgear Relays and Circuits"],
   add="KPIL SIEMENS ABB APARINDS CGPOWER GENUSPOWER")
th("Internet & New-Age Tech", sec=["E Commerce and App based Aggregator"],
   ind=["New age Platform E Retail", "Platform Others", "Platform Matrimony", "Platform Education", "E Commerce Platform Food",
        "E Commerce Platform Travel", "E Commerce Platform Utility", "Insurance Proxy", "Digital Gifting and Rewards", "E Services"],
   add="MAPMYINDIA DELHIVERY NAZARA ZAGGLE AFFLE")
th("Semiconductors (India)", add="MOSCHIP CGPOWER KAYNES SPELS RIR TATAELXSI")
th("Water & Sanitation", ind=["Water Treatment", "Building Materials Plastic Pipes", "Plastics Pipes and Fittings", "Plastics Pipes",
                              "DI Pipes and Saw Pipes", "Pumps", "Solar Pumps", "Irrigation System", "Plastics Drip Irrigation"],
   add="EIEL EMSLIMITED THERMAX JASH")
th("Private Banks", ind=["Private Banks"])
th("Building Materials", sec=["Ceramic Products", "Plywood Boards and Laminates", "Paints and Varnish", "Cement Products"],
   ind=["Building Materials Plastic Pipes", "Plastics Pipes and Fittings", "Plastics Pipes", "Ceramics Tiles",
        "Ceramics Tiles and Sanitaryware", "Plywood Boards and Laminates", "Decoratives Wood based", "Laminates",
        "Building Materials Paints", "Granite and Marble", "Cement Products", "Building Material USA"],
   add="PIDILITIND APLAPOLLO HINDWAREAP")
th("Hospitals & Diagnostics", ind=["Hospitals", "Hospitals and Medical Services", "Diagnostic Services", "Medical Equipment",
                                   "Medical Equipment and Diagnostic Technology"])
th("EV & Batteries", ind=["Auto Batteries"],
   add="OLAELEC ATHERENERG TMPV M&M BAJAJ-AUTO TVSMOTOR HEROMOTOCO OLECTRA JBMA SONACOMS UNOMINDA HBLENGINE GREAVESCOT EXICOM")
th("Infra EPC", sec=["Infrastructure Developers and Operators"],
   ind=["Construction Civil and Turnkey", "Infra Construction and Contracting", "Construction and Contracting", "EPC",
        "Engineering Turnkey Services", "Infra Engineering General", "Infra General", "Project Consultancy and Turnkey",
        "Infra Power Generation and Distribution"])
th("Renewable Energy", sec=["Power Infrastructure"], ind=["Capital Goods Solar", "Solar EPC", "Solar Power and EPC", "Solar Pumps"],
   add="ADANIGREEN NTPCGREEN SUZLON INOXWIND TATAPOWER JSWENERGY ACMESOLAR KPIGREEN BORORENEW INOXGREEN IREDA GREENPOWER "
       "EMMVEE SAATVIKGL INA")
th("PSU Banks", ind=["PSU Banks"])
th("NBFC & Lending", ind=["Conglomerate Backed NBFC", "Finance Housing", "Finance PSU Lending", "Finance and Investments CV Finance",
                          "Finance and Investments Gold Loan", "Finance and Investments MSME Lending",
                          "Finance and Investments Microfinance", "Finance Credit Cards", "NBFC Others", "Retail Lending NBFC"],
   add="BAJAJFINSV")
th("Insurance", sec=["Insurance"], ind=["Finance Insurance", "Finance Non Life Insurance", "Insurance Distribution"], add="MFSL")
th("IT Services", ind=["IT Services", "Engineering R and D", "IT Enabled Services", "IT Enabled Services and BPO", "IT Product Companies"])
th("Pharma", ind=["Pharma API", "Pharma Bulk Drugs", "Pharma CRAMS", "Pharma Formulations", "Pharma Integrated", "Pharma MNC Bulk Drugs",
                  "Pharma Others", "Pharma IV Fluids", "Pharma Gelatin Capsules", "Pharma Animal", "Biotechnology"])
th("Specialty Chemicals", ind=["Specialty Chemicals", "Chemicals Fluorine", "Chemicals Organic", "Dyes and Pigments", "Dyes Intermediate",
                               "Chemicals Organic Alcohol Based", "Chemicals Organic Maleic Anhydride"],
   add="PIIND DEEPAKNTR NOCIL")
th("Agrochem & Fertilisers", sec=["Agro Chemicals", "Fertilizers"],
   ind=["Pesticides and Agrochemicals", "Fertilisers", "Fertilizers Nitrogenous and Phosphatic", "Phosphatic Fertilizers Single Super Phosphate"])
th("Auto Ancillaries", sec=["Auto Ancillaries"], add="SONACOMS BHARATFORG SCHAEFFLER TIINDIA")
th("Tyres", sec=["Tyres"], ind=["Tyres and Tubes"])
th("Cement", ind=["Cement"], sec=["Cement"])
th("Metals & Mining", sec=["Steel", "Non Ferrous Metals", "Mining and Mineral Products", "Ferro Alloys", "Aluminium"],
   ind=["Mining and Minerals", "Mining and Minerals Iron Ore", "Aluminium", "Metals", "Steel", "Stainless Steel"], add="APLAPOLLO")
th("Real Estate", sec=["Realty"], ind=["Realty National", "Realty Regional", "Realty Commercial"])
th("FMCG", sec=["FMCG", "Tobacco Products", "Alcoholic Beverages"],
   ind=["FMCG Personal Care", "Personal Care", "Cigarettes and Tobacco Products", "FMCG Foods", "FMCG Dairy Products"],
   add="VBL AWL TATACONSUM")
th("Consumer Durables", sec=["Consumer Durables"], ind=["Consumer Electronics", "Domestic Appliances"], add="HAVELLS VGUARD")
th("Textiles & Apparel", sec=["Textiles", "Readymade Garments and Apparel"])
th("Logistics", sec=["Logistics", "Marine Port and Services"],
   ind=["Logistics", "Logistics Warehousing and Supply Chain", "Transport Road", "Marine Port and Services"],
   add="CONCOR")
th("Telecom & Media", sec=["Telecom Service", "Telecom Equipment and Infra Services", "Entertainment", "Media Print and Television and Radio"],
   ind=["Telecom Services", "Telecommunications Equipment", "Telecommunications Equipment and Network EPC", "Cables Telecom",
        "Entertainment Content Providers", "Entertainment Electronic Media", "Entertainment and Media", "Music Licensing", "Newspaper"],
   add="STLTECH")
th("Oil & Gas", sec=["Crude Oil and Natural Gas", "Refineries", "Gas Distribution", "Oil Drill and Allied"],
   ind=["Oil Drilling and Exploration", "Oil Exploration and Allied Services", "Refineries", "Gas Distribution", "Lubricants",
        "LPG Bottling"], add="AEGISLOG")
th("Power Utilities", sec=["Power Generation and Distribution"],
   ind=["Power Generation and Distribution", "Power Generation and Supply"], add="POWERGRID IEX PTC")
th("Capital Goods & Industrials", sec=["Capital Goods Electrical Equipment", "Capital Goods Non Electrical Equipment", "Bearings",
                                       "Engineering", "Castings Forgings and Fasteners"], add="LT")
# new, well-defined groups
th("Small Finance Banks", ind=["Small Finance Banks"])
th("Housing Finance", ind=["Finance Housing"])
th("Paper & Packaging", sec=["Paper", "Packaging"])
th("Alcoholic Beverages", sec=["Alcoholic Beverages"], ind=["Alcoholic Beverages", "Breweries"])
th("Education", sec=["Education", "Computer Education"], ind=["Computer Education", "IT Education", "Platform Education"])

# ---- reviewed corrections (member-by-member review)
def _drop(name, syms): T[name]["drop"] |= set(syms.split())
def _unadd(name, syms): T[name]["add"] -= set(syms.split())
_drop("Defence", "HRYNSHP")                                   # ship breaking, not defence
_unadd("Shipbuilding & Maritime", "SWANCORP")                 # Swan's shipyard is now listed on its own (SWANDEF)
_drop("Capital Markets", "MIIL")                              # a realty company
_drop("Travel & Hospitality", "RAYMOND JETFREIGHT")           # realty/engineering; air-freight logistics
_drop("Internet & New-Age Tech", "MEDIASSIST CORDELIA THOMASCOOK")   # TPA, cruise line, offline travel agency
_drop("Building Materials", "GPTINFRA")                       # railway sleepers / infra contractor
_drop("Infra EPC", "NIRLON MAHLIFE MODIS BLAL SOMATEX")       # property owners / developers, not contractors
_drop("Auto Ancillaries", "FRONTSP")                          # railway springs
_drop("Metals & Mining", "INTERARCH PENIND EPACKPEB")         # pre-engineered buildings
_drop("Real Estate", "PFOCUS AHLUCONT")                       # VFX studio; building contractor
_drop("FMCG", "KSCL OSWALSEEDS BSHSL INDOUS NATHBIOGEN MSL AGRITECH")  # seeds and tissue culture (farm inputs)
_drop("Consumer Durables", "MIDWESTLTD GSLSU PACIFICI AROGRANITE MADHAV CARYSIL POKARNA GENUSPOWER HIRECT RIR MICEL")
_drop("Textiles & Apparel", "WAKEFIT JINDALPOLY")             # mattresses; BOPP film
_drop("Logistics", "MEESHO")                                  # e-commerce marketplace
_drop("Telecom & Media", "WONDERLA IMAGICAA NICCOPAR")        # amusement parks (in Travel & Hospitality)
_drop("Power Utilities", "ENRIN BHAGYANGR")                   # equipment maker; copper/recycling
_drop("Education", "SCILAL")                                  # SCI Land & Assets (land holding company)
T["Cement"]["ind"] = set()                                    # cement makers only (an AAC-block maker carries the label)
_drop("Telecom & Media", "FINCABLES NILASPACES")              # mostly electrical cables; a realty company


def build(sec, ind, symbols):
    """-> {theme: [symbols]} for the given stocks. sec, ind: pandas Series indexed by symbol (master labels)."""
    out = {}
    syms = list(symbols)
    for name, r in T.items():
        m = [s for s in syms if (sec.get(s) in r["sec"]) or (ind.get(s) in r["ind"]) or (s in r["add"])]
        out[name] = [s for s in m if s not in r["drop"]]
    return out
