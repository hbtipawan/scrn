# PKC Sector Radar

A free, ScreeningMantis-style dashboard for NSE stocks:

- **Rotation** – theme / sector / industry / NSE-index returns for Today, 1W, 1M, 3M, 6M, YTD, 1Y, with mean or median, rank change vs last week, and a click-through list of the stocks in each group. Uses **every NSE stock** by default (switch to the liquid universe with *Stocks: All / Liquid*). A **Rotation map (RRG)** view plots NSE's sector, theme and size indices against Nifty 500, week by week.
- **Group charts** – every theme, sector, NSE index and industry has its own daily index. Open a group in Rotation for a 12-month chart; tap it (or 📈) for a full-screen chart: candles with 21/50/200-day averages, members' turnover, RS line vs Nifty 500 with blue dots, % of members above their 50/200-day averages, and the group RS rating — with past signals marked and what followed. Rotation also has a **Rotation radar** (group RS rating against its 4-week change) and **Group signals** (early-rotation signals that held up in testing, plus breakouts and weakness).
- **Breadth** – every NSE main-board stock (no liquidity filter, or the liquid universe with the switch): % above 20/50/200 DMA, advance/decline and the A/D line, McClellan oscillator, 52-week highs/lows, 4% movers, one year of history. Below it, **valuation and volatility**: NSE's own P/E, P/B and dividend yield for 50 indices against their history, and India VIX.
- **RS ranking** – every stock ranked 1–99 by relative strength, with where the rating is **coming from** (▲ from 70 / ▼ from 99 over 12 weeks), a 52-week RS path, RS 4 and 12 weeks ago, and **blue dots** (RS line at a 52-week high). Filterable by sector, theme, direction, blue dot, Stage 2, Minervini trend template.
- **Stock window** – price chart, **relative strength** (RS line with every blue dot of the year + the RS rating week by week), **delivery** (NSE delivery % and value delivered for 3 months), **corporate actions** (splits, bonuses, dividends coming up), plus bases, Stage 2, results, fundamentals and mutual funds.
- **Scanners** – 99 stock scanners in 18 colour-coded groups (group signals live in Rotation): 59 technical (`scripts/scanners.py`), 4 from the RS history (`scripts/rs_history.py`), 5 from NSE delivery data (`scripts/delivery.py`), 18 from NSE filings, 6 from mutual-fund portfolios and 7 from the long-base, Stage 2 and results models, led by a **Confluence** list (stocks firing in 4+ of the 7 bullish technical groups). Every scanner opens with a collapsible **How this scanner works** panel — what it looks for, the exact rules, how traders use it, what to watch out for and the source (`scripts/scan_docs.py`). A search box finds scanners by any word in their name or write-up ("EMA", "volume", "Minervini"); Enter opens the closest match. Any scan can be limited to the top 5 or 10 themes or by Fund rating.
- **Fund flows** – what mutual funds bought and sold each month, stock by stock, from every scheme's month-end portfolio (Scanners → Fund flows).
- **Watchlists** – multiple lists, return since added, pivot/stop/target with buy-zone alerts, notes, flags, track record, import/export, phone ↔ PC sync.
- **VPCI Screener** – your Streamlit screener (`vpci/` folder, files unchanged) run every evening: Fresh Signals, Buyable, Watchlist, All Results, Ranked, G4 Pending, New Listings, Sector Leadership, Sector Rotation — for both completed weeks and the running week.

**No broker login, no API key, no password.** Prices come from Upstox's public historical-candle service, which answers without an account. Today's candle is added from NSE's official bhavcopy. Yahoo Finance is wired in as a backup.

```
GitHub Actions (6:40 PM IST, Mon–Fri, free)
   ├─ update_reference.py   sector + NSE index lists      (niftyindices.com)
   ├─ fetch_prices.py       2 years of daily candles       (Upstox → NSE bhavcopy for today; Yahoo backup)
   ├─ fetch_nse_daily.py    NSE delivery, index P/E-P/B-yield + VIX, corporate actions, holidays (config/nse/);
   │                        corrects any close that differs from NSE's official close
   ├─ compute.py            returns, RS + RS history, breadth, delivery, index data, group indices, scans → docs/data/*.json
   ├─ fetch_fundamentals.py new NSE results + shareholding (config/fund_*.csv)
   ├─ fetch_mf.py + mf_flows.py  fund portfolios, 1st–20th of each month (config/mf/)
   └─ publish docs/ to Pages → website updates itself
```

Cost: ₹0. Setup: about 20 minutes, once.

---

## Step 1 — Try it on your PC (optional, 10 minutes)

1. Install Python 3.12 from python.org (tick "Add Python to PATH").
2. Unzip this folder, e.g. to `D:\sector-radar`.
3. Double-click `run_local.bat`. It downloads all ~2,900 NSE stocks (about 6 minutes), computes everything and opens the site at http://localhost:8000.

Quick 20-stock test instead: open Command Prompt in the folder and run
```
pip install -r requirements.txt
python scripts\fetch_prices.py --limit 20
```

## Step 2 — Put it on GitHub

