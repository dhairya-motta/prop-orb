import pandas as pd
import numpy as np

# Roman 5/30 MIN ORB Strict Backtest

CONFIG = {
    "AMBIGUOUS_BAR_POLICY": "conservative", # "conservative", "optimistic", "skip"
    "BIAS_MODE": "LAST_COMPLETED_CANDLE", # "CURRENT_UNFINISHED_CANDLE" or "LAST_COMPLETED_CANDLE"
    "MAX_TRADES_PER_BOX": 1,
    "ALLOW_BOTH_BOXES": True,
    "SESSION_END": "16:00",
    "DEBUG": False,
    "PROFILES": [
        {"name": "Live 40:40", "tp": 40.0, "sl": 40.0},
        {"name": "Live 40:20", "tp": 40.0, "sl": 20.0},
        {"name": "25k Eval 12.5:25", "tp": 12.5, "sl": 25.0},
        {"name": "50k Eval 18.75:25", "tp": 18.75, "sl": 25.0},
        {"name": "ES Funded 8:8", "tp": 8.0, "sl": 8.0}
    ]
}

def log_debug(msg):
    if CONFIG["DEBUG"]:
        print(msg)

def get_day_trend(df, date_str, check_time="09:29"):
    # DAY TREND PROXY ASSUMPTION: 
    # We compare the close at check_time against the most recent 18:00 Globex open.
    # This mechanically simulates the discretionary "Name the day's direction" rule.
    try:
        current_dt = pd.Timestamp(f"{date_str} {check_time}")
        lookback_start = current_dt - pd.Timedelta(days=4)
        recent_data = df.loc[lookback_start:current_dt]
        
        candles_1800 = recent_data.at_time('18:00')
        if not candles_1800.empty:
            day_open_price = candles_1800.iloc[-1]['open']
        else:
            # Fallback to the first candle of the current calendar day
            day_open_price = df.loc[date_str].iloc[0]['open']
            
        check_price = recent_data.iloc[-1]['close']
        
        if check_price > day_open_price: return "UP"
        elif check_price < day_open_price: return "DOWN"
        else: return "NONE"
    except:
        return "NONE"

def get_4h_direction(df, date_str, check_time):
    # Standard CME 4H blocks starting from 18:00:
    # 18-22, 22-02, 02-06, 06-10, 10-14, 14-18
    try:
        current_dt = pd.Timestamp(f"{date_str} {check_time}")
        h = current_dt.hour
        
        if CONFIG["BIAS_MODE"] == "LAST_COMPLETED_CANDLE":
            if h < 10:
                start_h = '02:00'; end_h = '05:59'
            elif h < 14:
                start_h = '06:00'; end_h = '09:59'
            else:
                start_h = '10:00'; end_h = '13:59'
            
            # Find the most recent candle matching this block on or before current day
            recent_data = df.loc[current_dt - pd.Timedelta(days=1):current_dt]
            block_data = recent_data.between_time(start_h, end_h)
            if block_data.empty: return "NONE"
            
            # Group by date to get the last full block
            last_date = block_data.index[-1].date()
            last_block = block_data.loc[str(last_date)]
            
            c_open = last_block.iloc[0]['open']
            c_close = last_block.iloc[-1]['close']
            
            if c_close > c_open: return "UP"
            elif c_close < c_open: return "DOWN"
            else: return "NONE"
            
        else: # CURRENT_UNFINISHED_CANDLE
            if 6 <= h < 10: start_h = '06:00'
            elif 10 <= h < 14: start_h = '10:00'
            else: start_h = '06:00' 
            
            recent_data = df.loc[f"{date_str} {start_h}":current_dt]
            if recent_data.empty: return "NONE"
            
            c_open = recent_data.iloc[0]['open']
            c_close = recent_data.iloc[-1]['close']
            
            if c_close > c_open: return "UP"
            elif c_close < c_open: return "DOWN"
            else: return "NONE"
    except:
        return "NONE"

def get_7h_direction(df, date_str, check_time):
    # Standard 7H blocks starting from 18:00:
    # 18-01, 01-08, 08-15
    try:
        current_dt = pd.Timestamp(f"{date_str} {check_time}")
        h = current_dt.hour
        
        if CONFIG["BIAS_MODE"] == "LAST_COMPLETED_CANDLE":
            if h < 15:
                start_h = '01:00'; end_h = '07:59'
            else:
                start_h = '08:00'; end_h = '14:59'
                
            recent_data = df.loc[current_dt - pd.Timedelta(days=1):current_dt]
            block_data = recent_data.between_time(start_h, end_h)
            if block_data.empty: return "NONE"
            
            last_date = block_data.index[-1].date()
            last_block = block_data.loc[str(last_date)]
            
            c_open = last_block.iloc[0]['open']
            c_close = last_block.iloc[-1]['close']
            
            if c_close > c_open: return "UP"
            elif c_close < c_open: return "DOWN"
            else: return "NONE"
            
        else: # CURRENT_UNFINISHED_CANDLE
            if 8 <= h < 15: start_h = '08:00'
            else: start_h = '08:00'
            
            recent_data = df.loc[f"{date_str} {start_h}":current_dt]
            if recent_data.empty: return "NONE"
            
            c_open = recent_data.iloc[0]['open']
            c_close = recent_data.iloc[-1]['close']
            
            if c_close > c_open: return "UP"
            elif c_close < c_open: return "DOWN"
            else: return "NONE"
    except:
        return "NONE"

