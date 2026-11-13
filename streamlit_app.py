
import streamlit as st
import pandas as pd
import altair as alt
import urllib.request
import json
import sqlite3
from datetime import datetime, timezone

# =====================================================
# ATB 99 | ADVANCED TRADING TERMINAL | VERSION 1.3
# PAPER TRADING ONLY
# =====================================================

st.set_page_config(
    page_title="ATB 99 | Advanced Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------------- CONFIGURATION ----------------

START_BALANCE = 1000.0
FEE_RATE = 0.001
RISK_PER_TRADE = 0.005
MAX_ALLOCATION = 0.25
DAILY_LOSS_LIMIT = 0.02

MARKETS = {
    "BTC/USDT": "XBTUSDT",
    "ETH/USDT": "ETHUSDT"
}

DB_FILE = "atb99_history.db"

# ---------------- DESIGN ----------------

st.markdown("""
<style>
.stApp {
    background: #090e14;
    color: #e7edf5;
}
header[data-testid="stHeader"] {
    background: #090e14;
}
.block-container {
    max-width: 1500px;
    padding-top: 1.2rem;
    padding-bottom: 3rem;
}
[data-testid="stMetric"] {
    background: #141d28;
    border: 1px solid #293747;
    border-radius: 12px;
    padding: 15px;
    min-width: 0;
}
[data-testid="stMetricValue"] {
    color: #f1f5f9;
    font-size: clamp(17px, 2.2vw, 27px);
}
[data-testid="stMetricLabel"] {
    color: #93a4b8;
}
div.stButton > button {
    background: #00c78a;
    color: #06130e;
    border: 0;
    border-radius: 9px;
    font-weight: 700;
    min-height: 44px;
    width: 100%;
}
div.stButton > button:hover {
    background: #00e5a0;
    color: #06130e;
}
.terminal {
    background: linear-gradient(120deg,#14232e,#101720);
    border: 1px solid #2a4050;
    border-radius: 15px;
    padding: 22px;
    margin-bottom: 20px;
}
.brand {
    font-size: 30px;
    font-weight: 800;
    color: #f4f8fc;
}
.subtitle {
    font-size: 12px;
    color: #8fa5b8;
    letter-spacing: 1px;
}
.pill {
    display: inline-block;
    background: #123d31;
    color: #00e5a0;
    padding: 7px 12px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 700;
    margin-top: 15px;
}
.section {
    color: #e6edf5;
    font-size: 19px;
    font-weight: 750;
    margin-top: 12px;
    margin-bottom: 10px;
}
div[data-testid="stDataFrame"] {
    border: 1px solid #293747;
    border-radius: 10px;
}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ---------------- SESSION STATE ----------------

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

# ---------------- DATABASE ----------------

def init_database():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                market TEXT,
                action TEXT,
                price REAL,
                quantity REAL,
                fee REAL,
                pnl REAL,
                reason TEXT
            )
        """)

def save_trade(trade):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT INTO trades
            (timestamp, market, action, price,
             quantity, fee, pnl, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade["Time"],
            trade["Market"],
            trade["Action"],
            trade["Price"],
            trade["Quantity"],
            trade["Fee"],
            trade["P/L"],
            trade["Reason"]
        ))

def load_database_history():
    with sqlite3.connect(DB_FILE) as conn:
        return pd.read_sql_query(
            "SELECT * FROM trades ORDER BY id DESC LIMIT 200",
            conn
        )

init_database()

# ---------------- MARKET DATA ----------------

