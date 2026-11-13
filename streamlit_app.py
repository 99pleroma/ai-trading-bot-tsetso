
import streamlit as st
import pandas as pd
import urllib.request
import json
from datetime import datetime, timezone

# ==================================================
# ATB 99 - VERSION 1.1
# AUTOMATED CRYPTO PAPER TRADING
# ==================================================

st.set_page_config(
    page_title="ATB 99 | AI Trading System",
    page_icon="📈",
    layout="wide"
)

# ---------------- CONFIGURATION ----------------

START_BALANCE = 1000.0
FEE_RATE = 0.001
RISK_PER_TRADE = 0.005
MAX_POSITION = 0.25
DAILY_LOSS_LIMIT = 0.02

MARKETS = {
    "BTC/USDT": "XBTUSDT",
    "ETH/USDT": "ETHUSDT"
}

# ---------------- SESSION STATE ----------------

defaults = {
    "cash": START_BALANCE,
    "positions": {},
    "trades": [],
    "realized_pnl": 0.0,
    "daily_pnl": 0.0,
    "daily_date": datetime.now(timezone.utc).date().isoformat(),
    "last_processed": {},
    "equity_history": [],
    "halted": False
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


def reset_account():
    for key, value in defaults.items():
        st.session_state[key] = value


# ---------------- MARKET DATA ----------------

def get_market(symbol):

    pair = MARKETS[symbol]

    url = (
        "https://api.kraken.com/0/public/OHLC"
        f"?pair={pair}&interval=60"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATB99-PaperTrading/1.1"}
    )

    with urllib.request.urlopen(
        request, timeout=20
    ) as response:

        payload = json.loads(
            response.read().decode("utf-8")
        )

    if payload.get("error"):
        raise Exception(str(payload["error"]))

    result = payload["result"]

    rows = next(
        value for key, value in result.items()
        if key != "last" and isinstance(value, list)
    )

    # Последната свещ е незавършена.
    rows = rows[:-1]

    if len(rows) < 55:
        raise Exception("Недостатъчно исторически данни")

    candles = []

    for row in rows:
        candles.append({
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[6])
        })

    return candles


# ---------------- TECHNICAL INDICATORS ----------------

def calculate_ema(values, period):

    alpha = 2 / (period + 1)

    result = [values[0]]

    for value in values[1:]:
        result.append(
            alpha * value +
            (1 - alpha) * result[-1]
        )

    return result


def calculate_rsi(values, period=14):

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def calculate_atr(candles, period=14):

    true_ranges = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )

        true_ranges.append(tr)

    atr = sum(true_ranges[:period]) / period

    for value in true_ranges[period:]:
        atr = (
            atr * (period - 1) + value
        ) / period

    return atr


# ---------------- MARKET ANALYSIS ----------------

def analyze_market(symbol):

    candles = get_market(symbol)

    close = [x["close"] for x in candles]

    ema20 = calculate_ema(close, 20)
    ema50 = calculate_ema(close, 50)

    rsi = calculate_rsi(close)
    atr = calculate_atr(candles)

    signal = "HOLD"

    crossed_up = (
        ema20[-2] <= ema50[-2]
        and ema20[-1] > ema50[-1]
    )

    crossed_down = (
        ema20[-2] >= ema50[-2]
        and ema20[-1] < ema50[-1]
    )

    if crossed_up and 45 <= rsi <= 68:
        signal = "BUY"

    elif crossed_down:
        signal = "SELL"

    return {
        "price": close[-1],
        "ema20": ema20[-1],
        "ema50": ema50[-1],
        "rsi": rsi,
        "atr": atr,
        "signal": signal,
        "candle_time": candles[-1]["time"],
        "high": candles[-1]["high"],
        "low": candles[-1]["low"],
        "chart": [
            {
                "Time": datetime.fromtimestamp(
                    candles[i]["time"],
                    timezone.utc
                ),
                "Price": close[i],
                "EMA 20": ema20[i],
                "EMA 50": ema50[i]
            }
            for i in range(max(0, len(candles) - 100), len(candles))
        ]
    }


# ---------------- PAPER TRADING ----------------

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

    st.session_state.realized_pnl += pnl
    st.session_state.daily_pnl += pnl

    st.session_state.trades.append({
        "Time": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "Market": symbol,
        "Action": "SELL",
        "Price": round(price, 4),
        "Quantity": round(qty, 8),
        "Fee": round(exit_fee, 4),
        "P/L": round(pnl, 4),
        "Reason": reason
    })

    del st.session_state.positions[symbol]

    return pnl


