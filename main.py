import yfinance as yf
import pandas as pd
import requests
import time
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange


# ================= CONFIG =================

SYMBOL = "GC=F"  # Gold futures
DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1472646622021292073/uFperB-67bB3T0zHbiJXzNDniZxwbyOYYTdIn0z_lPIz3zwpSTbC4ipkWqJMceeVzYj0"

ACCOUNT_BALANCE = 10000
RISK_PER_TRADE = 0.01
RR_RATIO = 2

SCAN_INTERVAL = 900  # seconds (15 minutes)

# ==========================================


def send_discord(message):
    payload = {"content": message}
    try:
        requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    except Exception as e:
        print("Discord error:", e)


def fetch_data(interval, period):
    df = yf.download(SYMBOL, interval=interval, period=period, progress=False)
    df.dropna(inplace=True)
    return df


def add_indicators(df):
    df['EMA50'] = EMAIndicator(df['Close'], window=50).ema_indicator()
    df['EMA200'] = EMAIndicator(df['Close'], window=200).ema_indicator()

    atr = AverageTrueRange(
        high=df['High'],
        low=df['Low'],
        close=df['Close'],
        window=14
    )

    df['ATR'] = atr.average_true_range()
    return df


# -------- Multi-Timeframe Trend --------

def trend_direction():
    h4 = add_indicators(fetch_data("1h", "60d"))
    m15 = add_indicators(fetch_data("15m", "7d"))

    h4_last = h4.iloc[-1]
    m15_last = m15.iloc[-1]

    bullish_h4 = h4_last['EMA50'] > h4_last['EMA200']
    bullish_m15 = m15_last['EMA50'] > m15_last['EMA200']

    bearish_h4 = h4_last['EMA50'] < h4_last['EMA200']
    bearish_m15 = m15_last['EMA50'] < m15_last['EMA200']

    if bullish_h4 and bullish_m15:
        return "BUY", m15_last
    elif bearish_h4 and bearish_m15:
        return "SELL", m15_last
    else:
        return "NONE", m15_last


# -------- Trade Builder --------

def build_trade(direction, candle):
    entry = candle['Close']
    atr = candle['ATR']

    if direction == "BUY":
        stop = entry - atr
        target = entry + atr * RR_RATIO
    else:
        stop = entry + atr
        target = entry - atr * RR_RATIO

    risk_amount = ACCOUNT_BALANCE * RISK_PER_TRADE
    risk_per_unit = abs(entry - stop)

    position_size = risk_amount / risk_per_unit
    potential_profit = abs(target - entry) * position_size

    score = trade_score(atr, entry)

    return {
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "size": position_size,
        "profit": potential_profit,
        "score": score
    }


# -------- Trade Quality Score --------

def trade_score(atr, price):
    volatility_percent = (atr / price) * 100

    if volatility_percent > 1.2:
        return "A+ (High momentum)"
    elif volatility_percent > 0.8:
        return "A (Tradable)"
    elif volatility_percent > 0.5:
        return "B (Moderate)"
    else:
        return "C (Low volatility)"


# -------- Format Alert --------

def format_alert(trade):
    return f"""
🚨 GOLD TRADE SIGNAL 🚨

Direction: **{trade['direction']}**
Entry: {trade['entry']:.2f}
Stop Loss: {trade['stop']:.2f}
Take Profit: {trade['target']:.2f}

Position Size: {trade['size']:.3f}
Potential Profit: ${trade['profit']:.2f}

Trade Quality: {trade['score']}
Risk:Reward = 1:{RR_RATIO}
"""


# -------- Main Scanner Loop --------

def run_bot():
    print("Gold bot running...")

    last_signal = None

    while True:
        try:
            direction, candle = trend_direction()

            if direction != "NONE":
                trade = build_trade(direction, candle)

                signal_id = f"{direction}-{round(trade['entry'],2)}"

                # Prevent duplicate spam
                if signal_id != last_signal:
                    alert = format_alert(trade)

                    print(alert)
                    send_discord(alert)

                    last_signal = signal_id

            else:
                print("No aligned trend...")

        except Exception as e:
            print("Bot error:", e)

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run_bot()
