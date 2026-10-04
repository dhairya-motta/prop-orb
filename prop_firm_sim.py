import pandas as pd
import numpy as np
from roman_strict_bt import process_day, CONFIG

# ============================================================
#  100k PROP FIRM — REALISTIC v2
# ============================================================
#  TWO-PHASE MODEL:
#
#  PHASE 1 — EVAL
#    Pay $250 entry fee.
#    Trade toward $2,000 cumulative profit.
#    Hit $2,000  -> FUNDED  (transition, no additional fee).
#    Daily loss >= $2,000 -> BLOWN: pay $250, back to EVAL,
#                            skip rest of that calendar day.
#
#  PHASE 2 — FUNDED
#    No new fee until blown.
#    Every $2,000 profit milestone  -> PAYOUT ($1,600 = 80%).
#    Equity resets to $0 after each payout; keep trading.
#    Daily loss >= $2,000 -> BLOWN: pay $250, back to EVAL,
#                            skip rest of that calendar day.
#
#  DAILY DD CHECK (intraday):
#    For every open trade we walk the 1-min candle path and
#    track the WORST UNREALIZED equity drawdown during the
#    trade.  If  daily_equity_before_trade + worst_unrealized
#    <= -$2,000  we treat the account as blown at that point.
#
#  EXECUTION COSTS:
#    Slippage  : 0.5 pt entry slippage (applied to entry price)
#    Commission: $0.70 round-trip per MNQ contract
# ============================================================

PROP = {
    "eval_fee":         250,
    "eval_target":      2000,
    "payout_threshold": 2000,
    "daily_loss_limit": 2000,
    "payout_split":     0.80,
}

SLIPPAGE_PTS      = 0.5
MNQ_COMMISSION_RT = 0.70   # per contract, round trip ($)
MNQ_DOLLAR_PER_PT = 2.0

RISK_PROFILES = [
    {"risk": 500,  "rr": 0.20},
    {"risk": 1000, "rr": 0.20},
    {"risk": 500,  "rr": 0.25},
    {"risk": 1000, "rr": 0.25},
    {"risk": 500,  "rr": 0.33},
    {"risk": 1000, "rr": 0.33},
    {"risk": 500,  "rr": 0.50},
    {"risk": 1000, "rr": 0.50},
]

CONTRACT_SIZES = [5, 3]


def load_data():
    df0 = pd.read_csv(r'C:\Users\kingcuber\Desktop\Trading Data\usatechidxusd-m1-bid-2011-09-18T21-53-2024-01-01.csv')
    df0['datetime'] = pd.to_datetime(df0['timestamp'], unit='ms', utc=True)
    df0.set_index('datetime', inplace=True)
    df0.index = df0.index.tz_convert('US/Eastern').tz_localize(None)
    df1 = pd.read_csv(r'C:\Users\kingcuber\Desktop\Trading Data\Dataset_NQ_1min_2022_2025.csv')
    df1['datetime'] = pd.to_datetime(df1['timestamp ET'], errors='coerce')
    df1.dropna(subset=['datetime'], inplace=True)
    df1.set_index('datetime', inplace=True)
    df = pd.concat([df0[['open','high','low','close']], df1[['open','high','low','close']]])
    df = df[~df.index.duplicated(keep='last')]
    df.sort_index(inplace=True)
    df = df.loc['2020-01-01':'2025-12-31'].copy()
    return df


def get_all_setups(df):
    df['date'] = df.index.date
    days = df['date'].unique()
    all_setups = []
    for d in days:
        if d.weekday() >= 5:
            continue
        day_str = d.strftime('%Y-%m-%d')
        df_day = df.loc[day_str]
        all_setups.extend(process_day(day_str, df, df_day))
    print(f'  Total valid setups: {len(all_setups)}')
    return all_setups


