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


SYMBOL = "GC=F"
WEBHOOK = os.getenv("DISCORD_WEBHOOK")

SCAN_INTERVAL = 900
HEARTBEAT_MINUTES = 60

ACCOUNT_SIZE = 10000
RISK_PER_TRADE = 0.01
RR = 2.5

NEWS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

last_heartbeat = 0
last_signal = None


# ================= DISCORD =================

def send(msg):
    if WEBHOOK:
        try:
            requests.post(WEBHOOK, json={"content": msg}, timeout=10)
        except:
            print("Discord failed")


# ================= DATA SAFETY =================

def force_series(col):
    if isinstance(col, pd.DataFrame):
        col = col.iloc[:, 0]
    return pd.Series(col).astype(float)


def fetch(interval="15m", period="60d"):

    df = yf.download(
        SYMBOL,
        interval=interval,
        period=period,
        auto_adjust=True,
        progress=False
    )

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    return df.astype(float)


# ================= INDICATORS =================

def add_indicators(df):

    close = force_series(df["Close"])
    high = force_series(df["High"])
    low = force_series(df["Low"])

    df["EMA50"] = EMAIndicator(close, 50).ema_indicator()
    df["EMA200"] = EMAIndicator(close, 200).ema_indicator()
    df["ATR"] = AverageTrueRange(high, low, close).average_true_range()
    df["ADX"] = ADXIndicator(high, low, close).adx()

    return df


# ================= MARKET FILTERS =================

def kill_zone():
    london = pytz.timezone("Europe/London")
    hour = datetime.now(london).hour
    return 7 <= hour <= 16


def high_news():
    try:
        events = requests.get(NEWS_URL, timeout=10).json()
        now = pd.Timestamp.utcnow()

        for e in events:
            if e.get("impact") != "High":
                continue

            diff = abs((pd.Timestamp(e["date"]) - now).total_seconds()) / 60
            if diff < 45:
                return True
    except:
        return False

    return False


# ================= TREND ENGINE =================

def trend():

    h1 = add_indicators(fetch("1h"))
    m15 = add_indicators(fetch("15m", "7d"))

    h = h1.iloc[-1]
    m = m15.iloc[-1]

    if h["EMA50"] > h["EMA200"] and m["EMA50"] > m["EMA200"]:
        return "BUY", m15

    if h["EMA50"] < h["EMA200"] and m["EMA50"] < m["EMA200"]:
        return "SELL", m15

    return "NONE", m15


# ================= POSITION SCIENCE =================

def build_trade(direction, df):

    last = df.iloc[-1]

    entry = last["Close"]
    atr = last["ATR"]

    stop = entry - atr if direction == "BUY" else entry + atr
    target = entry + atr * RR if direction == "BUY" else entry - atr * RR

    risk_amount = ACCOUNT_SIZE * RISK_PER_TRADE
    size = risk_amount / abs(entry - stop)

    rr_real = abs(target - entry) / abs(entry - stop)

    confidence = min(100, 50 + (last["ADX"] - 20) * 2)

    return entry, stop, target, size, rr_real, confidence


# ================= BACKTEST ENGINE =================

def backtest():

    df = add_indicators(fetch("1h", "120d"))

    wins = 0
    losses = 0

    for i in range(200, len(df) - 10):

        row = df.iloc[i]

        if row["EMA50"] <= row["EMA200"]:
            continue

        entry = row["Close"]
        atr = row["ATR"]

        stop = entry - atr
        target = entry + atr * RR

        future = df.iloc[i:i+10]

        if future["Low"].min() <= stop:
            losses += 1
        elif future["High"].max() >= target:
            wins += 1

    total = wins + losses

    if total == 0:
        return

    winrate = wins / total * 100
    expectancy = (winrate/100 * RR) - ((1 - winrate/100) * 1)

    send(f"""
📊 DAILY BACKTEST REPORT

Win Rate: {winrate:.1f}%
RR: {RR}
Expectancy: {expectancy:.2f}

Trades Tested: {total}
""")


# ================= HEARTBEAT =================

def heartbeat():
    global last_heartbeat

    if time.time() - last_heartbeat > HEARTBEAT_MINUTES * 60:
        send("💓 God-Tier Gold Bot alive.")
        last_heartbeat = time.time()


# ================= RUN =================

def run():

    send("""
🚀 GOD-TIER GOLD BOT ONLINE

Institutional Scanner Active.
Risk Engine Running.
Research Engine Running.
""")

    last_backtest_day = None

    while True:

        try:

            heartbeat()

            today = datetime.utcnow().date()

            if today != last_backtest_day:
                backtest()
                last_backtest_day = today

            if not kill_zone() or high_news():
                time.sleep(600)
                continue

            direction, df = trend()

            if direction == "NONE":
                time.sleep(SCAN_INTERVAL)
                continue

            entry, stop, target, size, rr_real, confidence = build_trade(direction, df)

            global last_signal
            sig_id = f"{direction}-{round(entry,1)}"

            if sig_id != last_signal and confidence > 70:

                send(f"""
🔥 GOLD TRADE BRIEFING 🔥

Direction: {direction}

Entry: {entry:.2f}
Stop Loss: {stop:.2f}
Take Profit: {target:.2f}

Position Size: {size:.3f}
Risk: {RISK_PER_TRADE*100:.1f}%

R:R: {rr_real:.2f}
Confidence: {confidence:.0f}/100
""")

                last_signal = sig_id

        except Exception:

            send(f"🚨 BOT ERROR 🚨\n{traceback.format_exc()}")
            time.sleep(60)

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