@st.cache_data(ttl=60)
def get_market(symbol):

    pair = MARKETS[symbol]

    url = (
        "https://api.kraken.com/0/public/OHLC"
        f"?pair={pair}&interval=60"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ATB99/1.3"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if payload.get("error"):
        raise Exception(str(payload["error"]))

    rows = next(
        value for key, value in payload["result"].items()
        if key != "last" and isinstance(value, list)
    )

    # Ignore the unfinished candle.
    rows = rows[:-1]

    if len(rows) < 60:
        raise Exception("Insufficient candle history")

    return pd.DataFrame([{
        "time": int(x[0]),
        "open": float(x[1]),
        "high": float(x[2]),
        "low": float(x[3]),
        "close": float(x[4]),
        "volume": float(x[6])
    } for x in rows])

# ---------------- INDICATORS ----------------

def calculate_indicators(df):

    df = df.copy()

    df["ema20"] = df["close"].ewm(
        span=20, adjust=False
    ).mean()

    df["ema50"] = df["close"].ewm(
        span=50, adjust=False
    ).mean()

    delta = df["close"].diff()

    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.ewm(
        alpha=1/14, adjust=False, min_periods=14
    ).mean()

    avg_loss = losses.ewm(
        alpha=1/14, adjust=False, min_periods=14
    ).mean()

    rs = avg_gain / avg_loss.where(avg_loss != 0)

    df["rsi"] = 100 - (100 / (1 + rs))
    df.loc[avg_loss == 0, "rsi"] = 100

    previous_close = df["close"].shift(1)

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs()
    ], axis=1).max(axis=1)

    df["atr"] = tr.ewm(
        alpha=1/14, adjust=False, min_periods=14
    ).mean()

    cross_up = (
        (df["ema20"].shift(1) <= df["ema50"].shift(1))
        & (df["ema20"] > df["ema50"])
    )

    cross_down = (
        (df["ema20"].shift(1) >= df["ema50"].shift(1))
        & (df["ema20"] < df["ema50"])
    )

    df["signal"] = "HOLD"

    df.loc[
        cross_up & df["rsi"].between(45, 68),
        "signal"
    ] = "BUY"

    df.loc[cross_down, "signal"] = "SELL"

    return df

# ---------------- CANDLESTICK CHART ----------------

def make_chart(df):

    chart_data = df.tail(100).copy()

    chart_data["date"] = pd.to_datetime(
        chart_data["time"], unit="s", utc=True
    )

    chart_data["color"] = chart_data.apply(
        lambda x: "UP" if x["close"] >= x["open"] else "DOWN",
        axis=1
    )

    base = alt.Chart(chart_data).encode(
        x=alt.X(
            "date:T",
            title=None,
            axis=alt.Axis(labelColor="#9aabba", grid=False)
        )
    )

    candles = base.mark_rule().encode(
        y=alt.Y(
            "low:Q",
            title="Price (USDT)",
            scale=alt.Scale(zero=False),
            axis=alt.Axis(labelColor="#9aabba", gridColor="#263342")
        ),
        y2="high:Q",
        color=alt.Color(
            "color:N",
            scale=alt.Scale(
                domain=["UP", "DOWN"],
                range=["#00d69a", "#ff647c"]
            ),
            legend=None
        ),
        tooltip=[
            alt.Tooltip("date:T", title="Time"),
            alt.Tooltip("open:Q", title="Open", format=",.2f"),
            alt.Tooltip("high:Q", title="High", format=",.2f"),
            alt.Tooltip("low:Q", title="Low", format=",.2f"),
            alt.Tooltip("close:Q", title="Close", format=",.2f")
        ]
    )

    bodies = base.mark_bar(size=7).encode(
        y=alt.Y(
            "open:Q",
            scale=alt.Scale(zero=False)
        ),
        y2="close:Q",
        color=alt.Color(
            "color:N",
            scale=alt.Scale(
                domain=["UP", "DOWN"],
                range=["#00d69a", "#ff647c"]
            ),
            legend=None
        )
    )

    ema20 = base.mark_line(
        color="#f5bd4f", strokeWidth=1.5
    ).encode(
        y=alt.Y("ema20:Q", scale=alt.Scale(zero=False))
    )

    ema50 = base.mark_line(
        color="#55aaff", strokeWidth=1.5
    ).encode(
        y=alt.Y("ema50:Q", scale=alt.Scale(zero=False))
    )

    return (
        alt.layer(candles, bodies, ema20, ema50)
        .properties(
            height=330,
            background="#111923",
            padding=10
        )
        .configure_view(stroke="#263342")
        .configure_axis(
            labelColor="#9aabba",
            titleColor="#9aabba",
            gridColor="#263342"
        )
        .interactive()
    )

# ---------------- BACKTEST ENGINE ----------------

