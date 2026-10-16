"""Detailed, plain-English documentation for every scanner on the site (shown in a collapsible panel).

Each entry: what (what it finds and why it matters), rules (the exact conditions the code applies),
use (how traders use it), watch (where it misleads), src (who defined the setup).

Terms used in the rules:
  SMA / EMA   simple / exponential moving average of daily closes, computed exactly as TradingView does
  Stage-2 stack   close above the 50-day SMA, 50 above 150, 150 above 200
  Average volume  the average of the 50 sessions before today
  RS rating   IBD-style 1-99 rank of the 12-month return (last quarter counts double) across the site's universe
  ADR %       average daily range: mean of (high / low - 1) over the last 20 sessions
  Close range where the close sits in the day's range: 0% = at the low, 100% = at the high
"""

STACK = "Stage-2 stack: close above the 50-day SMA, 50 above the 150-day, 150 above the 200-day"

DOCS = {
    # ── Confluence
    "combo3": dict(
        what="The day's shortlist: stocks that fire bullish scans in at least 4 different groups at once — momentum, breakouts, "
             "volume, trend & pullbacks, price action, oscillators and relative strength. Agreement between independent kinds of "
             "evidence is stronger than any single signal.",
        rules=["The stock is in bullish scans from 4 or more of the 7 technical groups today",
               "Each group counts once: three momentum scans still score 1 for momentum",
               "Broad 'state' lists are left out of the count: trend template, strong ADX, leaders near highs, high-octane, swing leaders",
               "Weakness scans are left out of the count"],
        use="Start here after the close. Open each stock to see which scans it is in, then check the chart for a clean base or pivot.",
        watch="One huge up day can still trip four groups (a 4% day + volume spike + 52-week high + RSI cross). Prefer stocks breaking "
              "out of a tight base, not ones already far above their averages.",
        src="Site rule"),
    # ── Momentum
    "up4": dict(
        what="The start of a momentum burst: a stock that jumps 4% or more on rising volume often keeps moving for 3–5 days.",
        rules=["Close at least 4% above yesterday's close", "Volume higher than yesterday's volume"],
        use="Bonde buys on the day or the next morning, stop at the low of the breakout day, and takes profits into the 3–5 day burst "
            "(8–20%). Best when the stock was tight and quiet before the move.",
        watch="After a long run a 4% day can be exhaustion. Check that the stock wasn't already up a lot in the last few days.",
        src="Pradeep Bonde (Stockbee) — 4% breakout / momentum burst"),
    "burst20": dict(
        what="Stocks that have already moved fast: up 20% or more in a week.",
        rules=["Close today at least 20% above the close 5 sessions ago"],
        use="A watch list, not a buy list: wait for the first orderly pullback or a tight flag before entering.",
        watch="Often news- or circuit-driven. Check the reason; chasing a 20% week usually means buying someone's profit-taking.",
        src="Momentum screening convention"),
    "gap_up": dict(
        what="A gap up that buyers defended all day — demand strong enough to keep the price above yesterday's high.",
        rules=["Opened at least 2% above yesterday's close",
               "The day's low stayed above yesterday's high (the gap never filled)", "Closed above the open"],
        use="Buy near the close or on a dip that holds the gap; stop just under the gap-day low.",
        watch="Gaps on no news in thin stocks fade more often. Prefer above-average volume.",
        src="Classic gap analysis"),
    "rs_jump": dict(
        what="A fresh surge in relative strength: the stock has moved up the RS ranking quickly.",
        rules=["RS rating 70 or higher today", "RS rating up 15 points or more against 5 sessions ago"],
        use="Early warning that money is rotating into the stock — look for a base or pivot to buy from.",
        watch="A jump can come from one big day. Confirm with price above its 50-day SMA.",
        src="IBD-style RS rating"),
    "leaders": dict(
        what="The market's strongest stocks that are also near their highs.",
        rules=["RS rating 90 or higher", "Close within 5% of the 52-week high (highest high of the last 252 sessions)"],
        use="A core watch list for breakouts and pullback buys.",
        watch="A broad list — it says nothing about the setup. Pair it with a base, tight area or pivot.",
        src="William O'Neil / IBD leadership"),
    "power_trend": dict(
        what="A trend so strong that buyers step in before the stock can pull back to its 21-day EMA.",
        rules=["Low above the 21-day EMA on each of the last 10 sessions",
               "21-day EMA above the 50-day SMA on each of the last 5 sessions",
               "50-day SMA higher than yesterday", "Close above yesterday's close"],
        use="Hold winners and buy pullbacks to the 10 or 21-day EMA while it lasts. IBD ends a power trend when the 21-day EMA "
            "crosses back below the 50-day SMA.",
        watch="A state, not an entry. The further price runs above the 21 EMA, the worse the risk on a fresh buy.",
        src="IBD Power Trend (Mike Webster)"),
    "ants": dict(
        what="Steady institutional accumulation: up almost every day for three weeks, with rising volume — 'ants' carrying the stock up.",
        rules=["Up close on 12 or more of the last 15 sessions", "Price up 20% or more over those 15 sessions",
               "Average volume of the 15 sessions at least 1.2× the average of the 50 sessions before"],
        use="Marks a stock under accumulation. The first pullback after the streak is often a good entry.",
        watch="After 15 strong days the stock is usually extended — rarely a same-day buy.",
        src="David Ryan's Ants indicator (IBD / MarketSurge)"),
    "high_octane": dict(
        what="Fast-moving leaders: stocks with big daily ranges that are also strong and near highs — the names swing traders want.",
        rules=["ADR % (average daily range, 20 sessions) of 5% or more", "RS rating 90 or higher",
               "Close above the 21-day EMA and the 50-day SMA", "Within 10% of the 52-week high"],
        use="Size positions smaller — a 5% average range means wide stops. Good candidates for short swing trades.",
        watch="Deepvue's version uses ADR above 3%; raised to 5% here because Indian small caps swing more.",
        src="Deepvue 'High Octane RS' (adapted)"),
    "strong_3612": dict(
        what="Stocks leading over every horizon: top 10% on 3-month, 6-month and 12-month returns.",
        rules=["Top 10% of the universe by 3-month (63 sessions) return",
               "Top 10% by 6-month (126 sessions) return", "Top 10% by 12-month (252 sessions) return",
               "Close above the 21-day EMA"],
        use="A leadership list for swing and position trades — buy constructive pullbacks or new bases.",
        watch="A broad list; check that the stock isn't late in a long advance (see Stage 2 phase).",
        src="Mike Webster's 3-6-12 leaders"),
    "episodic_pivot": dict(
        what="A big gap on huge volume in a stock that was quiet — usually news that changes the story (results, orders, policy).",
        rules=["Opened 10% or more above yesterday's close", "Volume at least 3× the 50-day average",
               "Close no more than 2% below the open (the gap held)",
               "Not up more than 30% over the previous ~3 months (yesterday vs 64 sessions earlier)"],
        use="Bonde buys on the EP day or the next day with a stop below the EP day's low; the best ones run for weeks.",
        watch="Always read the news. A gap on a one-off (asset sale, rumour) fades; a gap on earnings surprise tends to drift.",
        src="Pradeep Bonde — Episodic Pivot"),
    "bgu": dict(
        what="A gap up big enough relative to the stock's normal range, on heavy volume — Morales' 'buyable' gap.",
        rules=["Open above yesterday's high by at least 0.75 × the 40-day ATR (Wilder, as of yesterday)",
               "Volume at least 1.5× the 50-day average",
               "Close in the upper half of the day's range and not more than 1% below the open"],
        use="Buy at or near the gap; stop at the gap-day's intraday low. The gap low is the line in the sand.",
        watch="The close-position filters are this site's addition to weed out gaps that sold off all day.",
        src="Gil Morales & Chris Kacher — Buyable Gap-Up"),
    # ── Breakouts
    "high52": dict(
        what="A new 52-week closing high: the stock closed above every close of the past year.",
        rules=["Close above the highest close of the previous 252 sessions", "At least 200 sessions of history"],
        use="Stocks at highs tend to keep making highs (no overhead supply). Best out of a proper base on volume.",
        watch="Check the volume column — breakouts on below-average volume fail more often.",
        src="52-week high effect (George & Hwang 2004)"),
    "high2y": dict(
        what="The highest close in about two years — a bigger, more meaningful high than a 52-week one.",
        rules=["Close at or above the highest close of the site's ~2-year price history",
               "At least 400 sessions of history"],
        use="Same as 52-week highs, with even less overhead supply.",
        watch="Two years is the data window, not the all-time high — see Green line breakout for that.",
        src="Site rule"),
    "high52_dcr": dict(
        what="A 52-week high where buyers held the price into the close — a stronger breakout day.",
        rules=["New 52-week closing high (as above)", "Close in the top third of the day's range (close range 67%+)"],
        use="Preferred version of the 52-week-high list for breakouts.",
        watch="A strong close on low volume is still suspect.",
        src="Deepvue daily closing range rule"),
    "ath": dict(
        what="A 'green line' breakout: the stock closed above the highest price in its entire listed history — nobody is holding at a loss.",
        rules=["Close above the all-time high (monthly history since listing + daily highs since)",
               "Volume at least 1.2× the 50-day average", "Close in the upper half of the day's range"],
        use="All-time highs have no overhead supply; leaders often start big runs here.",
        watch="For stocks listed before the long history was fetched, the all-time high comes from monthly data.",
        src="Dr Eric Wish — Green Line Breakout"),
    "tight3w": dict(
        what="Three weekly closes almost on top of each other: holders aren't selling, the stock is coiling.",
        rules=["The last three weekly closes (weeks ending Friday; this week so far counts) within 1.5% of each other",
               STACK],
        use="Buy point: just above the highest intraday high of the three weeks. O'Neil adds to winners on these.",
        watch="Mid-week the third close can still change — the list is final on Friday.",
        src="William O'Neil — 3 weeks tight"),
    "launchpad": dict(
        what="A bunch of rising moving averages right under the price: volatility has contracted and the stock is ready to launch.",
        rules=["Close within 3% of the 21-day SMA, the 50-day SMA and the 65-day EMA (each one)",
               "Averages stacked: 21-day SMA above 50-day SMA above 65-day EMA",
               "All three averages higher than 5 sessions ago (rising)"],
        use="Deepvue: go long above the high of the tight range, stop at the bottom of the range. Often an earlier entry than "
            "waiting for the 52-week-high breakout.",
        watch="Deepvue's page says 'within 1–3%'; this uses the 3% end. Earlier versions of this site used 10/21 EMA + 50 SMA — "
              "that is a different screen.",
        src="Deepvue — Launch Pad"),
    "ipo_bo": dict(
        what="A recent listing breaking above its highest price since listing — many big leaders start this way.",
        rules=["First trade within the last 252 sessions and at least 10 sessions ago",
               "Close above the highest high since listing (before today)", "Volume at least 1.5× average"],
        use="Buy the breakout from the first proper base after listing; stop under the base.",
        watch="'Listed' means the first day in this site's price data — a stock that moved from SME or BSE also counts.",
        src="O'Neil — IPO base breakouts"),
    "darvas": dict(
        what="A breakout from a tight box: the stock traded in a narrow range for a month, then closed above it on volume.",
        rules=["The previous 20 sessions' high and low within 15% of each other (the box)",
               "Close above the box top (the 20-session high)", "Volume at least 1.5× average"],
        use="Buy the breakout; stop below the box bottom or the breakout day's low.",
        watch="Simplified: Darvas drew boxes from his own swing highs and lows; here the box is always the last 20 sessions.",
        src="Nicolas Darvas — box theory"),
    "bb_break": dict(
        what="Price closing outside its normal volatility band on heavy volume — an expansion move.",
        rules=["Close above the upper Bollinger band: 20-day SMA + 2 × standard deviation (population, as TradingView)",
               "Volume at least 1.5× average"],
        use="Momentum entry after a squeeze; strong trends 'walk the band'.",
        watch="Outside a trend a close above the band often snaps back — combine with a base or squeeze.",
        src="John Bollinger"),
    "stage2_bo": dict(
        what="The start of a Weinstein Stage 2 advance: price breaks above a flattening or rising 30-week average on volume.",
        rules=["Close crossed above the 150-day SMA (about the 30-week line) in the last 5 sessions",
               "150-day SMA flat or rising (at least 99.5% of its value 20 sessions ago)", "Close above the 50-day SMA",
               "Volume at least 1.5× average on at least one of the last 5 sessions"],
        use="Weinstein buys the breakout above the base and the 30-week line; stop below the base.",
        watch="Weinstein wanted at least 2× normal volume on the breakout week; this uses 1.5× on a daily bar.",
        src="Stan Weinstein — Secrets for Profiting in Bull and Bear Markets"),
    "vcp": dict(
        what="A volatility contraction pattern: each pullback inside the base is smaller than the last and volume dries up.",
        rules=[STACK, "Within 15% of the 52-week high",
               "High–low range of sessions 40–21 ago > range of 20–11 ago > range of the last 10",
               "Range of the last 10 sessions 10% or less",
               "Average volume of the last 10 sessions below the average of the 50 before"],
        use="Buy the breakout above the high of the last tight range (the pivot); stop under the last contraction's low.",
        watch="A simplified, fixed-window version of Minervini's pattern — always confirm on the chart.",
        src="Mark Minervini — VCP"),
    # ── Volume
    "vol_spike": dict(
        what="A burst of buying volume on an up day.",
        rules=["Volume at least 3× the 50-day average", "Close up 2% or more"],
        use="Flags institutional activity; best when it lifts the stock out of a base.",
        watch="Index rebalances and block deals can spike volume without a real change in demand.",
        src="Volume analysis convention"),
    "pocket_pivot": dict(
        what="An early buy point inside a base: an up day whose volume tops every down day of the last two weeks.",
        rules=["Close above yesterday's close",
               "Volume above the highest volume of any down day in the previous 10 sessions",
               "Close above the 10-day SMA and the 50-day SMA, but no more than 5% above the 10-day SMA",
               "50-day SMA not lower than 5 sessions ago", "Within 15% of the 52-week high"],
        use="Kacher & Morales buy pocket pivots near the 10-day line, before the classic breakout; stop just under the 10 or 50-day line.",
        watch="The 'not extended' limit (5% above the 10-day line) is this site's number — the authors leave it to judgement. "
              "Up days far above the 10-day line are breakouts or bursts, not pocket pivots.",
        src="Chris Kacher & Gil Morales — Pocket Pivot"),
    "vol_high": dict(
        what="The heaviest trading day in a year, and the stock closed up.",
        rules=["Today's volume is the highest of the last 252 sessions", "Close above yesterday's",
               "At least 200 sessions of history"],
        use="Often marks a change in the story (results, big order). Watch how the stock holds the day's range afterwards.",
        watch="Can also be a climax top after a long run — check where in the trend it happens.",
        src="Volume analysis convention"),
    "dryup": dict(
        what="Selling has dried up while the stock holds near its highs — supply exhausted, often just before a breakout.",
        rules=["Average volume of the last 5 sessions at most 50% of the 50-day average",
               "Within 10% of the 52-week high", "Close above the 50-day SMA"],
        use="Set an alert above the recent high; buy when volume returns on an up move.",
        watch="Holiday weeks dry up volume for everyone.",
        src="O'Neil / Minervini — volume dry-up in the right side of a base"),
    # ── Trend & pullbacks
    "trend_template": dict(
        what="Minervini's eight checks for a stock in a confirmed Stage 2 uptrend — the first filter before looking for a setup.",
        rules=["Close above the 150-day and the 200-day SMA", "150-day SMA above the 200-day SMA",
               "200-day SMA higher than 21 sessions ago (rising for about a month)", "50-day SMA above the 150 and 200-day",
               "Close above the 50-day SMA", "Close at least 30% above the 52-week low",
               "Close within 25% of the 52-week high", "RS rating 70 or higher"],
        use="Only look for buy setups (VCP, pivots, tight areas) in stocks that pass.",
        watch="A broad state list — hundreds of stocks pass in a bull market.",
        src="Mark Minervini — Trend Template"),
    "golden": dict(
        what="The 50-day average crossing above the 200-day — a long-term trend turning up.",
        rules=["50-day SMA crossed above the 200-day SMA on one of the last 5 sessions"],
        use="A trend-change flag for position traders; buy pullbacks once it holds.",
        watch="A slow, lagging signal — price usually moved well before the cross.",
        src="Classic moving-average crossover"),
    "ema_up": dict(
        what="The 20-day EMA crossing above the 50-day EMA — a medium-term trend turning up.",
        rules=["20-day EMA crossed above the 50-day EMA in the last 3 sessions", "Close above the 20-day EMA"],
        use="Swing traders use it to switch from 'avoid' to 'look for entries'.",
        watch="Whipsaws a lot in sideways markets.",
        src="Moving-average crossover"),
    "pb20": dict(
        what="A strong uptrend pulling back to the 20-day EMA and bouncing — the classic low-risk add point.",
        rules=[STACK, "RS rating 70 or higher", "Today's low at or within 1% above the 20-day EMA",
               "Close at or above the 20-day EMA"],
        use="Buy near the EMA with a stop a little under it.",
        watch="A pullback on heavy volume is distribution, not a dip — check the volume.",
        src="Swing-trading pullback rule"),
    "pb50": dict(
        what="A leader testing its 50-day average and holding — where institutions often defend a position.",
        rules=[STACK, "RS rating 70 or higher", "Today's low at or within 1.5% above the 50-day SMA",
               "Close above the 50-day SMA"],
        use="O'Neil's first test of the 50-day line is a classic add point; stop a few percent under the line.",
        watch="The third or fourth test of the 50-day line is weaker than the first.",
        src="O'Neil — 50-day line support"),
    "supertrend": dict(
        what="The Supertrend indicator flipping from sell to buy — a trend-following entry signal.",
        rules=["Supertrend (ATR 10, factor 3 — TradingView's ta.supertrend) in buy mode today",
               "It was in sell mode on one of the 2 previous sessions"],
        use="Trail a stop on the Supertrend line while it stays in buy mode.",
        watch="Late in a choppy range it flips back and forth — use with a trend filter.",
        src="Olivier Seban — Supertrend"),
    "adx_strong": dict(
        what="A trend with real force: ADX strong and rising, buyers in control.",
        rules=["ADX(14) at least 25 (TradingView DMI 14, 14)", "ADX higher than 5 sessions ago", "+DI above −DI"],
        use="Confirms a trend is worth trading; combine with a pullback scan for the entry.",
        watch="A state list. ADX above 40–50 often comes late in a move.",
        src="J. Welles Wilder — DMI / ADX"),
    "nr7": dict(
        what="The quietest day in a week inside an uptrend — a volatility pause that often comes before a range expansion.",
        rules=["Today's high–low range is the smallest of the last 7 sessions (today included)", STACK],
        use="Buy a move above today's high; stop below today's low. Tight risk.",
        watch="The expansion can go either way; the uptrend filter tilts the odds.",
        src="Toby Crabel — NR7"),
    "inside": dict(
        what="A day that traded entirely inside yesterday's range, in a strong uptrend — a short coil.",
        rules=["Today's high at or below yesterday's high and low at or above yesterday's low (and a smaller range)",
               STACK, "RS rating 70 or higher"],
        use="Buy above the mother bar's (yesterday's) high; stop below its low.",
        watch="Single inside days are common — the double inside day is the tighter version.",
        src="Price-action convention"),
    "power3": dict(
        what="In one up day the stock went from below all three key averages to above all three — a decisive reclaim.",
        rules=["Close above yesterday's close", "Today's low at or below the lowest of the 10-day EMA, 21-day EMA and 50-day SMA",
               "Close above the highest of the three (all three must exist)"],
        use="Often ends a pullback; buy with a stop under the day's low.",
        watch="Works best when the averages are rising; a reclaim of falling averages is a bounce, not a trend.",
        src="Deepvue — Power of 3"),
    "wedge_pop": dict(
        what="After drifting under its short-term averages, the stock pops back above them on volume — the end of a pullback or wedge.",
        rules=["At least 3 of the previous 5 closes below the 20-day EMA",
               "Today's close above both the 10-day and the 20-day EMA", "Volume at least 1.5× average",
               "50-day SMA above the 200-day SMA"],
        use="Kell's first entry in a new uptrend cycle; stop below the day's low.",
        watch="Kell also wants a falling wedge before the pop — this scan doesn't measure the wedge shape.",
        src="Oliver Kell — Wedge Pop (cycle of price action)"),
    # ── Price action
    "outside_day": dict(
        what="A day whose range swallows yesterday's and closes near the high — control switching to buyers.",
        rules=["High above yesterday's high and low below yesterday's low", "Close above yesterday's close",
               "Close in the top 30% of the day's range", "Volume at least the 50-day average"],
        use="A reversal entry after a pullback; stop under the day's low.",
        watch="In a downtrend it is often just a bounce.",
        src="Candlestick / price-action convention (bullish engulfing range)"),
    "open_low": dict(
        what="The stock opened at the low of the day and never looked back — buyers in charge from the first trade.",
        rules=["Open within 0.05% of the day's low", "Close at least 2% above the open", "Volume at least the 50-day average"],
        use="Intraday-strength signal; good follow-through candidates for the next session.",
        watch="Common on index up days — compare with the market.",
        src="Indian trading convention (open = low)"),
    "hammer50": dict(
        what="A hammer candle on the 50-day average: sellers pushed it down to support, buyers pushed it back.",
        rules=["Lower wick at least 2× the candle body", "Upper wick no bigger than the body",
               "Low at or within 1% above the 50-day SMA", "Close above the 50-day SMA", STACK],
        use="Buy above the hammer's high; stop under its low.",
        watch="A hammer needs follow-through the next day to mean much.",
        src="Candlestick analysis (hammer) at moving-average support"),
    "inside2": dict(
        what="Two inside days in a row in an uptrend — a tighter coil than a single inside day.",
        rules=["Today inside yesterday's range and yesterday inside the day before's", STACK],
        use="Buy above the mother bar's high (the day before yesterday); stop below its low.",
        watch="Rare and tight — false breaks happen; wait for a close above the mother bar.",
        src="Price-action convention"),
    "bull_snort": dict(
        what="A 'power candle': after a short dip, a big up day on heavy volume closing near the high.",
        rules=["At least 2 down closes in the 3 sessions before today", "Up 3% or more today",
               "Volume at least 2× average", "Close in the top 25% of the day's range", "Close above the 200-day SMA"],
        use="Marks institutions stepping back in after a dip; the day's low is the stop.",
        watch="A trader nickname rather than a formal published setup; thresholds are this site's.",
        src="Trader slang for a power candle"),
    # ── Oscillators
    "rsi60": dict(
        what="RSI moving into its bull range: momentum shifting up.",
        rules=["RSI(14) — Wilder, as TradingView — above 60 today and at or below 60 yesterday", "Close above the 50-day SMA"],
        use="Cardwell: in bull trends RSI holds 40–80; a push through 60 often starts a new up leg.",
        watch="In sideways markets RSI crosses 60 often without follow-through.",
        src="Andrew Cardwell — RSI range rules"),
    "rsi30": dict(
        what="An oversold bounce in a stock that is still in a long-term uptrend — a dip, not a collapse.",
        rules=["RSI(14) crossed back above 30 today or yesterday", "Close above the 200-day SMA"],
        use="Mean-reversion entry; stop under the recent low.",
        watch="Below the 50-day SMA the stock may still be in a correction — size small.",
        src="J. Welles Wilder — RSI"),
    "macd_bull": dict(
        what="MACD turning up while already above zero — momentum resuming inside an uptrend.",
        rules=["MACD line (12-day EMA minus 26-day EMA) crossed above its 9-day EMA signal today or yesterday",
               "MACD above zero"],
        use="A continuation signal after a pause.",
        watch="Lags price; many crosses happen after the move.",
        src="Gerald Appel — MACD"),
    "squeeze": dict(
        what="Bollinger bands at their narrowest in six months: the stock is unusually quiet, and big moves follow quiet periods.",
        rules=["Band width (4 × standard deviation ÷ 20-day SMA) is the lowest of the last 120 sessions",
               "Close above the 50-day SMA", "At least 150 sessions of history"],
        use="Set alerts above the recent high; buy the expansion when volume comes in.",
        watch="The squeeze tells you a move is coming, not its direction.",
        src="John Bollinger — the squeeze"),
    # ── Relative strength
    "rsnh_1m": dict(
        what="The RS line (stock ÷ NIFTY 500) is at a 1-month high while the price isn't yet — strength showing before the breakout.",
        rules=["RS line at its highest of the last 21 sessions", "Close more than 2% below its own highest close of those 21 sessions",
               "RS rating 70 or higher"],
        use="Put it on watch for a price breakout; leaders' RS lines often lead price.",
        watch="In a falling market a stock can make RS highs just by falling less.",
        src="Deepvue — RS New Highs Before Price"),
    "rsnh_3m": dict(
        what="RS line at a 3-month high while price is still below its own 3-month high.",
        rules=["RS line at its highest of the last 63 sessions", "Close more than 2% below its own highest close of those 63 sessions",
               "RS rating 70 or higher"],
        use="Stronger than the 1-month version; watch for the price to follow.",
        watch="Same caveat: falling less than the market also lifts the RS line.",
        src="Deepvue — RS New Highs Before Price"),
    "rsnh_6m": dict(
        what="RS line at a 6-month high while price lags — a meaningful leadership tell.",
        rules=["RS line at its highest of the last 126 sessions", "Close more than 2% below its own highest close of those 126 sessions",
               "RS rating 70 or higher"],
        use="Often seen in the right side of a base just before a breakout.",
        watch="Check that the base itself is constructive.",
        src="Deepvue — RS New Highs Before Price"),
    "rsline_lead": dict(
        what="RS line at a 52-week high before the price — O'Neil's 'blue dot', one of the best leadership signals.",
        rules=["RS line at its highest of the last 252 sessions", "Close more than 2% below the 52-week high",
               "At least 200 sessions of history"],
        use="Watch closely for the price breakout; these often become the cycle's leaders.",
        watch="No RS-rating floor here, so a few weak stocks in a falling market can appear.",
        src="William O'Neil / IBD — RS line blue dot"),
    # ── Delivery (NSE security-wise delivery position)
    "dlv_spike": dict(
        what="A day when far more shares than usual were taken into delivery, on a strong up day in an up-trending "
             "stock. Delivery is volume that was not squared off the same day — buyers kept the shares.",
        rules=["Delivered shares today ≥ 3× the average of the previous 50 sessions (split-adjusted)",
               "Close at least 2% above yesterday's", "Close above the 50-day SMA"],
        use="Information about who is buying, not a buy signal by itself — check whether the stock is breaking out of a base.",
        watch="Block deals, index rebalancing and results days all create one-day delivery spikes that mean little.",
        evid="Mar 2021 – Jul 2026, 6,285 weekly signals: no edge. Over 3 months these stocks did +0.3% better than the "
             "average stock, while all 2%-up days above the 50-day average did +0.7%, and they beat the median stock "
             "49% of the time. Delivery spikes alone did not predict returns.",
        src="NSE delivery data (sec_bhavdata_full); site's own rule"),
    "dlv_accum": dict(
        what="Repeated heavy delivery on up days with little on down days over the last month — the pattern of steady "
             "accumulation rather than one big day.",
        rules=["Accumulation day: close up on the day and delivered shares ≥ 1.5× the 50-session average",
               "Distribution day: the same on a down close",
               "4 or more accumulation days and at most 1 distribution day in the last 20 sessions",
               "Close above the 50-day SMA"],
        use="A shortlist of stocks with persistent delivery buying. Combine with a base or a Stage 2 setup.",
        watch="Counts can build up in a strong rally across the whole market; compare with the stock's own history.",
        evid="Mar 2021 – Jul 2026, 25,851 weekly signals: +1.1% over 3 months against the average stock, beating the "
             "median stock 51% of the time — a small edge.",
        src="NSE delivery data; idea after O'Neil's accumulation/distribution days, applied to delivered shares"),
    "dlv_quiet": dict(
        what="Delivery share rising while the price goes nowhere: over the last 20 sessions a clearly larger part of the "
             "volume is being delivered than over the last 6 months, inside a tight range above the 50-day average.",
        rules=["Delivery % over 20 sessions (shares delivered ÷ shares traded) ≥ 1.25× the same over 120 sessions",
               "Delivery % over 20 sessions at least 40%", "Highest close ÷ lowest close of the last 20 sessions ≤ 1.12",
               "Close above the 50-day SMA", "BE/BZ-series stocks left out (every trade there is delivered)"],
        use="Holders adding quietly before a move. Set an alert at the top of the range.",
        watch="A falling share of intraday trading (e.g. after a stock leaves the F&O list) also raises delivery %.",
        evid="Mar 2021 – Jul 2026, 5,711 weekly signals: +1.7% over 3 months against the average stock and 54% beat "
             "the median stock — the best of the delivery scanners, still a modest edge.",
        src="NSE delivery data; site's own rule"),
    "dlv_bigticket": dict(
        what="Unusually large trades: the average value per trade today was several times the stock's normal, on an up "
             "day with heavy delivery — bigger orders than the stock usually sees.",
        rules=["Value per trade (close × volume ÷ number of trades) ≥ 3× its median of the previous 50 sessions",
               "Close at least 1% above yesterday's", "Delivered shares ≥ 1.5× the 50-session average"],
        use="A pointer to check the bulk/block deal list for the day.",
        watch="Rare, and one block deal can trip it. Testing found no lasting edge.",
        evid="Mar 2021 – Jul 2026, 1,409 weekly signals: +0.4% over 3 months against the average stock, 48% beat the "
             "median — no edge.",
        src="NSE trade counts; site's own rule"),
    "dlv_dist": dict(
        what="Heavy delivery selling: far more shares than usual delivered on a sharp down day, below the 50-day average.",
        rules=["Delivered shares today ≥ 3× the 50-session average", "Close at least 2% below yesterday's",
               "Close below the 50-day SMA"],
        use="A check for stocks you hold — holders, not just traders, are leaving.",
        watch="Capitulation days look the same and sometimes mark the low.",
        evid="Mar 2021 – Jul 2026, 1,372 weekly signals: −0.7% over 3 months against the average stock (all 2%-down "
             "days below the 50-day average: +0.1%). A mild warning.",
        src="NSE delivery data; site's own rule"),
    "rs_bluedot": dict(
        what="Every stock whose RS line set a 52-week high today — the blue dot on MarketSmith charts. The stock is ahead "
             "of the market by more than at any point in the last year, whether or not its price is at a high.",
        rules=["RS line = close ÷ NIFTY 500 close", "Today's RS line is the highest of the last 252 sessions",
               "At least 200 sessions of history"],
        use="A list of today's leaders by relative strength. Open the stock window: the Relative strength chart shows every "
            "blue dot of the year, so you can see whether the dots are clustering (persistent leadership) or a one-off.",
        watch="In a falling market a stock can make an RS-line high just by falling less than the index — check that the "
              "price trend is also up.",
        evid="Sampled weekly from Jul 2021 to Jul 2026 on stocks passing the site's price and turnover filters at the time "
             "(7,967 signals): the next 3 months beat the average stock by +1.7% on average and beat the median stock 54% "
             "of the time. A real but small edge — the median signal still lagged slightly, so the gain comes from a few "
             "big winners. Today's listed stocks only, so delisted losers are missing.",
        src="William O'Neil / MarketSmith — RS line blue dot"),
    "rs_climb": dict(
        what="Stocks moving up the RS leaderboard: rated 80+ today and at least 20 points higher than four weeks ago "
             "— a 90 that came from 70, not one sliding down from 99.",
        rules=["RS rating 80 or higher today", "RS rating at least 20 points above its value 20 sessions ago"],
        use="New leadership often shows up here first. Look for a base or a pullback to buy from rather than chasing.",
        watch="A fast climb can come from one big result-day gap. Check the chart and the news behind the jump.",
        evid="Jul 2021 – Jul 2026, 4,021 weekly signals: +1.0% over 1 month and +1.7% over 3 months above the average "
             "stock, beating the median stock about half the time (51–52%). Treat it as a watch list, not a buy signal.",
        src="IBD-style RS rating (site's own rule)"),
    "rs_top_hold": dict(
        what="Persistent leaders: RS rating 90 or higher on every one of the last 40 sessions (8 weeks).",
        rules=["Daily RS rating ≥ 90 on each of the last 40 sessions"],
        use="The market's most consistent outperformers. Buy them on pullbacks to the 21-day or 50-day average.",
        watch="Long leadership runs end — watch for a close below the 50-day average on heavy volume.",
        evid="Jul 2021 – Jul 2026, 10,886 weekly signals: +1.2% over 1 month and +4.2% over 3 months above the average "
             "stock; 53% beat the median stock over 3 months — the strongest of the RS-history scanners.",
        src="IBD / O'Neil leadership — site's own rule"),
    "rs_fade": dict(
        what="Former leaders losing ground: rated 95+ at some point in the last 8 weeks, now 80 or lower.",
        rules=["Highest daily RS rating of the last 40 sessions is 95 or more", "RS rating today is 80 or lower"],
        use="A check for stocks you hold: a leader that has dropped this far is no longer leading. Tighten the stop or "
            "look for the reason.",
        watch="Some leaders reset in a normal correction and resume. Look at the price — still above the 200-day average?",
        evid="Jul 2021 – Jul 2026, 2,092 weekly signals: −0.4% over 1 month and −0.7% over 3 months against the average "
             "stock; 49–50% beat the median. A mild lag rather than a collapse.",
        src="IBD-style RS rating (site's own rule)"),
    "rs_up_mkt_down": dict(
        what="A strong stock rising on a day the market fell — buyers absorbing selling pressure.",
        rules=["Up 1% or more today", "NIFTY 500 down today", "RS rating 80 or higher", "Volume at least the 50-day average"],
        use="Shows which leaders institutions are protecting; first to break out when the market turns.",
        watch="One day is a hint, not a trend — watch for repeats.",
        src="O'Neil — relative strength in corrections"),
    # ── Weakness
    "down4": dict(
        what="A 4% drop on rising volume — a momentum break to the downside.",
        rules=["Close at least 4% below yesterday's close", "Volume higher than yesterday's"],
        use="Exit check for holdings: review the chart and your stop.",
        watch="After results or in a market sell-off many stocks appear; judge against the index.",
        src="Pradeep Bonde (the mirror of the 4% breakout)"),
    "leader_down": dict(
        what="A leader falling on heavy volume — possible distribution.",
        rules=["RS rating 80 or higher", "Down 2% or more today", "Volume at least 1.5× average"],
        use="If you hold it, tighten the stop; two or three such days in a few weeks is a warning.",
        watch="A single day on news can recover quickly.",
        src="O'Neil — distribution in leaders"),
    "ema_down": dict(
        what="The 20-day EMA crossing below the 50-day EMA — medium-term trend turning down.",
        rules=["20-day EMA crossed below the 50-day EMA in the last 3 sessions", "Close below the 20-day EMA"],
        use="Exit or avoid for swing trades.",
        watch="Whipsaws in sideways markets.",
        src="Moving-average crossover"),
    "below200": dict(
        what="A break of the 200-day average on heavy volume — long-term support given up.",
        rules=["Close crossed below the 200-day SMA in the last 3 sessions", "Still below it today",
               "Volume today at least 1.5× average"],
        use="A sell rule for position trades; Weinstein Stage 3 → 4 warning.",
        watch="A quick reclaim within days cancels the signal.",
        src="Weinstein / O'Neil — 200-day line breaks"),
    "death": dict(
        what="The 50-day average crossing below the 200-day — long-term trend turning down.",
        rules=["50-day SMA crossed below the 200-day SMA on one of the last 5 sessions"],
        use="A trend-change flag; avoid new long positions.",
        watch="Lagging — the price fall usually came earlier.",
        src="Classic moving-average crossover"),
    "low52": dict(
        what="A new 52-week closing low.",
        rules=["Close below the lowest close of the previous 252 sessions", "At least 200 sessions of history"],
        use="Avoid for longs; stocks at lows tend to keep making lows.",
        watch="Value buyers look here, but trend followers don't.",
        src="52-week low effect"),
    "gap_down": dict(
        what="A gap down that sellers kept unfilled all day.",
        rules=["Opened at least 2% below yesterday's close",
               "The day's high stayed below yesterday's low (gap unfilled)", "Closed below the open"],
        use="Exit check — unfilled gaps down often mark the start of a decline.",
        watch="On results days check what the numbers were.",
        src="Classic gap analysis"),
    # ── Fundamentals (NSE filings)
    "f_growth": dict(
        what="Fast growers the market is rewarding: revenue and profit both up 30%+ in a stock that is in Stage 2 with RS 80+.",
        rules=["Latest quarter's revenue up 30% or more on the same quarter last year",
               "Latest quarter's net profit up 30% or more", "Profitable over the last four quarters",
               "RS rating 80 or higher", "In Stage 2 (above a rising 150-day SMA)"],
        use="A growth-leader list for CANSLIM-style position trades.",
        watch="One quarter's growth can be a base effect — check the trend in the stock card.",
        src="Deepvue 30/30 screen"),
    "f_accel": dict(
        what="Earnings growth speeding up three quarters in a row — O'Neil's strongest earnings signal.",
        rules=["Year-on-year profit growth rising each quarter: two quarters ago < last quarter < latest",
               "Latest growth at least 20%; two quarters ago positive", "Latest revenue up 10% or more",
               "RS rating 60 or higher"],
        use="Buy these from proper bases; acceleration often precedes re-rating.",
        watch="Small bases make percentages jump — look at the rupee profit too.",
        src="William O'Neil — earnings acceleration"),
    "f_canslim": dict(
        what="Stocks meeting the measurable CANSLIM letters at once.",
        rules=["C: latest quarter profit +25% and revenue +20% on last year", "A: trailing-year profit up 20%+",
               "N: within 15% of the 52-week high", "L: RS rating 80+", "I: FII + DII holding up over the year",
               "M (market): check the Breadth tab"],
        use="O'Neil's full checklist for leaders; buy from bases in a confirmed uptrend.",
        watch="'A' here is one trailing year, not O'Neil's three years of annual growth.",
        src="William O'Neil — CANSLIM"),
    "f_sepa": dict(
        what="Minervini's SEPA idea: a stock passing the trend template that also has the earnings to back it.",
        rules=["Passes the trend template (all 8 checks)", "Latest profit up 20%+ and revenue up 15%+ on last year",
               "ROE 15% or more"],
        use="Look for VCPs and tight areas in these.",
        watch="Banks' ROE and growth behave differently — compare within the sector.",
        src="Mark Minervini — SEPA"),
    "f_margin": dict(
        what="Operating leverage kicking in: margins expanding while revenue grows.",
        rules=["Not a bank or other lender", "Operating margin up 3+ points on the same quarter last year",
               "Trailing-year operating margin also up", "Latest revenue up 15%+", "Profitable over the last four quarters",
               "RS rating 75 or higher"],
        use="Margin expansion drives earnings surprises; good post-results candidates.",
        watch="Commodity price swings can lift margins temporarily.",
        src="Operating-leverage screen"),
    "f_streak": dict(
        what="Consistent growers: revenue up 10%+ year on year for five quarters or more in a row.",
        rules=["Revenue up more than 10% on the same quarter last year for 5+ consecutive quarters",
               "Trailing-year profit up 20%+", "RS rating 70+", "Close above the 200-day SMA"],
        use="Core holdings for position trades; buy pullbacks.",
        watch="Growth by acquisition looks the same in these numbers.",
        src="Consistency-of-growth screen"),
    "f_turn": dict(
        what="A turnaround: back in profit for two quarters after a loss in the same quarter last year.",
        rules=["Net profit positive in the latest quarter", "Net profit positive in the quarter before",
               "Net loss in the same quarter last year", "Close above the 50-day SMA"],
        use="Early-stage turnarounds can re-rate sharply once the market believes the profit is real.",
        watch="Recent listings without a year-ago quarter are excluded (an earlier version wrongly included them).",
        src="Turnaround screen"),
    "f_post": dict(
        what="The market buying a good result: profit up 20%+ and the stock 5%+ above its pre-results close.",
        rules=["Results announced in the last 20 days (the first filing, or the board meeting if earlier)",
               "Latest profit up 20%+ on last year", "Close at least 5% above the last close before the results day"],
        use="Post-earnings drift: see the PEAD score on the Results tab for a tested version.",
        watch="A big gap on results can also exhaust buyers — check the reaction volume.",
        src="Post-earnings announcement drift"),
    "f_upcoming": dict(
        what="Strong stocks with results due within a week.",
        rules=["Board meeting for results scheduled 0–7 days from today (NSE corporate calendar)", "RS rating 60 or higher"],
        use="Decide before results whether to hold through them, trim or wait.",
        watch="Companies sometimes reschedule meetings.",
        src="NSE corporate calendar"),
    "f_quality": dict(
        what="High-return, low-debt businesses that are still growing — compounders.",
        rules=["Not a bank or other lender", "ROCE 20%+ and ROE 18%+ (last financial year)", "Debt/equity 0.5 or less",
               "Positive free cash flow last year", "Trailing operating margin 15%+", "Trailing revenue growth 12%+",
               "Close above the 200-day SMA"],
        use="A long-term holding list; buy on corrections to the 200-day line.",
        watch="Quality is often already priced in — check the P/E.",
        src="Quality-investing screen (ROCE / ROE)"),
    "f_garp": dict(
        what="Growth at a reasonable price: strong profit growth without a stretched valuation.",
        rules=["PEG 0.8 or less (P/E ÷ trailing profit growth %)", "Trailing profit growth 20%+", "ROE 15%+",
               "P/E under 35", "RS rating 60+", "Close above the 200-day SMA"],
        use="Peter Lynch's idea: buy growth cheaper than its growth rate.",
        watch="One-off profit jumps make the PEG look low.",
        src="Peter Lynch — PEG / GARP"),
    "f_capex": dict(
        what="Companies building new capacity that isn't in the numbers yet.",
        rules=["Not a bank or other lender", "Capital work in progress 15%+ of total assets", "Debt/equity 1 or less",
               "Trailing revenue growing"],
        use="Earnings tend to step up when the new capacity starts; watch for commissioning news.",
        watch="Delays and cost overruns are common.",
        src="Capex-cycle screen"),
    "f_netcash": dict(
        what="Small companies with more cash than debt, cash-generating and cheap.",
        rules=["Not a bank or other lender", "Cash above total borrowings", "Market cap under ₹5,000 Cr",
               "Positive free cash flow", "P/E between 0 and 25"],
        use="A value list with a balance-sheet margin of safety.",
        watch="Cheap can stay cheap without a catalyst.",
        src="Net-cash value screen"),
    "f_smart": dict(
        what="Institutions buying from individuals in a stock that is already in an uptrend.",
        rules=["FII + DII holding up 0.5+ points this quarter", "FII + DII up 1+ point over the year",
               "Retail holding down over the year", "In Stage 2"],
        use="Supports a technical setup — big holders take time to build positions.",
        watch="Shareholding is quarterly and arrives weeks after the quarter ends.",
        src="Shareholding-pattern analysis"),
    "f_mf": dict(
        what="Domestic mutual funds building positions in a stock that is acting well.",
        rules=["Mutual-fund holding up 2+ points over the year", "Still rising this quarter", "RS rating 60 or higher"],
        use="Sustained fund buying supports the trend.",
        watch="Index-fund inflows lift holdings in index stocks mechanically.",
        src="Shareholding-pattern analysis"),
    "f_promoter": dict(
        what="Promoters raising their stake — insiders putting in money.",
        rules=["Promoter holding up 0.5+ points this quarter, or 1+ point over the year"],
        use="A confidence signal; strongest when bought in the open market.",
        watch="Preferential allotments and warrant conversions also raise the stake.",
        src="Shareholding-pattern analysis"),
    "f_under": dict(
        what="Strong businesses the institutions haven't found yet.",
        rules=["FII + DII own less than 5%", "Latest profit up 25%+ and revenue up 15%+", "Fund rating 70+", "RS rating 80+"],
        use="Discovery-stage leaders: institutional buying later can drive big moves.",
        watch="Low institutional holding often means low liquidity — size carefully.",
        src="Under-owned growth screen"),
    "f_red": dict(
        what="Two or more independent warning signs in the filings — an exit check for holdings.",
        rules=["Counts: promoter stake down 2+ points in a year, or promoter and FIIs both selling this quarter (counted once)",
               "Negative operating cash flow last year despite a profit", "Debt/equity above 1.5 and rising",
               "Profit down 25%+ with revenue falling", "Two or more of these"],
        use="If you hold one, open the stock card to see which flags and review the position.",
        watch="Pledging, auditor remarks and related-party issues are not covered — read the filings.",
        src="Forensic red-flag screen"),
    # ── Long bases (bases.py)
    "lb_breakout": dict(
        what="A breakout from a long base — a stock that spent 100+ trading days below a closing high and has just cleared it.",
        rules=["The base: time spent below a closing high (the pivot) without falling more than 50% below it, 25+ days",
               "Closed above the pivot of a 100+ day base in the last 20 sessions",
               "Still within 5% above the pivot (the buy range)"],
        use="Buy in the buy range with a stop under the breakout area; see the Long bases tab for the evidence.",
        watch="In 20 years of NSE data, length alone didn't help — long bases worked when the stock was in an uptrend with RS 70+.",
        src="Weinstein Stage 1 / O'Neil bases — tested on 20 years of NSE data"),
    "lb_near": dict(
        what="A long base (200+ days) with the price within 5% of its pivot — watch for the breakout.",
        rules=["Base of 200+ trading days", "Close within 5% below the pivot"],
        use="Set an alert just above the pivot.",
        watch="Some bases stay near the pivot for weeks — wait for the close above it.",
        src="Long-base identifier"),
    "lb_best": dict(
        what="The best-scoring big bases: 200+ days with a Base Score of 70+.",
        rules=["Base of 200+ trading days", "Base Score 70+ (uptrend, RS, tight right side, base built after an advance)",
               "Not extended and no more than 15% below its pivot"],
        use="Score-70+ breakouts beat NIFTY 500 by 14–17% on average over the next year in the backtest.",
        watch="Averages, not promises — see the evidence on the Long bases tab.",
        src="Long-base identifier"),
    # ── Stage 2 phase (stage2.py)
    "s2_early": dict(
        what="Early in a Stage 2 advance with a strong Stage 2 Score — the best-performing group in 20 years of NSE data.",
        rules=["Stage 2: close above a 150-day SMA that rose 1%+ over 20 sessions",
               "Early phase: 0–1 maturity points (first base or two, young advance, not far from the low)",
               "Stage 2 Score 70+ (RS, slope, near the advance's peak, extension, above the 50-day, multi-year high)"],
        use="Beat NIFTY 500 by about 23% on average over the next year in the backtest; only 6% fell into Stage 4 within 6 months.",
        watch="Averages over thousands of cases — individual stocks vary.",
        src="Stage 2 phase identifier (Weinstein stages, O'Neil base count)"),
    "s2_late_weak": dict(
        what="Late in the advance and weakening — the group most likely to roll over.",
        rules=["Late phase: 5+ maturity points (4+ bases, a year or more, a very large gain, slowing 150-day line)",
               "Stage 2 Score under 55"],
        use="Tighten stops on holdings; 40% fell into Stage 4 within 6 months in the backtest.",
        watch="Some late-stage leaders keep going — it's a risk flag, not a sell signal.",
        src="Stage 2 phase identifier"),
    # ── Results (results.py)
    "res_strong": dict(
        what="This season's strong results that the market has started to reward.",
        rules=["Result Quality Score 70+ (growth, margins, consistency, clean profit)",
               "PEAD score 7+ of 9 (profit and revenue surprise, two-session reaction, strong close, near highs)",
               "Latest result of the current results season"],
        use="PEAD 7–9 beat NIFTY 500 by about 7% on average over the next 60 sessions in 22,000 NSE results.",
        watch="The PEAD score needs two sessions after the result, so very fresh results join a day or two later.",
        src="Results tab — post-earnings drift research"),
    "res_quality": dict(
        what="This season's excellent quarters: strong, broad and clean growth.",
        rules=["Result Quality Score 85+"],
        use="Next quarter's operating profit was also up 91% of the time after such results in the backtest.",
        watch="Quality says the quarter was good; the PEAD score says whether the price is likely to follow.",
        src="Results tab — Result Quality Score"),
    # ── Fund flows (mf_flows.py → mf_scans.py): every scheme's month-end portfolio, month against month
    "mf_top": dict(
        what="The stocks active mutual funds bought most in the latest month, measured against the size of the company.",
        rules=["Active funds' net buying = change in shares held, scheme by scheme, same scheme in both months",
               "Net bought 0.25%+ of the company's shares in the month",
               "At least 3 schemes bought, and more schemes bought than sold",
               "Not a new listing (IPO allotments are not counted as buying)"],
        use="Funds put serious money behind these names last month; open the stock card to see which schemes and how much.",
        watch="Portfolios are published up to 10 days after month end, so the buying is 2–6 weeks old. "
              "A month of buying is not proven to beat the market on its own — use it with price and RS.",
        src="Fund-house monthly portfolio disclosures (SEBI), read by this site"),
    "mf_streak": dict(
        what="Steady accumulation: active funds have been net buyers month after month.",
        rules=["Active funds net bought the stock in each of the last 3 or more months",
               "Net bought 0.1%+ of the company in the latest month"],
        use="Persistent buying often comes from funds building a position over time — a supply overhang is being absorbed.",
        watch="Large inflows into funds can force buying in their existing holdings; check that more than one fund house is involved.",
        src="Fund-house monthly portfolio disclosures"),
    "mf_broad": dict(
        what="Many independent fund houses adding the same stock in the same month.",
        rules=["5+ fund houses increased their total holding (all their active schemes together)",
               "At least three times as many fund houses bought as sold", "Net buying overall"],
        use="Breadth of buying is harder to explain away than one big scheme — a sign of a widely shared view.",
        watch="Sector-wide moves (e.g. a rate cut) can make every fund buy the same group.",
        src="Fund-house monthly portfolio disclosures"),
    "mf_new": dict(
        what="Fresh positions: schemes that held none of the stock a month earlier.",
        rules=["2+ fund houses started a new position in the latest month (none of their active schemes held it before)",
               "3+ schemes in all bought it for the first time", "Not a new listing"],
        use="New entries are often where a fund's research has just reached a decision — worth a look before the position is built out.",
        watch="A new scheme (NFO) investing its money is left out for its first two months, but sector funds launched "
              "earlier can still add many names at once.",
        src="Fund-house monthly portfolio disclosures"),
    "mf_lead": dict(
        what="Institutional buying behind stocks that are already leading.",
        rules=["Active funds net bought 0.1%+ of the company in the latest month, more buyers than sellers",
               "Stage 2 (above a rising 150-day line)", "RS rating 70+"],
        use="Combines demand from the people with the deepest pockets with a stock that is already acting well.",
        watch="Fund buying is reported with a lag — check the chart has not already run far since month end.",
        src="Fund-house monthly portfolio disclosures + this site's trend and RS models"),
    "mf_sold": dict(
        what="The stocks active mutual funds sold most in the latest month, measured against the size of the company.",
        rules=["Net sold 0.25%+ of the company's shares in the month", "More schemes sold than bought"],
        use="A check for holdings: heavy, broad fund selling is supply that can weigh on the price.",
        watch="Funds also sell to meet redemptions or to trim a position that grew too big — not always a view on the stock.",
        src="Fund-house monthly portfolio disclosures"),
}
