import os
import time
import requests
import pandas as pd
import yfinance as yf

from ta.trend import EMAIndicator, ADXIndicator
from ta.volatility import AverageTrueRange


# ================= CONFIG =================

SYMBOL = "GC=F"
SCAN_INTERVAL = 900
RR_RATIO = 2
ACCOUNT_BALANCE = 10000
RISK_PER_TRADE = 0.01

WEBHOOK = os.getenv("DISCORD_WEBHOOK")
HEARTBEAT_MINUTES = int(os.getenv("HEARTBEAT_MINUTES", 60))

NEWS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# ==========================================


# ---------- Discord ----------

def send_discord(msg):

    if not WEBHOOK:
        print("No webhook configured.")
        return

    try:
        requests.post(WEBHOOK, json={"content": msg}, timeout=10)
    except:
        print("Discord send failed.")


# ---------- Heartbeat ----------

last_heartbeat = 0

def heartbeat():

    global last_heartbeat

    if time.time() - last_heartbeat > HEARTBEAT_MINUTES * 60:
        send_discord("💓 Gold ULTRA Bot is running.")
        last_heartbeat = time.time()


# ---------- News Filter ----------

def high_impact_news_soon():

    try:
        data = requests.get(NEWS_URL, timeout=10).json()

        now = pd.Timestamp.utcnow()

        for event in data:

            if event.get("impact") != "High":
                continue

            event_time = pd.Timestamp(event["date"])

            diff = abs((event_time - now).total_seconds()) / 60

            # avoid trading 45 minutes before/after
            if diff < 45:
                return True

    except:
        return False

    return False


# ---------- Data ----------

def fetch(interval, period):

    df = yf.download(
        SYMBOL,
        interval=interval,
        period=period,
        auto_adjust=True,
        progress=False
    )

    if df.empty:
        raise ValueError("Market data empty.")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    return df


# ---------- Indicators ----------

def indicators(df):

    close = df["Close"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()

    df["EMA50"] = EMAIndicator(close, 50).ema_indicator()
    df["EMA200"] = EMAIndicator(close, 200).ema_indicator()

    df["ATR"] = AverageTrueRange(high, low, close).average_true_range()
    df["ADX"] = ADXIndicator(high, low, close).adx()

    return df


# ---------- Liquidity Sweep ----------

def liquidity_sweep(df):

    recent_high = df["High"].rolling(20).max().iloc[-2]
    recent_low = df["Low"].rolling(20).min().iloc[-2]

    last = df.iloc[-1]

    sweep_high = last["High"] > recent_high and last["Close"] < recent_high
    sweep_low = last["Low"] < recent_low and last["Close"] > recent_low

    return sweep_high or sweep_low


# ---------- Trend ----------

def trend():

    h1 = indicators(fetch("1h", "60d"))
    m15 = indicators(fetch("15m", "7d"))

    h = h1.iloc[-1]
    m = m15.iloc[-1]

    bullish = h["EMA50"] > h["EMA200"] and m["EMA50"] > m["EMA200"]
    bearish = h["EMA50"] < h["EMA200"] and m["EMA50"] < m["EMA200"]

    if bullish:
        return "BUY", m15
    if bearish:
        return "SELL", m15

    return "NONE", m15


# ---------- Confidence Engine ----------

def confidence(df):

    last = df.iloc[-1]

    score = 50

    if last["ADX"] > 25:
        score += 20

    atr_percent = (last["ATR"] / last["Close"]) * 100
    if atr_percent > 0.7:
        score += 15

    if liquidity_sweep(df):
        score += 15

    return min(score, 100)


# ---------- Trade ----------

def build_trade(direction, df):

    last = df.iloc[-1]

    entry = last["Close"]
    atr = last["ATR"]

    if direction == "BUY":
        stop = entry - atr
        target = entry + atr * RR_RATIO
    else:
        stop = entry + atr
        target = entry - atr * RR_RATIO

    risk_amount = ACCOUNT_BALANCE * RISK_PER_TRADE
    size = risk_amount / abs(entry - stop)
    profit = abs(target - entry) * size

    conf = confidence(df)

    return entry, stop, target, size, profit, conf


# ---------- Main Loop ----------

def run():

    send_discord("🚀 Gold ULTRA Bot deployed and running.")

    last_signal = None

    while True:

        try:

            heartbeat()

            if high_impact_news_soon():
                print("High impact news soon — skipping trades.")
                time.sleep(600)
                continue

            direction, df = trend()

            if direction == "NONE":
                time.sleep(SCAN_INTERVAL)
                continue

            entry, stop, target, size, profit, conf = build_trade(direction, df)

            signal_id = f"{direction}-{round(entry,1)}"

            if signal_id != last_signal and conf >= 75:

                msg = f"""
🔥 **ULTRA GOLD SIGNAL**

Direction: {direction}
Entry: {entry:.2f}
Stop: {stop:.2f}
Target: {target:.2f}

Confidence: {conf}/100

Position Size: {size:.3f}
Potential Profit: ${profit:.2f}

Bot Status: ACTIVE ✅
"""

                send_discord(msg)
                last_signal = signal_id

        except Exception as e:

            send_discord(f"🚨 BOT CRASHED 🚨\n{str(e)}")
            time.sleep(60)

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