def evaluate_trades(setups, df, sl_pts, tp_pts, contracts):
    """
    Evaluate each setup exit.  Returns per-trade dict including:
      pnl_pts          : net P&L in points after 0.5pt entry slippage
      worst_unreal_pts : worst unrealized P&L seen during trade (pts, <= 0)
      commission       : round-trip commission in dollars
      outcome          : TP / SL / SL_AMB / EOD
      is_ambiguous     : True if SL+TP hit on same candle
      date             : trading date string
    """
    commission = contracts * MNQ_COMMISSION_RT
    session_end = CONFIG['SESSION_END']
    results = []

    for t in setups:
        entry_time  = t['entry_time']
        entry_price = t['entry_price']
        direction   = 1 if t['bias'] == 'LONG' else -1
        day_str     = t['date']

        # Apply slippage: entry is always worse by SLIPPAGE_PTS
        slipped_entry = entry_price + SLIPPAGE_PTS * direction

        tp_price = slipped_entry + tp_pts * direction
        sl_price = slipped_entry - sl_pts * direction

        trade_data = df.loc[day_str].loc[entry_time:]
        if len(trade_data) > 0 and trade_data.index[0] == entry_time:
            trade_data = trade_data.iloc[1:]

        pnl_pts          = 0.0
        outcome          = 'EOD'
        is_ambiguous     = False
        worst_unreal_pts = 0.0   # tracks most adverse unrealized (always <= 0)

        for ts, row in trade_data.iterrows():
            if ts >= pd.Timestamp(f'{day_str} {session_end}:00'):
                break
            h, l = row['high'], row['low']

            # Worst unrealized this candle
            if direction == 1:
                unreal = l - slipped_entry
            else:
                unreal = slipped_entry - h
            if unreal < worst_unreal_pts:
                worst_unreal_pts = unreal

            sl_hit = (direction ==  1 and l <= sl_price) or (direction == -1 and h >= sl_price)
            tp_hit = (direction ==  1 and h >= tp_price) or (direction == -1 and l <= tp_price)

            if sl_hit and tp_hit:
                is_ambiguous = True
                pnl_pts = -sl_pts   # conservative
                outcome = 'SL_AMB'
                break
            elif sl_hit:
                pnl_pts = -sl_pts
                outcome = 'SL'
                break
            elif tp_hit:
                pnl_pts = tp_pts
                outcome = 'TP'
                break

        if outcome == 'EOD':
            eod = trade_data.between_time('00:00', session_end)
            if not eod.empty:
                pnl_pts = (eod.iloc[-1]['close'] - slipped_entry) * direction

        results.append({
            'date':             day_str,
            'pnl_pts':          pnl_pts,
            'worst_unreal_pts': worst_unreal_pts,
            'commission':       commission,
            'outcome':          outcome,
            'is_ambiguous':     is_ambiguous,
        })

    return results


def simulate_prop_firm(trade_list, dollar_per_pt):
    """
    Walk all trades sequentially through the two-phase prop firm model.
    """
    eval_fee      = PROP['eval_fee']
    eval_target   = PROP['eval_target']
    payout_thresh = PROP['payout_threshold']
    daily_limit   = PROP['daily_loss_limit']
    split         = PROP['payout_split']

    phase         = 'EVAL'
    equity        = 0.0
    daily_pnl     = 0.0
    cur_date      = None
    skip_date     = None       # no trading on blow day
    eval_start    = None

    evals_passed  = 0
    payouts_recv  = 0
    blown_count   = 0
    total_fees    = eval_fee   # initial eval fee
    gross_payouts = 0.0
    ambiguous     = 0

    eval_days = []
    wins = losses = 0
    streaks_w = []; streaks_l = []
    cur_streak = 0; cur_type = None

    def flush_streak():
        nonlocal cur_streak, cur_type
        if cur_type == 'W': streaks_w.append(cur_streak)
        elif cur_type == 'L': streaks_l.append(cur_streak)
        cur_streak = 0; cur_type = None

    def track(is_win):
        nonlocal cur_streak, cur_type
        t2 = 'W' if is_win else 'L'
        if cur_type == t2: cur_streak += 1
        else: flush_streak(); cur_streak = 1; cur_type = t2

    def handle_blow(date):
        nonlocal blown_count, total_fees, phase, equity, daily_pnl
        nonlocal eval_start, cur_date, skip_date
        blown_count += 1
        total_fees  += eval_fee
        if eval_start:
            elapsed = (pd.Timestamp(date) - pd.Timestamp(eval_start)).days + 1
            eval_days.append(max(elapsed, 1))
        phase     = 'EVAL'
        equity    = 0.0
        daily_pnl = 0.0
        eval_start = None
        cur_date   = None
        skip_date  = date   # no more trades today

    for t in trade_list:
        date       = t['date']
        commission = t['commission']

        # Skip rest of blow day
        if skip_date == date:
            continue

        # New trading day
        if cur_date != date:
            daily_pnl = 0.0
            cur_date  = date
            if eval_start is None:
                eval_start = date

        # Deduct commission upfront
        daily_pnl -= commission
        equity    -= commission

        # Commission alone might breach daily limit
        if daily_pnl <= -daily_limit:
            handle_blow(date)
            continue

        # ── INTRADAY DD CHECK (unrealized path) ──────────────
        # Worst equity during trade assuming prior daily P&L
        worst_case = daily_pnl + t['worst_unreal_pts'] * dollar_per_pt
        if worst_case <= -daily_limit:
            # Account would have been force-liquidated during this trade
            handle_blow(date)
            continue

        # ── Trade closed normally ─────────────────────────────
        pnl = t['pnl_pts'] * dollar_per_pt
        daily_pnl += pnl
        equity    += pnl

        is_win = pnl > 0
        track(is_win)
        if is_win: wins   += 1
        else:      losses += 1
        if t['is_ambiguous']: ambiguous += 1

        # Check realized daily limit
        if daily_pnl <= -daily_limit:
            handle_blow(date)
            continue

        # ── Phase transitions ─────────────────────────────────
        if phase == 'EVAL' and equity >= eval_target:
            evals_passed += 1
            phase  = 'FUNDED'
            equity = 0.0           # start funded phase from zero

        elif phase == 'FUNDED':
            while equity >= payout_thresh:
                gross_payouts += payout_thresh * split
                payouts_recv  += 1
                equity        -= payout_thresh   # keep overage, continue

    flush_streak()

    total    = wins + losses
    win_rate = wins / total * 100 if total > 0 else 0
    net      = gross_payouts - total_fees

    return {
        'win_rate':       win_rate,
        'avg_win_streak': round(np.mean(streaks_w), 1) if streaks_w else 0.0,
        'avg_los_streak': round(np.mean(streaks_l), 1) if streaks_l else 0.0,
        'blown':          blown_count,
        'evals_passed':   evals_passed,
        'payouts':        payouts_recv,
        'ambiguous':      ambiguous,
        'eval_avg_days':  round(np.mean(eval_days)) if eval_days else 0,
        'eval_min_days':  min(eval_days)            if eval_days else 0,
        'eval_max_days':  max(eval_days)            if eval_days else 0,
        'total_fees':     total_fees,
        'gross_earned':   gross_payouts,
        'net_profit':     net,
    }