def run_backtest(df, starting_cash=500.0):

    cash = starting_cash
    position = None
    trades = []
    equity_curve = []

    for i in range(55, len(df) - 1):

        candle = df.iloc[i]
        next_candle = df.iloc[i + 1]

        if pd.isna(candle["atr"]) or candle["atr"] <= 0:
            continue

        # Manage existing position using only
        # candles that occurred after its entry.

        if position is not None:

            stop_hit = candle["low"] <= position["stop"]
            target_hit = candle["high"] >= position["target"]

            exit_price = None
            reason = None

            # Conservative rule if both levels are hit.
            if stop_hit:
                exit_price = position["stop"]
                reason = "STOP LOSS"

            elif target_hit:
                exit_price = position["target"]
                reason = "TAKE PROFIT"

            elif candle["signal"] == "SELL":
                exit_price = next_candle["open"]
                reason = "SELL SIGNAL"

            if exit_price is not None:

                exit_fee = position["qty"] * exit_price * FEE_RATE

                pnl = (
                    position["qty"] *
                    (exit_price - position["entry"])
                    - position["entry_fee"]
                    - exit_fee
                )

                cash += position["qty"] * exit_price - exit_fee

                trades.append({
                    "Market": "BACKTEST",
                    "Entry": round(position["entry"], 4),
                    "Exit": round(exit_price, 4),
                    "P/L": round(pnl, 4),
                    "Reason": reason
                })

                position = None

                # Avoid re-entry on the same candle.
                equity_curve.append(cash)
                continue

        # New entry at NEXT candle open,
        # after the signal candle has closed.

        if position is None and candle["signal"] == "BUY":

            entry = float(next_candle["open"])

            distance = max(
                float(candle["atr"]) * 1.5,
                entry * 0.005
            )

            risk_money = cash * RISK_PER_TRADE

            qty_by_risk = risk_money / distance
            qty_by_allocation = cash * MAX_ALLOCATION / entry

            qty = min(qty_by_risk, qty_by_allocation)

            cost = qty * entry
            entry_fee = cost * FEE_RATE

            if qty > 0 and cost + entry_fee <= cash:

                cash -= cost + entry_fee

                position = {
                    "entry": entry,
                    "qty": qty,
                    "entry_fee": entry_fee,
                    "stop": entry - distance,
                    "target": entry + 2 * distance
                }

        if position:
            current_equity = cash + position["qty"] * candle["close"]
        else:
            current_equity = cash

        equity_curve.append(current_equity)

    # Close any remaining position at final available close.

    if position is not None:

        final_price = float(df.iloc[-1]["close"])

        exit_fee = position["qty"] * final_price * FEE_RATE

        pnl = (
            position["qty"] *
            (final_price - position["entry"])
            - position["entry_fee"]
            - exit_fee
        )

        cash += position["qty"] * final_price - exit_fee

        trades.append({
            "Market": "BACKTEST",
            "Entry": round(position["entry"], 4),
            "Exit": round(final_price, 4),
            "P/L": round(pnl, 4),
            "Reason": "END OF TEST"
        })

    equity_curve.append(cash)

    # Statistics

    total_return = cash - starting_cash
    return_pct = total_return / starting_cash * 100

    winners = [x for x in trades if x["P/L"] > 0]
    losers = [x for x in trades if x["P/L"] < 0]

    win_rate = (
        len(winners) / len(trades) * 100
        if trades else 0
    )

    gross_profit = sum(x["P/L"] for x in winners)
    gross_loss = abs(sum(x["P/L"] for x in losers))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (float("inf") if gross_profit > 0 else 0)
    )

    peak = starting_cash
    max_drawdown = 0.0

    for value in equity_curve:
        peak = max(peak, value)

        if peak > 0:
            drawdown = (peak - value) / peak * 100
            max_drawdown = max(max_drawdown, drawdown)

    return {
        "final": cash,
        "return": return_pct,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "trades": trades,
        "equity_curve": equity_curve
    }

# ---------------- PAPER TRADING ----------------

def save_paper_trade(
    symbol, action, price, qty, fee, pnl, reason
):

    trade = {
        "Time": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "Market": symbol,
        "Action": action,
        "Price": round(price, 4),
        "Quantity": round(qty, 8),
        "Fee": round(fee, 4),
        "P/L": round(pnl, 4),
        "Reason": reason
    }

    st.session_state.trades.append(trade)
    save_trade(trade)


def close_paper_position(symbol, price, reason):

    position = st.session_state.positions[symbol]

    qty = position["qty"]
    fee = qty * price * FEE_RATE

    pnl = (
        qty * (price - position["entry"])
        - position["entry_fee"]
        - fee
    )

    st.session_state.cash += qty * price - fee
    st.session_state.realized += pnl
    st.session_state.daily_pnl += pnl

    save_paper_trade(
        symbol, "SELL", price, qty,
        fee, pnl, reason
    )

    del st.session_state.positions[symbol]

    return pnl