class RomanSetup:
    def __init__(self, box_type, date_str):
        self.box_type = box_type
        self.date_str = date_str
        self.state = "WAITING_FOR_BOX"
        self.bias = "NONE"
        self.box_high = None; self.box_low = None
        self.breakout_time = None; self.breakout_price = None
        self.entry_time = None; self.entry_price = None
        self.trades_generated = 0

def process_day(date_str, df, df_day):
    setups = []
    
    setup_935 = RomanSetup("09:35", date_str)
    setup_1100 = RomanSetup("11:00", date_str)
    
    # 1. 09:35 BOX
    setup_935.day_trend = get_day_trend(df, date_str, "09:29")
    setup_935.h4_trend = get_4h_direction(df, date_str, "09:29")
    setup_935.h7_trend = get_7h_direction(df, date_str, "09:29")
    
    if setup_935.day_trend == "UP" and setup_935.h4_trend == "UP" and setup_935.h7_trend == "UP":
        setup_935.bias = "LONG"
    elif setup_935.day_trend == "DOWN" and setup_935.h4_trend == "DOWN" and setup_935.h7_trend == "DOWN":
        setup_935.bias = "SHORT"
        
    box_935_data = df_day.between_time('09:30', '09:34') 
    if len(box_935_data) == 5 and setup_935.bias != "NONE":
        setup_935.box_high = box_935_data['high'].max()
        setup_935.box_low = box_935_data['low'].min()
        setup_935.state = "WAITING_FOR_BREAKOUT"
        
        trade_data_935 = df_day.between_time('09:35', CONFIG['SESSION_END'])
        for ts, row in trade_data_935.iterrows():
            if setup_935.trades_generated >= CONFIG["MAX_TRADES_PER_BOX"]: break
                
            if setup_935.state == "WAITING_FOR_BREAKOUT":
                if setup_935.bias == "LONG" and row['close'] > setup_935.box_high:
                    setup_935.state = "WAITING_FOR_RETEST"
                    setup_935.breakout_time = ts
                elif setup_935.bias == "SHORT" and row['close'] < setup_935.box_low:
                    setup_935.state = "WAITING_FOR_RETEST"
                    setup_935.breakout_time = ts
            
            elif setup_935.state == "WAITING_FOR_RETEST":
                if ts == setup_935.breakout_time: continue 
                
                if setup_935.bias == "LONG":
                    if row['low'] <= setup_935.box_high: 
                        if row['close'] > setup_935.box_high: 
                            setup_935.state = "ENTRY"
                            setup_935.entry_time = ts
                            setup_935.entry_price = row['close']
                            setups.append({"date": date_str, "box": "09:35", "bias": setup_935.bias, "entry_time": ts, "entry_price": row['close'], "breakout_time": setup_935.breakout_time, "day": setup_935.day_trend, "4h": setup_935.h4_trend, "7h": setup_935.h7_trend, "box_high": setup_935.box_high, "box_low": setup_935.box_low})
                            setup_935.trades_generated += 1
                            setup_935.state = "DONE"
                        else:
                            setup_935.state = "INVALID"
                            
                elif setup_935.bias == "SHORT":
                    if row['high'] >= setup_935.box_low:
                        if row['close'] < setup_935.box_low:
                            setup_935.state = "ENTRY"
                            setup_935.entry_time = ts
                            setup_935.entry_price = row['close']
                            setups.append({"date": date_str, "box": "09:35", "bias": setup_935.bias, "entry_time": ts, "entry_price": row['close'], "breakout_time": setup_935.breakout_time, "day": setup_935.day_trend, "4h": setup_935.h4_trend, "7h": setup_935.h7_trend, "box_high": setup_935.box_high, "box_low": setup_935.box_low})
                            setup_935.trades_generated += 1
                            setup_935.state = "DONE"
                        else:
                            setup_935.state = "INVALID"

    if not CONFIG["ALLOW_BOTH_BOXES"] and len(setups) > 0: return setups 
        
    # 2. 11:00 BOX
    setup_1100.day_trend = get_day_trend(df, date_str, "10:59")
    setup_1100.h4_trend = get_4h_direction(df, date_str, "10:59")
    setup_1100.h7_trend = get_7h_direction(df, date_str, "10:59")
    
    if setup_1100.day_trend == "UP" and setup_1100.h4_trend == "UP" and setup_1100.h7_trend == "UP":
        setup_1100.bias = "LONG"
    elif setup_1100.day_trend == "DOWN" and setup_1100.h4_trend == "DOWN" and setup_1100.h7_trend == "DOWN":
        setup_1100.bias = "SHORT"
        
    box_1100_data = df_day.between_time('10:30', '10:59')
    if len(box_1100_data) == 30 and setup_1100.bias != "NONE":
        setup_1100.box_high = box_1100_data['high'].max()
        setup_1100.box_low = box_1100_data['low'].min()
        setup_1100.state = "WAITING_FOR_BREAKOUT"
        
        trade_data_1100 = df_day.between_time('11:00', CONFIG['SESSION_END'])
        for ts, row in trade_data_1100.iterrows():
            if setup_1100.trades_generated >= CONFIG["MAX_TRADES_PER_BOX"]: break
                
            if setup_1100.state == "WAITING_FOR_BREAKOUT":
                if setup_1100.bias == "LONG" and row['close'] > setup_1100.box_high:
                    setup_1100.state = "WAITING_FOR_RETEST"
                    setup_1100.breakout_time = ts
                elif setup_1100.bias == "SHORT" and row['close'] < setup_1100.box_low:
                    setup_1100.state = "WAITING_FOR_RETEST"
                    setup_1100.breakout_time = ts
            
            elif setup_1100.state == "WAITING_FOR_RETEST":
                if ts == setup_1100.breakout_time: continue
                
                if setup_1100.bias == "LONG":
                    if row['low'] <= setup_1100.box_high:
                        if row['close'] > setup_1100.box_high:
                            setup_1100.state = "ENTRY"
                            setup_1100.entry_time = ts
                            setup_1100.entry_price = row['close']
                            setups.append({"date": date_str, "box": "11:00", "bias": setup_1100.bias, "entry_time": ts, "entry_price": row['close'], "breakout_time": setup_1100.breakout_time, "day": setup_1100.day_trend, "4h": setup_1100.h4_trend, "7h": setup_1100.h7_trend, "box_high": setup_1100.box_high, "box_low": setup_1100.box_low})
                            setup_1100.trades_generated += 1
                            setup_1100.state = "DONE"
                        else:
                            setup_1100.state = "INVALID"
                            
                elif setup_1100.bias == "SHORT":
                    if row['high'] >= setup_1100.box_low:
                        if row['close'] < setup_1100.box_low:
                            setup_1100.state = "ENTRY"
                            setup_1100.entry_time = ts
                            setup_1100.entry_price = row['close']
                            setups.append({"date": date_str, "box": "11:00", "bias": setup_1100.bias, "entry_time": ts, "entry_price": row['close'], "breakout_time": setup_1100.breakout_time, "day": setup_1100.day_trend, "4h": setup_1100.h4_trend, "7h": setup_1100.h7_trend, "box_high": setup_1100.box_high, "box_low": setup_1100.box_low})
                            setup_1100.trades_generated += 1
                            setup_1100.state = "DONE"
                        else:
                            setup_1100.state = "INVALID"

    return setups