def execute_paper_cycle(market_data):

    messages = []

    today = datetime.now(timezone.utc).date().isoformat()

    if today != st.session_state.daily_date:

        st.session_state.daily_date = today
        st.session_state.daily_pnl = 0.0
        st.session_state.halted = False

    if st.session_state.daily_pnl <= (
        -START_BALANCE * DAILY_LOSS_LIMIT
    ):
        st.session_state.halted = True

    if st.session_state.halted:
        return ["ТЪРГОВИЯТА Е СПРЯНА: достигнат е дневният лимит."]

    for symbol, data in market_data.items():

        candle_time = data["candle_time"]

        if st.session_state.last_processed.get(symbol) == candle_time:
            messages.append(
                f"{symbol}: тази свещ вече е обработена."
            )
            continue

        st.session_state.last_processed[symbol] = candle_time

        price = data["price"]

        position = st.session_state.positions.get(symbol)

        # -------- EXIT MANAGEMENT --------

        if position:

            stop_hit = data["low"] <= position["stop"]
            target_hit = data["high"] >= position["target"]

            # Ако и двете са достигнати в една свещ,
            # приемаме по-консервативно, че Stop Loss е първи.

            if stop_hit:

                pnl = close_position(
                    symbol,
                    position["stop"],
                    "STOP LOSS"
                )

                messages.append(
                    f"{symbol}: STOP LOSS | P/L {pnl:.2f} USDT"
                )

            elif target_hit:

                pnl = close_position(
                    symbol,
                    position["target"],
                    "TAKE PROFIT"
                )

                messages.append(
                    f"{symbol}: TAKE PROFIT | P/L {pnl:.2f} USDT"
                )

            elif data["signal"] == "SELL":

                pnl = close_position(
                    symbol,
                    price,
                    "SELL SIGNAL"
                )

                messages.append(
                    f"{symbol}: SELL SIGNAL | P/L {pnl:.2f} USDT"
                )

            continue

        # -------- ENTRY MANAGEMENT --------

        if data["signal"] != "BUY":

            messages.append(f"{symbol}: HOLD")
            continue

        if data["atr"] <= 0:
            messages.append(f"{symbol}: невалиден ATR")
            continue

        stop_distance = max(
            data["atr"] * 1.5,
            price * 0.005
        )

        risk_money = (
            st.session_state.cash * RISK_PER_TRADE
        )

        qty_by_risk = risk_money / stop_distance

        qty_by_allocation = (
            st.session_state.cash * MAX_POSITION / price
        )

        qty = min(qty_by_risk, qty_by_allocation)

        cost = qty * price
        entry_fee = cost * FEE_RATE

        if qty <= 0 or cost + entry_fee > st.session_state.cash:
            messages.append(
                f"{symbol}: недостатъчен виртуален баланс"
            )
            continue

        stop = price - stop_distance
        target = price + 2 * stop_distance

        st.session_state.cash -= cost + entry_fee

        st.session_state.positions[symbol] = {
            "qty": qty,
            "entry": price,
            "stop": stop,
            "target": target,
            "entry_fee": entry_fee
        }

        st.session_state.trades.append({
            "Time": datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "Market": symbol,
            "Action": "BUY",
            "Price": round(price, 4),
            "Quantity": round(qty, 8),
            "Fee": round(entry_fee, 4),
            "P/L": 0.0,
            "Reason": "EMA CROSS"
        })

        messages.append(
            f"{symbol}: BUY @ {price:.4f} | "
            f"SL {stop:.4f} | TP {target:.4f}"
        )

    return messages


# ---------------- PORTFOLIO ----------------

def calculate_equity(market_data):

    position_value = 0.0

    for symbol, position in st.session_state.positions.items():

        if symbol in market_data:

            position_value += (
                position["qty"] *
                market_data[symbol]["price"]
            )

    return st.session_state.cash + position_value


# ---------------- DASHBOARD ----------------

st.title("📈 ATB 99")
st.subheader("AI Trading Bot | Cryptocurrency")

st.caption(
    "VERSION 1.1 | PAPER TRADING | KRAKEN PUBLIC DATA"
)

st.success(
    "DEMO MODE — Системата използва само виртуални средства."
)

st.divider()

st.sidebar.title("ATB 99 CONTROL")

st.sidebar.write("Режим: PAPER TRADING")
st.sidebar.write("Начален капитал: 1 000 USDT")
st.sidebar.write("Риск на сделка: 0.5%")
st.sidebar.write("Ливъридж: ИЗКЛЮЧЕН")

if st.sidebar.button("НУЛИРАЙ СИМУЛАЦИЯТА"):

    reset_account()
    st.rerun()