1. Create a free account at github.com.
2. Click **New repository** → name it `sector-radar` → choose **Private** or **Public** (see Step 3) → Create.
3. On the empty repo page click **uploading an existing file** and drag in everything from the folder. Make sure the `.github` folder goes in too (on Windows, turn on "show hidden items" if you can't see it). Commit.
4. Go to **Actions** → enable workflows if asked → **Daily update** → **Run workflow**. It takes about 10 minutes. A green tick means `docs/data` now holds fresh data.

From now on it runs by itself at 6:40 PM IST every weekday. There are no secrets to add. A private repo gets 2,000 free Action minutes a month; this uses about 250.

## Step 3 — Host the website (free)

There is nothing secret in the repo, so pick based on who may see the dashboard:

**Public, simplest (2 minutes).** Make the repo public → **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main`, folder `/docs` → Save. Your site is at `https://<your-username>.github.io/sector-radar/`. Anyone with the link can view it.

**Private, only you.** GitHub Pages needs a paid plan for private repos, so use Cloudflare Pages:
1. Free account at dash.cloudflare.com.
2. **Workers & Pages → Create → Pages → Connect to Git** → pick `sector-radar`.
3. Framework preset: **None**. Build command: empty. Build output directory: `docs`. Deploy.
4. You get a link like `sector-radar-xyz.pages.dev`. Each evening's data commit redeploys it.
5. Lock it to you: **Zero Trust → Access → Applications → Add → Self-hosted**, enter the pages.dev address, allow only your email.

## Step 4 — Edit themes

Themes live in `config/themes.csv`: one theme per row, NSE symbols separated by spaces.

```
Theme,Symbols
Wires & Cables,POLYCAB KEI FINCABLES RRKABEL HAVELLS ...
```

Edit it on GitHub (open the file → pencil icon → commit). A theme appears once 3 of its stocks pass the filters. The next daily run picks up changes; to see them immediately, run the workflow by hand.

**Sector** comes from NSE's classification of the ~750 Nifty Total Market stocks. **NSE Index** groups are equal-weighted members of 39 sectoral and thematic indices. Both refresh automatically.

## Optional — Industry for every stock and the ₹500 Cr filter

BSE blocks cloud servers, but its public company list works from a home connection and has every company's industry and market cap:

```
python scripts\pc_bse_industry.py
```

Upload the `config/industry_bse.csv` it writes to `config/` on GitHub. From the next run you get an **Industry** tab covering all stocks, and stocks below ₹500 Cr are dropped. Re-run monthly.

Without it, the universe is filtered by liquidity: price ≥ ₹20 and median daily turnover ≥ ₹1 Cr over 50 days (about 1,550 stocks).

## Watchlists

Tap **☆** next to any stock name (Rotation, RS ranking, Scanners, VPCI, stock card) to put it in one or more lists. The **Watchlists** tab then shows, per list:

- **Since added** — price and NIFTY 500 level are recorded on the day you add a stock: return since added, return vs NIFTY, days on the list, best gain and worst dip since added, 3-month sparkline. The added date/price can be edited (change the date and the price fills in from that day's close).
- **Your levels** — pivot (buy-above), stop, target, flag colour and a note. Setup column: below pivot / near pivot / **buy zone** (pivot to +5%, IBD) / extended / below stop / target hit. Risk %, reward/risk and a position-size calculator from your risk per trade.
- **Needs your attention today** — stop hit, breakout above your pivot, buy zone, near pivot or stop, target reached, warnings (4% breakdown, lost 50 DMA, RS falling below 70, red flags), new hits in key scans, results due within 7 days, fresh VPCI signals. The tab shows a count of urgent items.
- Columns: Tracking / Performance / Fundamentals; sort and CSV like every table.
- **Track record** — removed stocks are logged with their return and return vs NIFTY, giving your hit rate.
- Import (paste symbols, TradingView `.txt`, Kite lists), export to TradingView, backup file, share link, and **☆ Add all** on every scanner.

Watchlists are saved in your browser. **Sync devices** keeps phone and PC identical through a secret GitHub gist: create a token with only the `gist` permission (the button links to the right GitHub page), paste it once on each device. The first connect on a device that already has lists merges both.

`compute.py` also writes `docs/data/closes.json` (one year of daily closes, ~0.8 MB compressed) for the sparklines, back-dated adds and the 12-month chart in every stock card.

## Long-base identifier

The **Long bases** tab lists every stock that is in a base on the daily chart, sorted by how many trading days it has been there.

- **Definition.** A base is the stretch a stock has spent below a closing high (the **pivot**) without falling more than 50% below it. All of it is measured on daily closes, so one wick does not move the pivot.
- **Where the count starts.** After an advance, it starts at the left-side high: the first close within 5% of the pivot. If the stock fell into the base, it starts at the bar after the last close above the pivot. The advance or decline that led into the base is not counted.
- **What each stock shows:**
  - base days (and years), the start date, pivot, base low and depth;
  - where the price is (breakout, back at the pivot, extended, within 5%, 5–15% below, deeper);
  - how many times the pivot was tested;
  - the last-15-day range (tightness) and volume dry-up;
  - up/down volume, an older high above the pivot (overhead supply), and the next pivot above;
  - a measured-move target (pivot + 85% of the base height);
  - a breakout from a shorter base inside the long one in the last 20 sessions;
  - a mini chart.
- **Stock card.** It shows the same with a large chart and the Base Score broken down.
- **Base Score (0–100), built from the backtest:**

  | Part | Points |
  |---|---|
  | Base length (most for 200–399 days, then 400–799) | 25 |
  | RS rating | 25 |
  | Uptrend (above a rising 150-day and the 200-day average) | 20 |
  | Tight right side | 15 |
  | Built after an advance | 10 |
  | Little overhead supply | 5 |

- **Three scanners in the Scanners tab, under Bases:**
  - Long-base breakout (100+ days)
  - Long base near pivot (200+ days)
  - Big base with a top score
  - The first two also feed watchlist alerts and the Telegram digest.

**Checked on 20 years of NSE data** (Oct 2006 – Oct 2026, about 59,000 breakouts, returns 1 year after the breakout against NIFTY 500). The full tables are in the tab under "What 20 years of NSE data say" and in `config/base_evidence.json`.

- **Length alone did not predict a bigger move.** In an uptrend with RS 70+ it did: 200–399-day bases beat the index by about 20% on average against 11% for 25–49-day bases. Outside an uptrend, long bases gave no edge.
- **The Base Score sorted outcomes in both halves of the period.** It ran from about +3% under 40 to about +17% at 80+.
- **Caveat.** Only stocks still listed today are included.

**Data.**
- `fetch_prices.py` now downloads `base_history_calendar_days` (2,300 days, about 6 years) in the same single request per stock. Everything else still uses the usual 760-day window, so all other numbers are unchanged.
- `fetch_bse_backfill.py` adds the older BSE closes for stocks that moved from BSE to NSE recently, so their bases are not cut at the NSE listing. Stocks with no older BSE data are remembered in `config/bse_skip.csv`.
- The detection code is `scripts/bases.py`. It uses numba and runs in a few seconds.

## Stage 2: early, mid or late

**Scanners → Stage 2: early · mid · late** lists every stock in Stage 2 — the same stocks the Stage column marks as Stage 2, i.e. above a 150-day (30-week) line that rose 1%+ in 20 sessions. Each stock gets a **phase** and a **Stage 2 Score**. The list is sorted Early → Mid → Late, highest score first within each phase.

- **When the advance started:** the first Stage 2 day after the last confirmed Stage 4 (10 of 20 sessions below a falling 150-day line).
- **Phase points (0–9):**
  - O'Neil base count since the start, 0–4. A base counts after a 20%+ gain from the last counted pivot, and undercutting the previous base's low restarts the count at 1. Two bases = 1 point, three = 2, four = 3, five or more = 4.
  - Months in Stage 2, 0–2: 6–12 months = 1, over 12 months = 2.
  - Gain from the low before the start, 0–2: 150–300% = 1, over 300% = 2.
  - 150-day slope slowing, 0–1.
  - **Early** 0–1 · **Mid** 2–4 · **Late** 5+.
- **Stage 2 Score (0–100):**

  | Part | Points |
  |---|---|
  | RS | 25 |
  | 150-day slope | 20 |
  | Close to the advance's peak | 20 |
  | Above the 150-day (30–100% best) | 15 |
  | Above the 50-day | 10 |
  | Highest close in 6 years | 10 |

- **Warnings:** below the 50-day, 15%+ off the peak, slope slowing, and climax (100%+ above the 200-day).
- **Two scanners:** "Early Stage 2, score 70+" (also used in watchlist alerts and Telegram) and "Late Stage 2, weakening".

**Checked on 20 years of NSE data** (119,000 Stage 2 snapshots, 2006–2026; full tables in the tab and in `config/stage2_evidence.json`):

- **Late phase:** more risk in both halves of the period. 25–29% fell into Stage 4 within 6 months, against 17–19% for Early, and drawdowns were deeper. Lower returns showed up only in 2017–26 (+2.7% a year over NIFTY 500 vs +13.3% for Early); in 2007–16 there was no return gap.
- **Distance above the moving averages** turned out to be bullish rather than a warning, so it is not counted as lateness.
- **Best group:** Early with a score of 70+ (+23% a year, 6% fell into Stage 4). **Worst:** Late with a score under 55 (+1.5%, 40% fell into Stage 4).

The code is `scripts/stage2.py`. It uses the long-base breakouts from `bases.py` to count bases.

## Quarterly results (Results tab)

**Results** shows every result announced in the current results season — the calendar quarter in which it was announced: 1 Oct – 31 Dec, 1 Jan – 31 Mar, and so on (the Oct–Dec season is mostly the September quarter, Q2). The season before it is one tap away, and the next 14 days of announced results dates are listed at the bottom. Each result is a card (revenue, EBITDA, net profit and EPS with YoY and QoQ change, EBITDA margin and its change in points) or a row in a sortable list.

- **Basis:** consolidated when the company files it, else standalone. YoY and QoQ compare only against quarters filed on the same basis. Banks show net interest income and operating profit before provisions; other lenders show operating profit without adding back finance cost.
- **Result date:** the first filing, or the board meeting that approved the results when that came 1–3 days earlier (the XBRL file often follows the results by a day). Revised filings keep the original date. Filings more than 100 days after the quarter ended (old quarters, revisions) are left out.
- **Result Quality Score (0–100)** — is the quarter good, and is the profit real? Revenue growth 20 · operating profit growth 20 · margins 20 (best margin in five quarters, change on the year) · consistency 20 (quarters in a row with operating profit up, revenue growth speeding up) · clean profit 20 (points off for a net loss, an exceptional gain, a tax rate under 10%, other income above 30% of PBT; 8 or less caps the score at 54). Grades: 85+ Excellent · 70+ Very good · 55+ Good · 40+ Weak · under 40 Very weak. A result with no like-for-like quarter a year ago is not rated.
- **PEAD score (0–9)** — how likely the price keeps drifting up after the result: profit surprise 2 (standardised unexpected EBITDA) · profit jump vs share price 1 · revenue surprise 2 · two-session price reaction vs NIFTY 500 2 · strong close 1 · within 10% of the 52-week high before the result 1. It is filled in once two full sessions from the result day are in; until then the card shows the points already known (out of 6).
- **Scanners:** "Strong results, PEAD 7+" (Quality 70+ and PEAD 7+; also in watchlist highlights and the Telegram digest) and "Excellent results (Quality 85+)".

**Tested on 22,188 NSE results from Jul 2019 to Jul 2026** (full tables in the tab and in `config/results_evidence.json`); returns are from the close of the second session after the result, against NIFTY 500:

- **PEAD 9/9:** +8.3% on average over the next 60 sessions, 58% beat the index. **0/9:** -1.3%, 39%. The order held in every year 2019–2026 and in every market-cap band, strongest in smaller companies.
- **Quality 85+:** next quarter's operating profit was also up on the year 91% of the time (under 40: 40%), and the stock did +5.0% over 60 sessions (under 40: +0.1%).
- The two-session reaction and the revenue surprise were the strongest single signs; result-day volume added little once those were known.

The code is `scripts/results.py` (it reads `config/fund_results.csv` from the fundamentals step).

## Fund flows (what mutual funds bought)

**Scanners → Fund flows** (address `#fundflows`) shows, stock by stock, what active mutual funds bought and sold each month: net ₹ Cr bought, the share of the company that is, a bar for each of the last 12 months, how many schemes and fund houses bought vs sold, new positions and exits, how many schemes hold it, ₹ held, and the buying streak. Filter by size (Large / Mid / Small, AMFI's method) and period (last month, 3, 6, 12 months); sort by most bought, most schemes buying, most fund houses, streak, % of company or most sold. Every stock window has a **Mutual funds** section with the monthly bars and the schemes that moved most (NEW / EXIT marked). Six scanners use it (group *Fund flows*): most bought, buying streak, broad buying, new entries, buying in leaders, most sold. The Telegram digest adds a short note when a new month is in.

**Where it comes from.** SEBI makes every fund house publish each scheme's full portfolio for the last day of the month within 10 days. `scripts/fetch_mf.py` reads those files straight from the fund houses' own websites (`scripts/mf_sources.py` has one reader per fund house; `scripts/mf_browser.py` opens Bandhan's site in a headless browser because its file list is encrypted) and saves a compact copy per fund house per month in `config/mf/YYYY-MM/`. `scripts/mf_flows.py` turns the months into flows (`config/mf/site/mf.json`).

**How a flow is measured — the accuracy rules**

- *Shares, not rupees.* Net buying = change in shares held × the month's average price. Value changes from price moves are not buying.
- *Same scheme, both months.* A scheme counts only when it is in both months' files — matched by name, or, when a scheme was renamed (many were renamed in Aug 2026), by an almost identical portfolio. A fund house counts only when both of its months were read completely; a fund house that suddenly shows 20% fewer schemes is treated as not yet complete. So a file that failed to download never looks like a sale.
- *Bonus issues and splits* are put on today's share basis from the price inside the file itself (value ÷ quantity) against the split-adjusted close.
- *Left out:* new schemes investing their NFO money (two months from allotment, from AMFI's scheme list), a scheme whose money more than doubles in a month (a merger into it — a merger found in the files is added back instead), and IPO allotments in the month a stock lists (shown, not counted).
- *Active funds only* in the table and scanners. Index funds/ETFs, arbitrage funds and hedged hybrids (balanced advantage, equity savings, multi-asset) are shown separately in the stock window.
- Units (₹ lakh vs crore) are checked against NSE closing prices for every file: across the year, 99.98% of 916,595 holdings agree with the close within 3% (every fund-house month at least 99.4%).

**Checked against independent data** (October 2026; the same text is in the *How this is counted* panel):

- NSE shareholding filings name every fund house that holds 1%+ of a company. For 5,031 such positions named in consecutive quarter-end filings (Dec 2025 → Sep 2026), the change in shares found here matched the company's own filing within 1% of the position in 93% of cases; for the 2,929 positions that moved 2% or more, the direction matched in 100% and the size within 10% in 89%.
- Scheme by scheme against AMFI NAVs (Oct 2025 – Sep 2026, ~456 active schemes a month): buying plus the change in cash came within ±1% of the money that went into the scheme (worked out from its NAV and AUM) for 91% of schemes; correlation 0.96. The gap is mostly dividends the funds received, largest in July–September.
- The checking tools are not part of the daily run; they were run once on the full year.

**Coverage.** 34 fund houses — every large one; together they hold about 95% of the stocks owned by active equity funds (₹35 lakh Cr in September 2026, against AMFI's industry totals). Not read yet (their sites block automated reading or encrypt the list): Edelweiss, Mahindra Manulife, JM Financial, ITI, Union, Navi, Jio BlackRock, Quantum and a few very small ones. Bandhan takes ~5 minutes in a browser each month.

**Does it work as a signal?** The panel *Does following fund buying pay?* measures it point-in-time (returns from the 11th of the next month, when the files are public) and updates itself every month. With the first year of data there is **no reliable edge** from fund buying on its own — use it as context with price, RS and results.

**Daily workflow.** From the 1st to the 20th of each month the daily job installs `requirements-mf.txt`, reads any new files (a fund house read before the 12th is checked again until its file list stops changing), downloads AMFI's scheme list and rebuilds the flows. On other days it does nothing. Each month adds about 2 MB to `config/mf/`. (The first year of portfolios came packed in `config/mf_seed/`; the first run after the update unpacks it into `config/mf/` and removes the packed copy.) To rebuild by hand: **Actions → Daily update → Run workflow → Rebuild mutual-fund flows**.

## NSE daily data (delivery, index valuations, India VIX, corporate actions)

`scripts/fetch_nse_daily.py` keeps NSE's own end-of-day files in `config/nse/` (the idea and the early index history come from [EOD2](https://github.com/BennyThadikaran/eod2), which builds the same data from the same NSE reports):

| File | What | From |
|---|---|---|
| `dlv/YYYY-MM.csv.gz` | every stock's traded shares, number of trades and **delivered shares** (EQ, BE, BZ, SME), since Jan 2024 | `sec_bhavdata_full_DDMMYYYY.csv` |
| `idx/YYYY.csv.gz` | every NSE index incl. **India VIX**: open, high, low, close, **P/E, P/B, dividend yield**, since 2012 | `ind_close_all_DDMMYYYY.csv` |
| `corp_actions.json` | splits, bonuses, dividends, rights, demergers, buybacks — last 10 days to 60 days ahead | NSE corporate-actions list |
| `holidays.json`, `symbol_changes.json` | trading holidays; old → new symbols | NSE |

Each evening it adds every session not stored yet (it catches up after a missed day, and tries weekends too, for budget-day sessions). NSE serves the previous day's file under a holiday's name, so the date *inside* each file is checked. Past months never change, so the repository grows by about 10 MB a year.

**Checks made when it was built (Oct 2026):** delivered shares, volume and trades equal NSE's file for 100% of stocks on five test days from 2024 to 2026; delivery % matches NSE's published `DELIV_PER` to rounding for all 2,343 EQ stocks; index closes and P/E agree with EOD2 for all 167 indices. The price file is checked every evening: the last session's close of every stock is compared with NSE's official close and corrected if it differs by more than 0.1% (unless more than a fifth differ, which would mean a wrong file).

**Delivery (stock window + 5 scanners, group *Delivery*).** NSE's quantities are raw, so delivered shares are put on the split-adjusted basis of the price file (NSE delivery % × adjusted volume); value per trade (₹) needs no adjustment. BE/BZ stocks trade for delivery only, so their delivery % is left out. Tested point-in-time on Mar 2021 – Jul 2026 (weekly signals, against the average stock): *quiet delivery build-up* +1.7% over 3 months (54% beat the median stock), *delivery accumulation* +1.1%, *heavy delivery selling* −0.7%; plain *delivery spikes* and *big-ticket trades* showed **no edge** — information, not signals.

**Index valuations.** NSE moved index P/E, P/B and yield to consolidated earnings on 31 Mar 2021 (Nifty 50 P/E fell from 40.4 to 33.2 overnight with the index flat), so each index is compared only with its readings since then. The Breadth tab shows the P/E of Nifty 50 / 500 / Midcap 150 / Smallcap 250 week by week, India VIX for a year, and a table of 50 indices; the header shows India VIX and the Nifty 50 P/E.

**Rotation map (RRG).** Weekly closes of NSE's sector, theme and size indices against Nifty 500. The original RRG formulas are not published; the site uses a smoothed approximation (`scripts/indices.py`): RS-Ratio = 100 × 10-week ÷ 30-week EMA of index/Nifty 500, RS-Momentum = 100 × RS-Ratio ÷ its 10-week EMA. Leading → weakening → lagging → improving, clockwise.

To rebuild the history: `python scripts/fetch_nse_daily.py --backfill 2024-01-01 2026-10-13` (delivery) and `--backfill-idx 2016-01-01 2026-10-13` (indices).

## Group charts and group signals (spotting rotation early)

`scripts/group_index.py` builds a daily price series for every group on the site (about 200: themes, sectors, NSE indices, industries), for all member stocks and for the liquid members only:

- **Price.** NSE's official index (open/high/low/close from `config/nse/idx`) for the NSE-index groups whose history NSE publishes in full (20 of them); for everything else an **equal-weight index** of the members — each day the index moves by the average of the members' daily returns (base 100); open, high and low are the averages of each member's open, high and low against its previous close, so every candle is a real candle. A member counts only on days it traded; a move over ±40% in a day is treated as a data error (120 member-days in six years). Membership is today's list. Checked against NSE's own indices: daily returns correlate 0.88–0.96 (equal weight and cap weight differ in level — Nifty Bank's 14 members equal-weighted rose 8.9% in a year while the official index fell 1.2%, because the smaller banks did better).
- **With it, per day:** members' turnover (₹ Cr), % of members above their 50- and 200-day averages, members at 52-week highs/lows, and the **group RS rating** (1–99): the IBD formula on the group's own index, ranked against the other groups of the same kind.
- **Website:** `docs/data/grp.json` (latest readings, signals, 26-week sparklines) and one file per group in `docs/data/grp/` (loaded when its chart opens). Charts use TradingView Lightweight Charts™ v5.2.1 (Apache 2.0), kept in `docs/vendor/` so nothing loads from outside.

**Signals, tested point-in-time** on every 5th session from Jul 2021 to Jul 2026 — each group's return over the next 3 months against the average group of the same kind (`config/group_evidence.json`, shown on the site):

| Signal | Rule | Next 3 months vs average group (liquid / all stocks) |
|---|---|---|
| RS rating climbing | group RS rating 70+, up 20+ points in 4 weeks | +2.4% / +1.8%, both periods positive |
| Stage 2 start | index crosses above its rising 150-day average after 3 months mostly below | +2.2% / +1.7% (liquid: both periods positive; all stocks: −0.6% in 2021–23) |
| Stage 2 start with money | the same with turnover 1.2× its usual | +5.0% / +6.6% (small sample: 45 / 37) |
| Money flowing in | 20-day turnover 1.5× its 120-day average, index up | +1.4% / +1.1% |
| Leaders (RS 80+) / laggards (RS 20 or less) | state, not a signal | +2.3% / −2.1% |
| Fresh 52-week high, base breakout, coiling, breadth thrust, new-highs expansion | breakout patterns | about 0 or negative — no edge on their own |
| RS line breakdown, 52-week low, breadth collapse | weakness | −0.4% to −1.1% (RS line breakdown); others no edge |

A turn from lagging to improving on a group RRG did *not* help (−1.2%), which is why the Rotation radar uses the group RS rating instead. Groups share stocks and membership is today's, so treat these as tendencies, not guarantees.

## Breadth and rotation on every stock

Breadth and rotation count **every NSE main-board stock that traded** (about 2,570 a day) — as NSE counts advances and declines — instead of only the ~1,440 liquid ones. The liquid universe still drives the scanners and the RS ranking; stocks outside it appear in rotation, breadth, search and the stock window, with a note. *Stocks: All / Liquid* switches Rotation, Breadth and the header. Checked: the all-stock % above the 50 and 200 DMA matches EOD2's independent market tracker within 0.3–0.4 points on average over a year, and advances/declines agree with NSE's daily file within a few stocks. NSE lists a sector only for the ~750 stocks of its broad indices; other stocks take the NSE sector their industry belongs to (the two agree for 91% of stocks where both are known), marked in the data. Small, thinly traded stocks swing more, so the median is steadier than the mean in *All* mode.

## RS history and blue dots

`scripts/rs_history.py` computes the RS rating for every session of the last year (the same formula and universe as today's rating — checked identical for 100% of stocks today). So a 90 can be read: **▲ from 70** (climbing — the 12-week low is 10+ points below) or **▼ from 99** (slipping — the 12-week high is 10+ points above; the more recent swing wins when both). A **blue dot** marks a session on which the RS line (stock ÷ Nifty 500) closed at a 52-week high (MarketSmith). Four scanners: *RS line at a 52-week high*, *RS rating climbing* (80+, up 20+ in 4 weeks), *RS 90+ for 8 weeks*, *Leader losing RS* (95+ within 8 weeks, now 80 or lower). Tested Jul 2021 – Jul 2026: holding 90+ for 8 weeks +4.2% over 3 months against the average stock; blue dot +1.7%; leader losing RS −0.7%; ratings of 85–95 that came from ≤75 and those that came down from 99 did about the same (+1.6% / +2.9%), so the path is context, not a signal on its own.

## Telegram alerts

Two kinds of message, both sent by your own Telegram bot:

- **Evening digest** (after each daily update, ~6:50 PM; not sent on NSE holidays): NIFTY 500 and breadth verdict (all stocks), India VIX and the Nifty 50 P/E, top themes, today's tested group signals (RS rating climbing, Stage 2 start, money flowing in), every watchlist alert from the Watchlists tab (stop, breakout, buy zone, near pivot, target, warnings incl. leader losing RS and heavy delivery selling, blue dots, results due, ex-dates of splits/bonuses/dividends in the next 7 days, fresh VPCI) and today's key scanner hits, with TradingView links. If the day's prices did not arrive it says so. When a new month of mutual-fund portfolios is in, it adds what funds bought and sold most, and any of your watchlist stocks they traded.
- **Live alerts** (every 15 minutes, 9:15 AM–3:30 PM on weekdays, skipped on NSE holidays): for each stock in your watchlists, today's live price from Upstox is checked against your levels — **crossed your pivot** (with volume pace vs the 50-day average and an "extended" warning above +5%), **within 1% of pivot**, **below your stop**, **target hit**, and **±5% move today**. Each alert is sent once per stock per day.

Setup (10 minutes, once):

1. In Telegram open **@BotFather** → `/newbot` → give it any name and a username ending in `bot`. Copy the token it gives you.
2. Open your new bot and press **Start** (or send it "hi") — a bot can only message you after you've messaged it.
3. Repository → **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN` = the BotFather token
   - `GIST_TOKEN` = the same `ghp_…` token you pasted in **Sync devices** (Sync must be on — that's how the bot sees your lists and levels)
4. **Actions → Telegram live alerts → Run workflow** (mode `test`). Open the run: the log shows `YOUR TELEGRAM_CHAT_ID IS: …`. Add that number as a third secret, `TELEGRAM_CHAT_ID`.
5. Run it again with mode `test` — you get a "connected" message listing how many lists and levels it found.

Optional: a variable (same page, **Variables** tab) `SITE_URL` with your dashboard address if it isn't `https://<user>.github.io/<repo>/`; `MOVE_PCT` changes the 5% move alert.

Notes: GitHub can start scheduled runs 5–15 minutes late on busy days, so treat these as a heads-up — keep real stop-loss / GTT orders in Kite. Live alerts cover NSE stocks (BSE-only names get the evening digest only). Without the secrets the workflow simply skips. Which alerts were already sent is kept in the same secret gist (`pkc-radar-alert-state.json`).

## Fundamentals (automatic, from NSE filings)

`scripts/fetch_fundamentals.py` reads the companies' own quarterly filings on NSE every evening — no login, no uploads:

- **Quarterly results** (about 10 quarters per stock): revenue, every expense line, profit before tax, net profit attributable to shareholders, EPS; balance sheet and cash flow from the half-year (Sep) and year-end (Mar) filings.
- **Shareholding pattern** (latest 5+ quarters): promoter, FII, DII, mutual funds, retail, number of shareholders.
- **Results calendar** (board meetings for the next 60 days) and **industry** (Yahoo Finance classification).

The first run downloads everything (~35,000 small files, about 45 min); after that each run fetches only filings published since the previous one, usually a few minutes. Data is kept in `config/fund_results.csv`, `config/fund_holdings.csv` and `config/fund_info.csv`.

`scripts/fundamentals.py` turns this into: profit and revenue growth (YoY, QoQ, trailing four quarters), three-quarter earnings acceleration, operating margin and its change, P/E, P/S and PEG on today's market cap, ROE, ROCE, debt/equity, free cash flow, CWIP share of assets, and shareholding changes over 1 quarter and 1 year. A **Fund rating 1–99** (70% growth, 30% quality, percentile across the universe; loss-makers capped low) sits next to the RS rating, and every scanner can be limited to Fund 60+ or 80+.

Fundamental scanners: growth leaders 25/25, earnings acceleration, CANSLIM-style, SEPA, margin expansion, revenue streak, turnaround, post-results breakout, results in the next 7 days, quality compounders, GARP, capex cycle, net-cash small caps, smart-money accumulation, mutual funds moving in, promoter buying, under-followed leaders, and fundamental red flags.

Banks and lenders skip margin, ROCE, debt and cash-flow tests. Growth is only computed from a profitable base.

## VPCI Screener

`vpci/` holds your screener exactly as in the `rojiroti` repo (`app.py`, `vpci_engine.py`, `data_sources.py`, `signal_history.py`, `sector_history.py`, `Stock_List.csv`). `scripts/vpci_app_run.py` does what clicking **Run Market Scan** does, with the app's defaults (Upstox → Yahoo, relaxed off, 12 workers), twice: once with "Screen the RUNNING week" off and once on (volume pro-rated). It reads its functions straight from `vpci/app.py`, so when you change the screener, copy the new files into `vpci/` and the website follows.

Checked against the real app: running `app.py` through Streamlit's test harness on 140 stocks gave identical values in every column, the same statuses and the same market caps.

Kite isn't used here (it needs a fresh token every day). Sector-rotation history is saved as one snapshot per week in `docs/data/vpci/history/`.

## Settings

`config/settings.json`:

| Setting | Default | Meaning |
|---|---|---|
| `base_history_calendar_days` | 2300 | Days of daily candles downloaded for the long-base identifier (everything else uses `history_calendar_days`, 760) |
| `min_price` | 20 | Ignore stocks below this price |
| `min_median_turnover_cr` | 1.0 | Median 50-day traded value, ₹ crore |
| `min_market_cap_cr` | 500 | Used only if `industry_bse.csv` or `mcap.csv` exists |
| `min_group_size` | 3 | Smallest group shown on the Rotation tab |
| `include_series` | EQ, BE | NSE series included |
| `upstox_requests_per_second` | 10 | Download speed; lower it if you ever see refusals |

## How the numbers are calculated

- **Prices** are adjusted for splits and bonuses (checked: HDFC Bank's 1:1 bonus and Bajaj Finance's split show no jumps). Upstox closes and volumes matched NSE's bhavcopy exactly for all 2,912 stocks tested.
- **Group return** = equal-weighted mean (or median) of member stocks' returns. Rank arrows compare with the same calculation 5 sessions ago.
- **RS rating** = percentile (1–99) of 0.4 × 3-month + 0.2 × 6-month + 0.2 × 9-month + 0.2 × 12-month performance.
- **Stage** = price vs the 150-day SMA (30-week) and its 20-day slope: above and rising = Stage 2, below and falling = Stage 4.
- **Trend template** = Minervini's 8 conditions with RS ≥ 70.
- **Darvas breakout** = prior 20-session range ≤ 15%, close above its high, volume ≥ 1.5× the 50-day average.
- **Breadth** counts every main-board stock that traded on each day (the liquid version uses today's liquid universe across the history). McClellan oscillator = 19-day minus 39-day EMA of daily (advances − declines) per 1,000 issues; A/D line = running total of advances − declines over the year shown.

## Scanner audit (October 2026)

Every scanner was checked against its published definition and against a second, independent implementation.

**Indicators now match TradingView exactly.** RSI, ATR, ADX and ±DI use Wilder's average seeded with a simple average (Pine `ta.rma`); EMAs start from the first close (`ta.ema`); Bollinger bands use the population standard deviation (`ta.stdev`); Supertrend is a line-by-line port of Pine's `ta.supertrend`. Days a stock did not trade (suspensions) are skipped, as TradingView has no bar for them. All 11 indicators were compared bar by bar on 417 stocks against a separate reference: identical.

**Every technical scan was rebuilt from scratch** in plain Python, one stock at a time, straight from the published rules, and compared with the site's code on 9 dates across the last year: 0 differences on all 57 scans.

What changed (counts are for 12 Oct 2026, before → after):

| Scanner | Change | Count |
|---|---|---|
| Launch pad | Now Deepvue's definition: close within 3% of the 21-day SMA, 50-day SMA and 65-day EMA, stacked 21 > 50 > 65, all three rising over the week. The old version bunched the 10 EMA, 21 EMA and 50 DMA within 2%. | 32 → 12 |
| Pocket pivot | Added Kacher & Morales' "not extended" rule (close no more than 5% above the 10-day SMA) and a 50-day SMA that is not falling. All 41 removed stocks were more than 5% above the 10-day. | 55 → 14 |
| Power trend | Follows IBD: low above the 21-day EMA for 10 sessions, 21 EMA above the 50-day SMA for 5 sessions, 50-day rising, up close. | — |
| Buyable gap-up | Gap measured in 40-day ATR as of the day before the gap (Morales & Kacher). | — |
| Stage 2 breakout | Added Weinstein's volume confirmation, which was missing: at least 1.5× average volume on one of the last 5 sessions, so the day of the 150-day cross counts. | 18 → 15 |
| Wedge pop | Uses the 10- and 20-day EMAs, as Oliver Kell defines it (it used the 21-day). | — |
| Power of 3 | No longer fires on new listings that don't have a 50-day average yet. | — |
| Inside day, double inside day | A bar that touches yesterday's high or low still counts as inside, as long as its range is smaller. | — |
| Bollinger breakout, strong ADX | Exact TradingView maths. | +1 each |
| Turnaround | Needs a profit this quarter and the last one after a loss a year ago; recent IPOs with no year-ago quarter are left out. | 31 → 17 |
| Post-results drift | Uses the date results were first filed, not a later revised filing. | — |
| Confluence | Follows from the changes above. | 56 → 42 |

Attributions were corrected too: Ants is David Ryan's indicator; the bull snort is a trader's term for a power candle, not Oliver Kell's; the high-octane list notes that Deepvue uses ADR above 3% while the site asks for 5%.

## Troubleshooting

| Problem | Fix |
|---|---|
| Actions run is red | Open it and read the step that failed. If Upstox failed, the Yahoo step should have run instead. |
| Site says "Data files could not be loaded" | The workflow hasn't succeeded yet — check the Actions tab. |
| Today's candle missing | NSE publishes the bhavcopy around 6 PM; on rare late days the run uses Upstox's own end-of-day candle. Run the workflow again later if needed. |
| Want data now | Actions → Daily update → Run workflow (choose `yahoo` if Upstox is down). |
| Workflow stopped running | GitHub pauses schedules after 60 days without repo activity on public repos. The daily data commit counts as activity, so this only happens if runs keep failing. |

## A note on the data source

Upstox's historical-candle endpoint is meant for its API users, and it currently answers without a login. That could change without notice; if it does, the job falls back to Yahoo automatically and you'll see "Yahoo (backup)" in the site header. Keep the dashboard for personal use; don't resell the data.