def backtest_roman_strict():
    print("Loading data...")
    df0 = pd.read_csv(r'C:\Users\kingcuber\Desktop\Trading Data\usatechidxusd-m1-bid-2011-09-18T21-53-2024-01-01.csv')
    df0['datetime'] = pd.to_datetime(df0['timestamp'], unit='ms', utc=True)
    df0.set_index('datetime', inplace=True)
    df0.index = df0.index.tz_convert('US/Eastern').tz_localize(None)
    
    df1 = pd.read_csv(r"C:\Users\kingcuber\Desktop\Trading Data\Dataset_NQ_1min_2022_2025.csv")
    df1['datetime'] = pd.to_datetime(df1['timestamp ET'], errors='coerce')
    df1.dropna(subset=['datetime'], inplace=True)
    df1.set_index('datetime', inplace=True)
    
    df = pd.concat([df0[['open', 'high', 'low', 'close']], df1[['open', 'high', 'low', 'close']]])
    df = df[~df.index.duplicated(keep='last')]
    df.sort_index(inplace=True)
    
    df = df.loc['2020-01-01':'2025-12-31'].copy()
    
    df['date'] = df.index.date
    days = df['date'].unique()
    
    all_trades = []
    
    print(f"Scanning for setups... (BIAS_MODE: {CONFIG['BIAS_MODE']})")
    for i in range(len(days)):
        if days[i].weekday() >= 5: continue
        
        day_str = days[i].strftime('%Y-%m-%d')
        df_day = df.loc[day_str]
        
        setups = process_day(day_str, df, df_day)
        all_trades.extend(setups)
        
    print(f"Total valid setups found: {len(all_trades)}")
    
    # Process Exits
    results = []
    
    # We will log the detailed trades for the first profile only to avoid duplicating 5x
    primary_profile = CONFIG["PROFILES"][0]
    detailed_trades = []
    
    for prof in CONFIG["PROFILES"]:
        wins = 0; losses = 0; total_pts = 0
        ambiguous_count = 0
        
        for t in all_trades:
            entry_time = t['entry_time']
            entry_price = t['entry_price']
            direction = 1 if t['bias'] == "LONG" else -1
            
            tp_price = entry_price + (prof['tp'] * direction)
            sl_price = entry_price - (prof['sl'] * direction)
            
            day_str = t['date']
            trade_data = df.loc[day_str].loc[entry_time:]
            
            if len(trade_data) > 0 and trade_data.index[0] == entry_time:
                trade_data = trade_data.iloc[1:]
                
            pnl = 0
            exit_reason = "EOD"
            exit_time = entry_time # Default
            exit_price = entry_price
            
            for ts, row in trade_data.iterrows():
                if ts >= pd.Timestamp(f"{day_str} {CONFIG['SESSION_END']}:00"):
                    break 
                    
                h, l = row['high'], row['low']
                sl_hit = False
                tp_hit = False
                
                if direction == 1:
                    if l <= sl_price: sl_hit = True
                    if h >= tp_price: tp_hit = True
                else:
                    if h >= sl_price: sl_hit = True
                    if l <= tp_price: tp_hit = True
                    
                if sl_hit and tp_hit:
                    ambiguous_count += 1
                    exit_time = ts
                    if CONFIG["AMBIGUOUS_BAR_POLICY"] == "conservative":
                        pnl = -prof['sl']
                        exit_price = sl_price
                        exit_reason = "SL (Ambiguous)"
                        break
                    elif CONFIG["AMBIGUOUS_BAR_POLICY"] == "optimistic":
                        pnl = prof['tp']
                        exit_price = tp_price
                        exit_reason = "TP (Ambiguous)"
                        break
                    else:
                        exit_reason = "SKIPPED (Ambiguous)"
                        break
                elif sl_hit:
                    pnl = -prof['sl']
                    exit_price = sl_price
                    exit_time = ts
                    exit_reason = "SL"
                    break
                elif tp_hit:
                    pnl = prof['tp']
                    exit_price = tp_price
                    exit_time = ts
                    exit_reason = "TP"
                    break
                    
            if pnl == 0 and exit_reason == "EOD":
                if len(trade_data) > 0:
                    eod_data = trade_data.between_time('00:00', CONFIG['SESSION_END'])
                    if not eod_data.empty:
                        eod_close = eod_data.iloc[-1]['close']
                        exit_time = eod_data.index[-1]
                        exit_price = eod_close
                        pnl = (eod_close - entry_price) * direction
                    else:
                        pnl = 0
                else:
                    pnl = 0
                    
            if prof['name'] == primary_profile['name'] and exit_reason != "SKIPPED (Ambiguous)":
                detailed_trades.append({
                    "Date": day_str,
                    "Box": t['box'],
                    "Direction": t['bias'],
                    "Day_Trend": t['day'],
                    "4H_Trend": t['4h'],
                    "7H_Trend": t['7h'],
                    "Box_High": t['box_high'],
                    "Box_Low": t['box_low'],
                    "Breakout_Time": t['breakout_time'].time(),
                    "Entry_Time": entry_time.time(),
                    "Entry_Price": entry_price,
                    "SL_Price": sl_price,
                    "TP_Price": tp_price,
                    "Exit_Time": exit_time.time() if hasattr(exit_time, 'time') else exit_time,
                    "Exit_Reason": exit_reason,
                    "PnL_Points": pnl
                })
                    
            if exit_reason != "SKIPPED (Ambiguous)":
                if pnl > 0: wins += 1
                else: losses += 1
                total_pts += pnl
                
        total = wins + losses
        win_rate = (wins/total*100) if total > 0 else 0
        
        results.append({
            "Profile": prof['name'],
            "Trades": total,
            "Wins": wins,
            "Losses": losses,
            "Win Rate": f"{win_rate:.1f}%",
            "Net Pts": f"{total_pts:.1f}",
            "Ambiguous": ambiguous_count
        })
        
    df_res = pd.DataFrame(results)
    print("\n" + df_res.to_markdown(index=False))
    
    # Save detailed trades
    df_trades = pd.DataFrame(detailed_trades)
    df_trades.to_csv("roman_trades_log.csv", index=False)
    print(f"\nSaved detailed trade log to roman_trades_log.csv for profile '{primary_profile['name']}'")
    
if __name__ == '__main__':
    backtest_roman_strict()
