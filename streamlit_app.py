
import streamlit as st
import pandas as pd
import urllib.request
import json
from datetime import datetime, timezone

# ==========================================
# ATB 99 | PROFESSIONAL TRADING TERMINAL
# VERSION 1.2
# PAPER TRADING ONLY
# ==========================================

st.set_page_config(
    page_title="ATB 99 | Trading Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------------- DESIGN ----------------

st.markdown("""
<style>
.stApp {
    background: #0b0f14;
    color: #e7edf5;
}
header[data-testid="stHeader"] {
    background: #0b0f14;
}
.block-container {
    max-width: 1450px;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}
[data-testid="stMetric"] {
    background: #151c25;
    border: 1px solid #273342;
    border-radius: 13px;
    padding: 17px;
}
[data-testid="stMetricLabel"] {
    color: #93a4b8;
}
[data-testid="stMetricValue"] {
    color: #f1f5f9;
}
div.stButton > button {
    background: #00c78a;
    color: #06130e;
    border: 0;
    border-radius: 9px;
    font-weight: 700;
    min-height: 45px;
    width: 100%;
}
div.stButton > button:hover {
    background: #00e5a0;
    color: #06130e;
}
.terminal-header {
    background: linear-gradient(120deg,#14232c,#101923);
    border: 1px solid #263c49;
    border-radius: 16px;
    padding: 22px;
    margin-bottom: 18px;
}
.terminal-title {
    font-size: 30px;
    font-weight: 800;
    color: #f4f8fc;
}
.terminal-sub {
    color: #8da4b6;
    font-size: 13px;
}
.section-title {
    color: #e5edf5;
    font-size: 19px;
    font-weight: 700;
    margin-top: 15px;
}
.status {
    display: inline-block;
    padding: 6px 12px;
    background: #123d31;
    color: #00e5a0;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 700;
}
.panel {
    background: #121922;
    border: 1px solid #273342;
    border-radius: 13px;
    padding: 16px;
    margin-bottom: 10px;
}
.small-label {
    color: #8496a8;
    font-size: 12px;
}
.green {color:#00d99a;}
.red {color:#ff647c;}
.muted {color:#91a0af;}
hr {border-color:#273342;}
</style>
""", unsafe_allow_html=True)

# ---------------- CONFIG ----------------

START_BALANCE = 1000.0
FEE_RATE = 0.001
RISK_PER_TRADE = 0.005
MAX_POSITION = 0.25
DAILY_LOSS_LIMIT = 0.02

MARKETS = {
    "BTC/USDT": "XBTUSDT",
    "ETH/USDT": "ETHUSDT"
}

# ---------------- SESSION ----------------

defaults = {
    "cash": START_BALANCE,
    "positions": {},
    "trades": [],
    "realized": 0.0,
    "daily_pnl": 0.0,
    "daily_date": datetime.now(timezone.utc).date().isoformat(),
    "last_processed": {},
    "equity_history": [],
    "halted": False
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ---------------- DATA ----------------

def get_market(symbol):
    pair = MARKETS[symbol]
    url = (
        "https://api.kraken.com/0/public/OHLC"
        f"?pair={pair}&interval=60"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ATB99/1.2"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode())

    if payload.get("error"):
        raise Exception(str(payload["error"]))

    rows = next(
        value for key, value in payload["result"].items()
        if key != "last" and isinstance(value, list)
    )

    # Exclude unfinished candle
    rows = rows[:-1]

    if len(rows) < 55:
        raise Exception("Insufficient candle history")

    return [{
        "time": int(x[0]),
        "open": float(x[1]),
        "high": float(x[2]),
        "low": float(x[3]),
        "close": float(x[4]),
        "volume": float(x[6])
    } for x in rows]


# ---------------- INDICATORS ----------------

def ema(values, period):
    alpha = 2 / (period + 1)
    result = [values[0]]

    for value in values[1:]:
        result.append(
            alpha * value + (1-alpha) * result[-1]
        )

    return result


def rsi(values, period=14):
    changes = [
        values[i] - values[i-1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period-1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period-1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    return 100 - 100 / (1 + avg_gain / avg_loss)


def atr(candles, period=14):
    ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i-1]

        ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        ))

    value = sum(ranges[:period]) / period

    for item in ranges[period:]:
        value = (
            value * (period-1) + item
        ) / period

    return value


def analyze(symbol):
    candles = get_market(symbol)
    close = [x["close"] for x in candles]

    fast = ema(close, 20)
    slow = ema(close, 50)

    current_rsi = rsi(close)
    current_atr = atr(candles)

    signal = "HOLD"

    if (
        fast[-2] <= slow[-2]
        and fast[-1] > slow[-1]
        and 45 <= current_rsi <= 68
    ):
        signal = "BUY"

    elif fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
        signal = "SELL"

    chart = pd.DataFrame({
        "Time": [
            datetime.fromtimestamp(x["time"], timezone.utc)
            for x in candles[-100:]
        ],
        "Price": close[-100:],
        "EMA 20": fast[-100:],
        "EMA 50": slow[-100:]
    })

    return {
        "price": close[-1],
        "rsi": current_rsi,
        "ema20": fast[-1],
        "ema50": slow[-1],
        "atr": current_atr,
        "signal": signal,
        "time": candles[-1]["time"],
        "high": candles[-1]["high"],
        "low": candles[-1]["low"],
        "chart": chart
    }


# ---------------- TRADING ENGINE ----------------

def close_position(symbol, price, reason):
    position = st.session_state.positions[symbol]
    qty = position["qty"]

    exit_fee = qty * price * FEE_RATE

    pnl = (
        qty * (price - position["entry"])
        - position["entry_fee"]
        - exit_fee
    )

    st.session_state.cash += qty * price - exit_fee
    st.session_state.realized += pnl
    st.session_state.daily_pnl += pnl

    st.session_state.trades.append({
        "Time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "Market": symbol,
        "Action": "SELL",
        "Price": round(price, 4),
        "P/L": round(pnl, 4),
        "Reason": reason
    })

    del st.session_state.positions[symbol]


def run_cycle(data):
    messages = []

    today = datetime.now(timezone.utc).date().isoformat()

    if today != st.session_state.daily_date:
        st.session_state.daily_date = today
        st.session_state.daily_pnl = 0.0
        st.session_state.halted = False

    if st.session_state.daily_pnl <= -START_BALANCE * DAILY_LOSS_LIMIT:
        st.session_state.halted = True

    if st.session_state.halted:
        return ["DAILY LOSS LIMIT — TRADING HALTED"]

    for symbol, item in data.items():
        candle_time = item["time"]

        if st.session_state.last_processed.get(symbol) == candle_time:
            messages.append(f"{symbol}: Already processed")
            continue

        st.session_state.last_processed[symbol] = candle_time

        price = item["price"]
        position = st.session_state.positions.get(symbol)

        # Exit management: only candles after entry
        if position:
            if candle_time <= position["entry_candle"]:
                messages.append(f"{symbol}: Position protected")
                continue

            if item["low"] <= position["stop"]:
                close_position(symbol, position["stop"], "STOP LOSS")
                messages.append(f"{symbol}: STOP LOSS")

            elif item["high"] >= position["target"]:
                close_position(symbol, position["target"], "TAKE PROFIT")
                messages.append(f"{symbol}: TAKE PROFIT")

            elif item["signal"] == "SELL":
                close_position(symbol, price, "SELL SIGNAL")
                messages.append(f"{symbol}: SELL SIGNAL")

            continue

        if item["signal"] != "BUY":
            messages.append(f"{symbol}: HOLD")
            continue

        if item["atr"] <= 0:
            messages.append(f"{symbol}: Invalid ATR")
            continue

        distance = max(item["atr"] * 1.5, price * 0.005)

        risk_money = st.session_state.cash * RISK_PER_TRADE
        qty_risk = risk_money / distance
        qty_limit = st.session_state.cash * MAX_POSITION / price

        qty = min(qty_risk, qty_limit)
        cost = qty * price
        fee = cost * FEE_RATE

        if qty <= 0 or cost + fee > st.session_state.cash:
            messages.append(f"{symbol}: Insufficient balance")
            continue

        st.session_state.cash -= cost + fee

        st.session_state.positions[symbol] = {
            "qty": qty,
            "entry": price,
            "entry_candle": candle_time,
            "entry_fee": fee,
            "stop": price - distance,
            "target": price + 2 * distance
        }

        st.session_state.trades.append({
            "Time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "Market": symbol,
            "Action": "BUY",
            "Price": round(price, 4),
            "P/L": 0.0,
            "Reason": "EMA CROSS"
        })

        messages.append(f"{symbol}: VIRTUAL BUY")

    return messages


# ---------------- PORTFOLIO ----------------

def get_equity(data):
    value = st.session_state.cash

    for symbol, position in st.session_state.positions.items():
        if symbol in data:
            value += position["qty"] * data[symbol]["price"]

    return value


# ---------------- HEADER ----------------

st.markdown("""
<div class="terminal-header">
    <div class="terminal-title">📈 ATB 99</div>
    <div class="terminal-sub">
        PROFESSIONAL CRYPTO TRADING TERMINAL
        &nbsp; | &nbsp; VERSION 1.2
    </div>
    <br>
    <span class="status">● DEMO / PAPER TRADING</span>
</div>
""", unsafe_allow_html=True)

# ---------------- SIDEBAR ----------------

with st.sidebar:
    st.title("ATB 99 CONTROL")
    st.caption("SYSTEM SETTINGS")

    st.write("Mode: PAPER TRADING")
    st.write("Leverage: DISABLED")
    st.write("Risk per trade: 0.5%")
    st.write("Max position: 25%")

    if st.button("RESET DEMO ACCOUNT"):
        for key, value in defaults.items():
            st.session_state[key] = value
        st.rerun()

# ---------------- DATA REFRESH ----------------

if st.button("↻ REFRESH MARKET DATA"):
    st.rerun()

data = {}

with st.spinner("Connecting to Kraken..."):
    for symbol in MARKETS:
        try:
            data[symbol] = analyze(symbol)
        except Exception as error:
            st.error(f"{symbol}: {error}")

# ---------------- DASHBOARD ----------------

if data:

    equity = get_equity(data)
    pnl = equity - START_BALANCE

    st.markdown('<div class="section-title">PORTFOLIO OVERVIEW</div>',
                unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("TOTAL EQUITY", f"{equity:,.2f} USDT")
    c2.metric("AVAILABLE CASH", f"{st.session_state.cash:,.2f} USDT")
    c3.metric("TOTAL P/L", f"{pnl:+.2f} USDT")
    c4.metric("OPEN POSITIONS", str(len(st.session_state.positions)))

    st.caption(
        f"Realized P/L: {st.session_state.realized:+.2f} USDT"
    )

    st.divider()

    # MARKET CARDS

    st.markdown('<div class="section-title">MARKET INTELLIGENCE</div>',
                unsafe_allow_html=True)

    tabs = st.tabs(list(data.keys()))

    for tab, (symbol, item) in zip(tabs, data.items()):

        with tab:
            a, b, c, d = st.columns(4)

            a.metric("LAST PRICE", f"{item['price']:,.2f}")
            b.metric("RSI 14", f"{item['rsi']:.2f}")
            c.metric("EMA 20", f"{item['ema20']:,.2f}")
            d.metric("EMA 50", f"{item['ema50']:,.2f}")

            if item["signal"] == "BUY":
                st.success("BUY SIGNAL")

            elif item["signal"] == "SELL":
                st.error("SELL SIGNAL")

            else:
                st.warning("HOLD — NO ENTRY")

            st.line_chart(
                item["chart"].set_index("Time"),
                height=320
            )

    st.divider()

    # TRADING ENGINE

    st.markdown('<div class="section-title">AUTOMATED TRADING ENGINE</div>',
                unsafe_allow_html=True)

    st.write(
        "Симулацията използва затворени едночасови свещи. "
        "Изпълнението е ръчно задействано."
    )

    if st.button("▶ EXECUTE PAPER TRADING CYCLE"):
        results = run_cycle(data)

        for result in results:
            st.write("•", result)

        new_equity = get_equity(data)

        st.session_state.equity_history.append({
            "Time": datetime.now(timezone.utc),
            "Equity": new_equity
        })

        st.rerun()

    st.divider()

    # POSITIONS

    st.markdown('<div class="section-title">OPEN POSITIONS</div>',
                unsafe_allow_html=True)

    if st.session_state.positions:

        rows = []

        for symbol, pos in st.session_state.positions.items():
            current = data.get(symbol, {}).get("price", pos["entry"])

            rows.append({
                "Market": symbol,
                "Entry": round(pos["entry"], 4),
                "Current": round(current, 4),
                "Quantity": round(pos["qty"], 8),
                "Stop Loss": round(pos["stop"], 4),
                "Take Profit": round(pos["target"], 4)
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    else:
        st.info("No open positions.")

    st.divider()

    # HISTORY

    st.markdown('<div class="section-title">TRADE HISTORY</div>',
                unsafe_allow_html=True)

    if st.session_state.trades:
        st.dataframe(
            pd.DataFrame(list(reversed(st.session_state.trades))),
            use_container_width=True
        )
    else:
        st.info("No trades executed yet.")

    st.divider()

    # EQUITY CURVE

    st.markdown('<div class="section-title">EQUITY PERFORMANCE</div>',
                unsafe_allow_html=True)

    if st.session_state.equity_history:
        history = pd.DataFrame(st.session_state.equity_history)
        st.line_chart(history.set_index("Time"))
    else:
        st.info("Performance history will appear after a trading cycle.")

else:
    st.error("Market data unavailable. Check Kraken connection.")

# ---------------- FOOTER ----------------

st.divider()

st.caption(
    "ATB 99 | Professional Trading Terminal | "
    "Kraken Public API | PAPER TRADING ONLY"
)

st.caption(
    "No real orders. No guaranteed profit. "
    "Experimental algorithmic trading software."
)

st.caption(
    "UTC: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
)