st.sidebar.caption(
    "Нулирането изтрива историята на текущата сесия."
)

# ---------------- FETCH DATA ----------------

market_data = {}

st.subheader("🌐 Пазарен монитор")

with st.spinner("Свързване с Kraken..."):

    for symbol in MARKETS:

        try:

            market_data[symbol] = analyze_market(symbol)

        except Exception as error:

            st.error(
                f"{symbol}: Грешка при данните: {error}"
            )

# ---------------- DISPLAY MARKETS ----------------

if market_data:

    columns = st.columns(len(market_data))

    for column, (symbol, data) in zip(
        columns, market_data.items()
    ):

        with column:

            st.markdown(f"### {symbol}")

            st.metric(
                "Последна затворена цена",
                f"{data['price']:,.2f} USDT"
            )

            st.metric(
                "RSI 14",
                f"{data['rsi']:.2f}"
            )

            st.metric(
                "EMA 20",
                f"{data['ema20']:.2f}"
            )

            st.metric(
                "EMA 50",
                f"{data['ema50']:.2f}"
            )

            signal = data["signal"]

            if signal == "BUY":
                st.success("BUY")

            elif signal == "SELL":
                st.error("SELL")

            else:
                st.warning("HOLD")

            chart = pd.DataFrame(data["chart"])

            st.line_chart(
                chart.set_index("Time")
            )

    st.divider()

    # ---------------- PORTFOLIO ----------------

    st.subheader("💰 Виртуален портфейл")

    equity = calculate_equity(market_data)

    position_value = equity - st.session_state.cash

    total_pnl = equity - START_BALANCE

    a, b, c, d = st.columns(4)

    a.metric(
        "Свободен баланс",
        f"{st.session_state.cash:.2f} USDT"
    )

    b.metric(
        "Отворени позиции",
        str(len(st.session_state.positions))
    )

    c.metric(
        "Обща стойност",
        f"{equity:.2f} USDT"
    )

    d.metric(
        "Общ резултат",
        f"{total_pnl:+.2f} USDT"
    )

    st.caption(
        f"Реализиран резултат: "
        f"{st.session_state.realized_pnl:+.2f} USDT"
    )

    st.divider()

    # ---------------- AUTOMATION ----------------

    st.subheader("🤖 Автоматично изпълнение")

    st.write(
        "Ботът анализира новите затворени свещи "
        "и изпълнява симулирани сделки."
    )

    if st.button(
        "▶ ИЗПЪЛНИ АВТОМАТИЧЕН PAPER CYCLE",
        type="primary"
    ):

        messages = execute_paper_cycle(market_data)

        for message in messages:
            st.write("•", message)

        equity = calculate_equity(market_data)

        st.session_state.equity_history.append({
            "Time": datetime.now(timezone.utc),
            "Equity": equity
        })

        st.rerun()

    st.divider()

    # ---------------- OPEN POSITIONS ----------------

    st.subheader("📊 Отворени позиции")

    if st.session_state.positions:

        position_rows = []

        for symbol, position in st.session_state.positions.items():

            current = market_data.get(symbol, {}).get(
                "price", position["entry"]
            )

            position_rows.append({
                "Market": symbol,
                "Entry": round(position["entry"], 4),
                "Current": round(current, 4),
                "Quantity": round(position["qty"], 8),
                "Stop Loss": round(position["stop"], 4),
                "Take Profit": round(position["target"], 4)
            })

        st.dataframe(
            pd.DataFrame(position_rows),
            use_container_width=True
        )

    else:

        st.info("Няма отворени позиции.")

    st.divider()

    # ---------------- TRADE HISTORY ----------------

    st.subheader("📜 История на сделките")

    if st.session_state.trades:

        st.dataframe(
            pd.DataFrame(
                list(reversed(st.session_state.trades))
            ),
            use_container_width=True
        )

    else:

        st.info("Все още няма изпълнени сделки.")

    st.divider()

    # ---------------- EQUITY HISTORY ----------------

    st.subheader("📈 История на капитала")

    if st.session_state.equity_history:

        history = pd.DataFrame(
            st.session_state.equity_history
        )

        st.line_chart(
            history.set_index("Time")
        )

    else:

        st.info(
            "Графиката ще се появи след първия PAPER cycle."
        )

else:

    st.error(
        "Няма получени пазарни данни. "
        "Провери връзката с Kraken."
    )

# ---------------- FOOTER ----------------

st.divider()

st.caption(
    "ATB 99 | Experimental Paper Trading System"
)

st.caption(
    "Kraken Public API | No real orders | "
    "No guaranteed profit"
)

st.caption(
    "Време UTC: "
    + datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
)
