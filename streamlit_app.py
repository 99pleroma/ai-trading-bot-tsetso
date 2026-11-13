
import streamlit as st
import urllib.request
import json
import math
from datetime import datetime, timezone

st.set_page_config(
    page_title="ATB 99 | AI Trading",
    page_icon="📈",
    layout="wide"
)

# -----------------------------
# CONFIGURATION
# -----------------------------
START_BALANCE = 1000.0
FEE = 0.001
RISK = 0.005

if "cash" not in st.session_state:
    st.session_state.cash = START_BALANCE
if "positions" not in st.session_state:
    st.session_state.positions = {}
if "trades" not in st.session_state:
    st.session_state.trades = []
if "realized" not in st.session_state:
    st.session_state.realized = 0.0

def get_market(symbol):
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval=1h&limit=100"
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "ATB99-Demo"}
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        rows = json.loads(response.read().decode())

    # Ignore the currently open candle
    rows = rows[:-1]

    close = [float(x[4]) for x in rows]
    high = [float(x[2]) for x in rows]
    low = [float(x[3]) for x in rows]
    volume = [float(x[5]) for x in rows]

    return close, high, low, volume

def ema(values, period):
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1-alpha) * result[-1])
    return result

def calculate_rsi(values, period=14):
    gains = []
    losses = []
    for i in range(1, len(values)):
        change = values[i] - values[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    return 100 - (100 / (1 + avg_gain / avg_loss))

def analyze(symbol):
    close, high, low, volume = get_market(symbol)
    fast = ema(close, 20)
    slow = ema(close, 50)
    rsi = calculate_rsi(close)

    signal = "HOLD"
    if fast[-2] <= slow[-2] and fast[-1] > slow[-1] and 45 <= rsi <= 68:
        signal = "BUY"
    elif fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
        signal = "SELL"

    atr_values = [
        max(high[i]-low[i],
            abs(high[i]-close[i-1]),
            abs(low[i]-close[i-1]))
        for i in range(1, len(close))
    ]
    atr = sum(atr_values[-14:]) / min(14, len(atr_values))

    return {
        "price": close[-1],
        "rsi": rsi,
        "ema20": fast[-1],
        "ema50": slow[-1],
        "signal": signal,
        "atr": atr,
        "high": high[-1],
        "low": low[-1],
        "chart": close[-50:]
    }

def paper_cycle(market):
    messages = []

    for symbol, data in market.items():
        price = data["price"]
        position = st.session_state.positions.get(symbol)

        if position:
            reason = None
            exit_price = price

            if data["low"] <= position["stop"]:
                reason = "STOP LOSS"
                exit_price = position["stop"]
            elif data["high"] >= position["target"]:
                reason = "TAKE PROFIT"
                exit_price = position["target"]
            elif data["signal"] == "SELL":
                reason = "SELL SIGNAL"

            if reason:
                qty = position["qty"]
                fee = qty * exit_price * FEE
                pnl = (
                    qty * (exit_price-position["entry"])
                    - fee - position["entry_fee"]
                )
                st.session_state.cash += qty * exit_price - fee
                st.session_state.realized += pnl
                st.session_state.trades.append({
                    "Time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "Market": symbol,
                    "Action": "SELL",
                    "Price": round(exit_price, 4),
                    "P/L USDT": round(pnl, 4),
                    "Reason": reason
                })
                del st.session_state.positions[symbol]
                messages.append(f"{symbol}: затворена позиция — {reason}")
            continue

        if data["signal"] != "BUY":
            messages.append(f"{symbol}: няма входящ сигнал")
            continue

        stop_distance = max(data["atr"] * 1.5, price * 0.005)
        risk_money = st.session_state.cash * RISK
        qty = min(
            risk_money / stop_distance,
            st.session_state.cash * 0.25 / price
        )

        cost = qty * price
        entry_fee = cost * FEE

        if cost + entry_fee > st.session_state.cash or qty <= 0:
            messages.append(f"{symbol}: недостатъчен баланс")
            continue

        st.session_state.cash -= cost + entry_fee
        st.session_state.positions[symbol] = {
            "qty": qty,
            "entry": price,
            "stop": price - stop_distance,
            "target": price + 2 * stop_distance,
            "entry_fee": entry_fee
        }

        st.session_state.trades.append({
            "Time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "Market": symbol,
            "Action": "BUY",
            "Price": round(price, 4),
            "P/L USDT": 0.0,
            "Reason": "EMA CROSS"
        })
        messages.append(f"{symbol}: виртуална покупка")

    return messages

# -----------------------------
# USER INTERFACE
# -----------------------------
st.title("📈 ATB 99")
st.subheader("AI Trading Bot | Cryptocurrency")
st.caption("Version 1.0 • PAPER TRADING • No real orders")

st.success("DEMO MODE — Работим само с виртуални средства.")

st.divider()

symbols = ["BTCUSDT", "ETHUSDT"]
market = {}

with st.spinner("Получаване на пазарни данни..."):
    for symbol in symbols:
        try:
            market[symbol] = analyze(symbol)
        except Exception as error:
            st.error(f"{symbol}: Грешка при връзката: {error}")

if market:
    st.subheader("Пазарен монитор")

    cols = st.columns(len(market))

    for col, (symbol, data) in zip(cols, market.items()):
        with col:
            st.markdown(f"### {symbol}")
            st.metric("Цена", f"{data['price']:,.2f} USDT")
            st.metric("RSI", f"{data['rsi']:.2f}")
            st.metric("EMA 20", f"{data['ema20']:.2f}")
            st.metric("EMA 50", f"{data['ema50']:.2f}")

            color = (
                "green" if data["signal"] == "BUY"
                else "red" if data["signal"] == "SELL"
                else "orange"
            )
            st.markdown(
                f"**Сигнал:** :{color}[{data['signal']}]"
            )
            st.line_chart(data["chart"])

    st.divider()
    st.subheader("Виртуален портфейл")

    position_value = sum(
        p["qty"] * market[s]["price"]
        for s, p in st.session_state.positions.items()
        if s in market
    )
    equity = st.session_state.cash + position_value
    total_pnl = equity - START_BALANCE

    a, b, c, d = st.columns(4)
    a.metric("Баланс", f"{st.session_state.cash:.2f} USDT")
    b.metric("Стойност на позициите", f"{position_value:.2f} USDT")
    c.metric("Обща стойност", f"{equity:.2f} USDT")
    d.metric("Резултат", f"{total_pnl:+.2f} USDT")

    st.divider()
    st.subheader("Автоматична симулация")

    if st.button("▶ ИЗПЪЛНИ PAPER TRADING", type="primary"):
        results = paper_cycle(market)
        for result in results:
            st.write("•", result)
        st.rerun()

    st.subheader("Отворени позиции")

    if st.session_state.positions:
        for symbol, p in st.session_state.positions.items():
            st.write(
                f"**{symbol}** | Вход: {p['entry']:.4f} | "
                f"SL: {p['stop']:.4f} | TP: {p['target']:.4f}"
            )
    else:
        st.info("Няма отворени позиции.")

    st.subheader("История на сделките")

    if st.session_state.trades:
        st.dataframe(
            list(reversed(st.session_state.trades)),
            use_container_width=True
        )
    else:
        st.info("Все още няма сделки.")

    if st.button("Нулирай виртуалния капитал"):
        st.session_state.cash = START_BALANCE
        st.session_state.positions = {}
        st.session_state.trades = []
        st.session_state.realized = 0.0
        st.rerun()

st.divider()
st.caption(
    "ATB 99 • Experimental software • Not financial advice. "
    "No profit is guaranteed."
)
st.caption(
    "Пазарни данни: Binance Public API | "
    + datetime.now(timezone.utc).strftime("UTC %Y-%m-%d %H:%M:%S")
)
