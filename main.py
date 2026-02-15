import os
import time
import traceback
import requests
import pandas as pd
import yfinance as yf
import pytz

from datetime import datetime
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

last_heartbeat = 0

# ==========================================


# ---------- Discord ----------

def send_discord(msg):

    if not WEBHOOK:
        print("Webhook missing.")
        return

    try:
        requests.post(WEBHOOK, json={"content": msg}, timeout=10)
    except:
        print("Discord failed.")


# ---------- SAFE SERIES (PERMANENT FIX) ----------

def force_series(col):
    """
    Converts ANY yfinance garbage into a clean float Series.
    This permanently fixes the 'Data must be 1-dimensional' error.
    """

    if isinstance(col, pd.DataFrame):
        col = col.iloc[:, 0]

    return pd.Series(col).astype(float)


# ---------- Fetch Data ----------

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

    df = df.astype(float)

    return df


# ---------- Indicators ----------

def indicators(df):

    close = force_series(df["Close"])
    high = force_series(df["High"])
    low = force_series(df["Low"])

    df["EMA50"] = EMAIndicator(close, 50).ema_indicator()
    df["EMA200"] = EMAIndicator(close, 200).ema_indicator()

    df["ATR"] = AverageTrueRange(high, low, close).average_true_range()
    df["ADX"] = ADXIndicator(high, low, close).adx()

    return df


# ---------- Kill Zone Filter ----------

def in_kill_zone():

    london = pytz.timezone("Europe/London")
    now = datetime.now(london)

    hour = now.hour

    # London + NY overlap
    return 7 <= hour <= 16


# ---------- News Filter ----------

def high_impact_news():

    try:
        data = requests.get(NEWS_URL, timeout=10).json()
        now = pd.Timestamp.utcnow()

        for event in data:

            if event.get("impact") != "High":
                continue

            event_time = pd.Timestamp(event["date"])

            diff = abs((event_time - now).total_seconds()) / 60

            if diff < 45:
                return True

    except:
        return False

    return False


# ---------- Liquidity Sweep ----------

def liquidity_sweep(df):

    high_roll = df["High"].rolling(20).max().iloc[-2]
    low_roll = df["Low"].rolling(20).min().iloc[-2]

    last = df.iloc[-1]

    sweep_high = last["High"] > high_roll and last["Close"] < high_roll
    sweep_low = last["Low"] < low_roll and last["Close"] > low_roll

    return sweep_high or sweep_low


# ---------- Trend Engine ----------

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


# ---------- Confidence ----------

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


# ---------- Trade Builder ----------

def build_trade(direction, df):

    last = df.iloc[-1]

    entry = last["Close"]
    atr = last["ATR"]

    stop = entry - atr if direction == "BUY" else entry + atr
    target = entry + atr * RR_RATIO if direction == "BUY" else entry - atr * RR_RATIO

    risk_amount = ACCOUNT_BALANCE * RISK_PER_TRADE
    size = risk_amount / abs(entry - stop)
    profit = abs(target - entry) * size

    conf = confidence(df)

    return entry, stop, target, size, profit, conf


# ---------- Heartbeat ----------

def heartbeat():

    global last_heartbeat

    if time.time() - last_heartbeat > HEARTBEAT_MINUTES * 60:

        send_discord("💓 ULTRA Gold Bot alive and scanning markets.")
        last_heartbeat = time.time()


# ---------- RUN BOT ----------

def run():

    send_discord("""
🚀 ULTRA GOLD BOT ONLINE

Status: RUNNING
Cloud: Railway
Asset: GOLD

Scanner is ACTIVE.
""")

    last_signal = None

    while True:

        try:

            heartbeat()

            if not in_kill_zone():
                time.sleep(600)
                continue

            if high_impact_news():
                send_discord("⚠️ High impact news soon — trading paused.")
                time.sleep(900)
                continue

            direction, df = trend()

            if direction == "NONE":
                time.sleep(SCAN_INTERVAL)
                continue

            entry, stop, target, size, profit, conf = build_trade(direction, df)

            signal_id = f"{direction}-{round(entry,1)}"

            if signal_id != last_signal and conf >= 75:

                msg = f"""
🔥 ULTRA GOLD SIGNAL 🔥

Direction: {direction}
Entry: {entry:.2f}
Stop: {stop:.2f}
Target: {target:.2f}

Confidence: {conf}/100

Position Size: {size:.3f}
Potential Profit: ${profit:.2f}
"""

                send_discord(msg)
                last_signal = signal_id

        except Exception:

            error = traceback.format_exc()
            print(error)

            send_discord(f"🚨 BOT CRASHED 🚨\n{error}")

            time.sleep(60)

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