def execute_paper_cycle(data):

    messages = []

    today = datetime.now(timezone.utc).date().isoformat()

    if today != st.session_state.daily_date:
        st.session_state.daily_date = today
        st.session_state.daily_pnl = 0.0
        st.session_state.halted = False

    if st.session_state.daily_pnl <= -START_BALANCE * DAILY_LOSS_LIMIT:
        st.session_state.halted = True

    if st.session_state.halted:
        return ["DAILY LOSS LIMIT: trading halted"]

    for symbol, item in data.items():

        candle_time = int(item["time"])

        if st.session_state.last_processed.get(symbol) == candle_time:
            messages.append(f"{symbol}: candle already processed")
            continue

        st.session_state.last_processed[symbol] = candle_time

        price = float(item["close"])

        position = st.session_state.positions.get(symbol)

        if position:

            if candle_time <= position["entry_candle"]:
                messages.append(f"{symbol}: waiting for next candle")
                continue

            stop_hit = item["low"] <= position["stop"]
            target_hit = item["high"] >= position["target"]

            if stop_hit:
                pnl = close_paper_position(
                    symbol, position["stop"], "STOP LOSS"
                )
                messages.append(
                    f"{symbol}: STOP LOSS | {pnl:+.2f} USDT"
                )

            elif target_hit:
                pnl = close_paper_position(
                    symbol, position["target"], "TAKE PROFIT"
                )
                messages.append(
                    f"{symbol}: TAKE PROFIT | {pnl:+.2f} USDT"
                )

            elif item["signal"] == "SELL":
                pnl = close_paper_position(
                    symbol, price, "SELL SIGNAL"
                )
                messages.append(
                    f"{symbol}: SELL | {pnl:+.2f} USDT"
                )

            continue

        if item["signal"] != "BUY":
            messages.append(f"{symbol}: HOLD")
            continue

        distance = max(
            float(item["atr"]) * 1.5,
            price * 0.005
        )

        risk_money = st.session_state.cash * RISK_PER_TRADE

        qty = min(
            risk_money / distance,
            st.session_state.cash * MAX_ALLOCATION / price
        )

        cost = qty * price
        fee = cost * FEE_RATE

        if qty <= 0 or cost + fee > st.session_state.cash:
            messages.append(f"{symbol}: insufficient balance")
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

        save_paper_trade(
            symbol, "BUY", price, qty,
            fee, 0.0, "EMA CROSS"
        )

        messages.append(f"{symbol}: VIRTUAL BUY")

    return messages

# ---------------- PORTFOLIO ----------------

def calculate_equity(data):

    value = st.session_state.cash

    for symbol, position in st.session_state.positions.items():
        if symbol in data:
            value += (
                position["qty"] * data[symbol]["close"]
            )

    return value

# ---------------- HEADER ----------------

st.markdown("""
<div class="terminal">
    <div class="brand">📈 ATB 99</div>
    <div class="subtitle">
        ADVANCED ALGORITHMIC TRADING TERMINAL | VERSION 1.3
    </div>
    <span class="pill">● DEMO / PAPER TRADING</span>
</div>
""", unsafe_allow_html=True)

# ---------------- SIDEBAR ----------------

with st.sidebar:

    st.title("ATB 99 CONTROL")

    st.write("Mode: PAPER TRADING")
    st.write("Leverage: DISABLED")
    st.write("Risk per trade: 0.5%")
    st.write("Max allocation: 25%")

    if st.button("RESET DEMO ACCOUNT"):

        for key, value in defaults.items():
            st.session_state[key] = value

        st.rerun()

    st.caption(
        "Resetting the account clears session data."
    )

# ---------------- REFRESH ----------------

if st.button("↻ REFRESH MARKET DATA"):

    get_market.clear()
    st.rerun()

# ---------------- FETCH MARKETS ----------------

market_data = {}
errors = {}

with st.spinner("Loading Kraken market data..."):

    for symbol in MARKETS:

        try:
            raw = get_market(symbol)
            market_data[symbol] = calculate_indicators(raw)

        except Exception as error:
            errors[symbol] = str(error)

for symbol, error in errors.items():
    st.error(f"{symbol}: {error}")

# ---------------- DASHBOARD ----------------

if market_data:

    equity = calculate_equity(market_data)
    pnl = equity - START_BALANCE
    return_pct = pnl / START_BALANCE * 100

    st.markdown(
        '<div class="section">PORTFOLIO OVERVIEW</div>',
        unsafe_allow_html=True
    )

    a, b, c, d = st.columns(4)

    a.metric("TOTAL EQUITY", f"{equity:,.2f} USDT")
    b.metric("AVAILABLE CASH", f"{st.session_state.cash:,.2f} USDT")
    c.metric("TOTAL P/L", f"{pnl:+,.2f} USDT")
    d.metric("RETURN", f"{return_pct:+.2f}%")

    st.caption(
        f"Realized P/L: {st.session_state.realized:+.2f} USDT"
    )

    st.divider()

    # MARKET INTELLIGENCE

    st.markdown(
        '<div class="section">
