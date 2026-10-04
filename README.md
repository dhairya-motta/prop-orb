# Roman ORB — Prop Firm Backtest (NQ Futures, 2020–2025)

> A rigorous, look-ahead-bias-free backtest of Roman's **5-Minute / 30-Minute Opening Range Breakout** strategy on NQ (Nasdaq-100 Futures / Micro NQ), simulated against a **100k prop firm account** over 5 years (Jan 2020 – Dec 2025).

---

## Strategy Overview

Roman's ORB (Opening Range Breakout) is an intraday NQ strategy built around two daily boxes and a triple-filter directional bias.

### Two Boxes per Day

| Box | Formation Window | Trade Window |
|-----|-----------------|--------------|
| **09:35 Box** | 09:30–09:34 ET (5 candles) | 09:35–16:00 ET |
| **11:00 Box** | 10:30–10:59 ET (30 candles) | 11:00–16:00 ET |

### Triple-Filter Bias (must ALL agree)

All three filters are evaluated **strictly on completed candles** — no look-ahead bias.

| Filter | Description | Evaluated At |
|--------|-------------|-------------|
| **Day Trend** | Current price vs most recent 18:00 Globex open | 09:29 / 10:59 ET |
| **4H Block** | Last *completed* CME 4H block direction (02–06, 06–10, 10–14) | 09:29 / 10:59 ET |
| **7H Block** | Last *completed* CME 7H block direction (01–08) | 09:29 / 10:59 ET |

> **LONG** only when Day + 4H + 7H all = UP  
> **SHORT** only when Day + 4H + 7H all = DOWN  
> No trade if any filter disagrees

### Entry Sequence (Strict State Machine)

```
Box freezes at 09:35 (or 11:00)
        ↓
1-min candle CLOSES outside box high/low  →  BREAKOUT
        ↓
Next candle(s) pull back and TOUCH the broken level
        ↓
That same candle CLOSES back outside the level  →  ENTRY
        ↓
If candle closes inside box on retest  →  SETUP INVALID
```

**Rules enforced in code:**
- Breakout requires a 1-min **close** outside the box (not just a wick)
- Breakout candle cannot simultaneously be the retest candle
- Failed retest (close inside box) permanently invalidates the setup
- Maximum **1 trade per box** per day
- Both boxes can trigger on the same day (independent)

---

## Backtest Implementation (`roman_strict_bt.py`)

### What Is Correctly Implemented

| Rule | Implementation |
|------|---------------|
| 09:35 box frozen at 09:35 | `between_time('09:30','09:34')` — exactly 5 candles required |
| 11:00 box frozen at 11:00 | `between_time('10:30','10:59')` — exactly 30 candles required |
| Breakout = 1-min close | `row['close'] > box_high` (not high/low wick) |
| Retest sequence | Full state machine: WAITING_FOR_BREAKOUT → WAITING_FOR_RETEST → ENTRY/INVALID |
| No same-candle breakout+entry | `if ts == breakout_time: continue` |
| Bias uses completed candles | `BIAS_MODE = "LAST_COMPLETED_CANDLE"` |
| Ambiguous bar (SL+TP same candle) | Conservative: SL wins, counted separately |
| Entry price | Close of retest candle |
| Session close | 16:00 ET hard stop |

### Known Assumptions (Documented)

- **Day Trend** is a mechanical proxy (compare current price to last 18:00 Globex open). Roman uses discretionary reading — this is the closest systematic approximation.
- Entry is at the **close** of the retest candle. In live trading, there will be slight additional slippage.
- Data from two merged sources (2011–2024 CSV + 2022–2025 CSV); duplicates resolved with `keep='last'`.

### Backtest Results (5 Profiles, 602 Trades)

> Dataset: NQ 1-minute bid data, Jan 2020 – Dec 2025  
> Conservative ambiguous-bar policy (SL wins if both hit same candle)

| Profile | Trades | Wins | Win Rate | Net Points |
|---------|--------|------|----------|-----------|
| Live 40:40 | 602 | 303 | 50.3% | +1,444 pts |
| Live 40:20 | 602 | 229 | 38.0% | +1,235 pts |
| 25k Eval 12.5:25 | 602 | 398 | 66.1% | −86 pts |
| 50k Eval 18.75:25 | 602 | 352 | 58.5% | +331 pts |

---

## Prop Firm Simulation (`prop_firm_sim.py`)

### Model: 100k Account — Intraday DD

```
EVAL PHASE
  Entry fee   : $250
  Target      : $2,000 cumulative profit
  Daily limit : $2,000 max loss in one trading day
  Pass eval → FUNDED (no extra fee)

FUNDED PHASE
  No entry fee until blown
  Every $2,000 profit milestone → PAYOUT (you keep 80% = $1,600)
  Equity resets after each payout; keep trading same account
  Daily loss ≥ $2,000 → BLOWN: pay $250, back to EVAL, next day

EXECUTION COSTS
  Slippage   : 0.5 pt entry slippage per trade
  Commission : $0.70 round-trip per MNQ contract
```