def fmt(val):
    return f'+${val:,.0f}' if val >= 0 else f'-${abs(val):,.0f}'


def main():
    print()
    print('=' * 76)
    print('  100k PROP FIRM MATRIX v2 — Roman ORB Strategy (2020-2025)')
    print('=' * 76)
    print('  EVAL      : $250 fee | $2,000 target | $2,000 daily DD')
    print('  FUNDED    : no fee | payout every $2,000 (80%) | same DD')
    print('  Blow      : daily loss >= $2,000 -> back to EVAL next day')
    print('  Intraday  : unrealized path checked per 1-min candle')
    print('  Slippage  : 0.5pt entry | Commission: $0.70 RT/MNQ contract')
    print('=' * 76)
    print()

    print('Loading market data...')
    df = load_data()
    print('Extracting strategy setups...')
    setups = get_all_setups(df)

    total_combos = len(RISK_PROFILES) * len(CONTRACT_SIZES)
    print(f'\nRunning {len(RISK_PROFILES)} profiles x {len(CONTRACT_SIZES)} contract sizes = {total_combos} combos...\n')

    rows = []
    for rp in RISK_PROFILES:
        for contracts in CONTRACT_SIZES:
            dollar_per_pt = contracts * MNQ_DOLLAR_PER_PT
            sl_pts = rp['risk'] / dollar_per_pt
            tp_pts = sl_pts * rp['rr']
            reward_dollars = int(rp['risk'] * rp['rr'])
            label = '${:d}R/${:d}W | {:.2f}RR | {:d}MNQ'.format(
                rp['risk'], reward_dollars, rp['rr'], contracts)
            print(f'  -> {label}  (SL:{sl_pts:.1f}pt  TP:{tp_pts:.1f}pt)')

            trades = evaluate_trades(setups, df, sl_pts, tp_pts, contracts)
            s = simulate_prop_firm(trades, dollar_per_pt)

            rows.append({
                'Size':          label,
                'Win%':          f"{s['win_rate']:.1f}%",
                'Avg W':         s['avg_win_streak'],
                'Avg L':         s['avg_los_streak'],
                'Blown':         s['blown'],
                'Evals':         s['evals_passed'],
                'Payouts':       s['payouts'],
                'Amb Bars':      s['ambiguous'],
                'Eval Avg':      s['eval_avg_days'],
                'Eval Min':      s['eval_min_days'],
                'Eval Max':      s['eval_max_days'],
                'Spent':         f"${s['total_fees']:,.0f}",
                'Gross':         fmt(s['gross_earned']),
                'Net Profit':    fmt(s['net_profit']),
            })

    df_out = pd.DataFrame(rows)
    print()
    print('=' * 140)
    print(df_out.to_markdown(index=False))
    print('=' * 140)

    out_path = r'C:\Users\kingcuber\.gemini\antigravity-ide\scratch\prop_firm_matrix_v2.csv'
    df_out.to_csv(out_path, index=False)
    print(f'\nSaved -> {out_path}')


if __name__ == '__main__':
    main()