### Intraday DD — How It Is Checked

The simulator does **not** just look at end-of-trade P&L. For each open trade it walks the 1-minute candle path and computes the **worst unrealized drawdown** seen during the trade:

```python
# Long trade: worst unrealized = (candle_low - entry_price)
# Short trade: worst unrealized = (entry_price - candle_high)

worst_case_daily = daily_pnl_before_trade + worst_unrealized * dollar_per_pt
if worst_case_daily <= -2000:
    # Account blown mid-trade
```

This catches intraday force-liquidation scenarios that end-of-bar checking misses.

---

## Full Results Matrix (2020–2025)

> 8 risk/RR profiles × 2 contract sizes (5 MNQ and 3 MNQ) = 16 combinations

**Column Guide:**

| Column | Meaning |
|--------|---------|
| Size | Risk per trade / Win per trade / RR ratio / Contracts |
| Win% | % of closed trades that were profitable |
| Avg W / Avg L | Average consecutive win / loss streak |
| Blown | Times daily DD limit was breached (across both phases) |
| Evals | Times the $2,000 eval target was hit → account funded |
| Payouts | Total $1,600 payouts received while funded |
| Amb Bars | Trades where SL + TP hit on same candle (conservative = SL) |
| Eval Avg | Average calendar days per eval cycle |
| Spent | Total eval fees paid (initial + restarts) |
| Gross | Total gross payouts before fee deduction |
| Net Profit | **Gross − Spent** — actual 5-year take-home |

### Results Table

| Size | Win% | Avg W | Avg L | Blown | Evals | Payouts | Amb | Eval Avg | Spent | Gross | Net Profit |
|:-----|:-----|------:|------:|------:|------:|--------:|----:|---------:|------:|------:|----------:|
| $500R/$100W \| 0.20RR \| 5MNQ | 81.0% | 5.1 | 1.2 | 1 | 1 | 0 | 1 | 1280d | $500 | +$0 | **-$500** |
| $500R/$100W \| 0.20RR \| 3MNQ | 83.5% | 5.9 | 1.2 | 1 | 1 | 2 | 0 | 1280d | $500 | +$3,200 | **+$2,700** |
| $1000R/$200W \| 0.20RR \| 5MNQ | 82.2% | 5.4 | 1.2 | 2 | 2 | 4 | 0 | 638d | $750 | +$6,400 | **+$5,650** |
| $1000R/$200W \| 0.20RR \| 3MNQ | 76.9% | 4.3 | 1.3 | 1 | 2 | 2 | 0 | 1280d | $500 | +$3,200 | **+$2,700** |
| $500R/$125W \| 0.25RR \| 5MNQ | 78.4% | 4.4 | 1.2 | 1 | 1 | 1 | 0 | 1280d | $500 | +$1,600 | **+$1,100** |
| $500R/$125W \| 0.25RR \| 3MNQ | 79.5% | 4.7 | 1.2 | 1 | 1 | 3 | 0 | 1280d | $500 | +$4,800 | **+$4,300** |
| $1000R/$250W \| 0.25RR \| 5MNQ | 78.2% | 4.4 | 1.2 | 2 | 3 | 4 | 0 | 638d | $750 | +$6,400 | **+$5,650** |
| $1000R/$250W \| 0.25RR \| 3MNQ | 74.5% | 3.9 | 1.3 | 2 | 3 | 6 | 0 | 640d | $750 | +$9,600 | **+$8,850** |
| $500R/$165W \| 0.33RR \| 5MNQ | 75.4% | 3.8 | 1.3 | 1 | 1 | 3 | 0 | 1280d | $500 | +$4,800 | **+$4,300** |
| $500R/$165W \| 0.33RR \| 3MNQ | 73.7% | 3.6 | 1.3 | 1 | 1 | 2 | 0 | 1280d | $500 | +$3,200 | **+$2,700** |
| $1000R/$330W \| 0.33RR \| 5MNQ | 73.5% | 3.6 | 1.3 | 2 | 3 | 7 | 0 | 638d | $750 | +$11,200 | **+$10,450** |
| $1000R/$330W \| 0.33RR \| 3MNQ | 68.2% | 3.2 | 1.5 | 2 | 2 | 4 | 0 | 640d | $750 | +$6,400 | **+$5,650** |
| $500R/$250W \| 0.50RR \| 5MNQ | 66.7% | 2.8 | 1.4 | 1 | 1 | 5 | 0 | 1280d | $500 | +$8,000 | **+$7,500** |
| $500R/$250W \| 0.50RR \| 3MNQ | 68.4% | 3.1 | 1.4 | 1 | 2 | 6 | 0 | 1280d | $500 | +$9,600 | **+$9,100** |
| $1000R/$500W \| 0.50RR \| 5MNQ | 67.1% | 3.0 | 1.5 | 4 | 4 | **14** | 0 | 486d | $1,250 | +$22,400 | **+$21,150** 🏆 |
| $1000R/$500W \| 0.50RR \| 3MNQ | 63.4% | 2.9 | 1.7 | 4 | 5 | 7 | 0 | 316d | $1,250 | +$11,200 | **+$9,950** |

### 🏆 Best Profile Explained: `$1000R/$500W | 0.50RR | 5MNQ`

```
Instrument      : 5 × MNQ (Micro NQ) = $10 per point
Risk per trade  : $1,000  (100-point SL)
Reward per trade: $500    (50-point TP)
Win rate        : 67.1%

Raw EV per trade = (0.671 × $500) − (0.329 × $1,000) ≈ +$6.50
After costs     : −$8.50 (slippage + commission per trade)

The prop firm structure is the real edge:
  → 4 eval passes over 5 years
  → While funded, took 14 × $1,600 payouts = $22,400 gross
  → Total fees paid: $1,250 (5 × $250)
  → Net take-home: $21,150

Average time to pass an eval: 486 calendar days
Fastest eval: 23 days | Slowest: 813 days
Accounts blown: 4 (across both eval and funded phases)
```

---

## Setup & Usage

### Requirements

```bash
pip install pandas numpy tabulate
```

### Data Format

The scripts expect two CSV files with 1-minute NQ bid data in US/Eastern time:

```
File 1: usatechidxusd-m1-bid-*.csv
  Columns: timestamp (ms UTC), open, high, low, close

File 2: Dataset_NQ_1min_2022_2025.csv
  Columns: timestamp ET, open, high, low, close
```

Update the file paths in `load_data()` inside each script to point to your data.

### Running the Strategy Backtest

```bash
python roman_strict_bt.py
```

Outputs a profile summary table + `roman_trades_log.csv` with every trade's entry, exit, direction, and P&L.

### Running the Prop Firm Matrix

```bash
python prop_firm_sim.py
```

Outputs the 16-combination matrix + saves `prop_firm_matrix_v2.csv`.

### Configuring the Prop Firm Rules

Edit the `PROP` dict at the top of `prop_firm_sim.py`:

```python
PROP = {
    "eval_fee":         250,    # Cost per evaluation attempt ($)
    "eval_target":      2000,   # Profit needed to get funded ($)
    "payout_threshold": 2000,   # Profit per payout while funded ($)
    "daily_loss_limit": 2000,   # Intraday DD limit ($)
    "payout_split":     0.80,   # Trader keeps 80%
}
```

### Adjusting Risk Profiles

Edit `RISK_PROFILES` and `CONTRACT_SIZES`:

```python
RISK_PROFILES = [
    {"risk": 500,  "rr": 0.20},   # Risk $500, TP = 20% of SL
    {"risk": 1000, "rr": 0.50},   # Risk $1000, TP = 50% of SL
    # Add more...
]

CONTRACT_SIZES = [5, 3]   # MNQ contracts per trade
```

---

## Important Caveats

> **This is a research backtest, not a guarantee of future performance.**

1. **Day Trend is a proxy** — Roman uses discretionary reading of market structure. This backtest uses a mechanical rule (price vs 18:00 Globex open). Results may differ from discretionary application.

2. **Entry at candle close** — In live trading, you submit your order after the 1-minute candle closes and fill at the next available price. Some additional slippage beyond the 0.5pt modeled here is realistic.

3. **In-sample data** — The full 2020–2025 period was used for both parameter exploration and results. Do not treat the best-performing profile as an unbiased estimate of future performance without an out-of-sample test on unseen data (e.g., hold out 2024–2025).

4. **Prop firm rules vary** — The EVAL → FUNDED → payout model used here is a reasonable approximation of firms like Topstep, Apex, or similar. Your specific firm may have different trailing DD rules, scaling plans, or consistency requirements.

5. **No position sizing ramp** — This backtest uses fixed contract sizes throughout. Real trading would likely involve scaling up as the funded account grows.

---

## File Reference

| File | Purpose |
|------|---------|
| `roman_strict_bt.py` | Core strategy: setup detection, state machine, exit simulation |
| `prop_firm_sim.py` | Prop firm simulation: two-phase model, intraday DD, full matrix |

---

## Credits

Strategy concept by **Roman** (YouTube / Trading Community).  
Backtest implementation and prop firm simulation by this repository.

*Not financial advice. For research and educational purposes only.*
