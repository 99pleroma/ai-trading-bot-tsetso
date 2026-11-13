import json
import sqlite3
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

# ============================================================
# ATB 99 | ADVANCED PAPER-TRADING TERMINAL | v1.4
# Public Kraken market data only. No exchange order endpoints.
# ============================================================

APP_NAME = "ATB 99"
APP_VERSION = "1.4"
START_BALANCE = 1000.0
FEE_RATE = 0.001          # Simulation assumption: 0.10% per side
SLIPPAGE_RATE = 0.0005    # Simulation assumption: 0.05% per side
RISK_PER_TRADE = 0.005    # 0.50% of equity
MAX_ALLOCATION = 0.25     # Maximum 25% of available cash per position
DAILY_LOSS_LIMIT = 0.02   # Halt new entries after 2% daily equity drawdown
DB_PATH = Path(__file__).with_name("atb99_demo.sqlite3")

MARKETS = {
    "BTC/USDT": "XBTUSDT",
    "ETH/USDT": "ETHUSDT",
}
TIMEFRAMES = {
    "15 минути": 15,
    "1 час": 60,
    "4 часа": 240,
}

st.set_page_config(
    page_title=f"{APP_NAME} | Trading Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Simple CSS only; no custom HTML fragments are used in the app body.
st.markdown(
    """ <style> .stApp { background: #0b1017; color: #e8eef6; } header[data-testid="stHeader"] { background: #0b1017; } .block-container { max-width: 1450px; padding-top: 1.1rem; padding-bottom: 2.5rem; } [data-testid="stMetric"] { background: #151e29; border: 1px solid #2a394a; border-radius: 12px; padding: 13px; min-width: 0; } [data-testid="stMetricLabel"] { color: #98a9bb; } [data-testid="stMetricValue"] { color: #f2f6fa; font-size: clamp(17px, 2.1vw, 27px); } div.stButton > button { border-radius: 9px; font-weight: 700; min-height: 42px; } div[data-testid="stDataFrame"] { border: 1px solid #2a394a; border-radius: 10px; } hr { border-color: #2a394a; } </style> """,
    unsafe_allow_html=True,
)


# ----------------------------- DATABASE -----------------------------

@contextmanager
def database():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    with database() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS account ( id INTEGER PRIMARY KEY CHECK (id = 1), cash REAL NOT NULL, realized_pnl REAL NOT NULL, daily_date TEXT NOT NULL, day_start_equity REAL NOT NULL, halted INTEGER NOT NULL DEFAULT 0 )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS positions ( symbol TEXT PRIMARY KEY, quantity REAL NOT NULL, entry_price REAL NOT NULL, entry_fee REAL NOT NULL, stop_price REAL NOT NULL, target_price REAL NOT NULL, entry_candle INTEGER NOT NULL )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS trades ( id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, quantity REAL NOT NULL, fee REAL NOT NULL, pnl REAL NOT NULL, reason TEXT NOT NULL )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS processed_candles ( symbol TEXT PRIMARY KEY, candle_time INTEGER NOT NULL )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS equity_history ( id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, equity REAL NOT NULL )"""
        )
        row = conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
        if row is None:
            today = datetime.now(timezone.utc).date().isoformat()
            conn.execute(
                "INSERT INTO account (id, cash, realized_pnl, daily_date, day_start_equity, halted) VALUES (1, ?, 0, ?, ?, 0)",
                (START_BALANCE, today, START_BALANCE),
            )


def reset_demo_account():
    today = datetime.now(timezone.utc).date().isoformat()
    with database() as conn:
        conn.execute("DELETE FROM positions")
        conn.execute("DELETE FROM trades")
        conn.execute("DELETE FROM processed_candles")
        conn.execute("DELETE FROM equity_history")
        conn.execute(
            "UPDATE account SET cash=?, realized_pnl=0, daily_date=?, day_start_equity=?, halted=0 WHERE id=1",
            (START_BALANCE, today, START_BALANCE),
        )


def load_account():
    with database() as conn:
        row = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
    return dict(row)


def load_positions():
    with database() as conn:
        rows = conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
    return {row["symbol"]: dict(row) for row in rows}


def load_trades(limit=200):
    with database() as conn:
        rows = conn.execute(
            "SELECT timestamp, symbol, side, price, quantity, fee, pnl, reason FROM trades ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def load_equity_history(limit=500):
    with database() as conn:
        rows = conn.execute(
            "SELECT timestamp, equity FROM equity_history ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return list(reversed([dict(row) for row in rows]))


init_database()


# ----------------------------- MARKET DATA -----------------------------

@st.cache_data(ttl=45, show_spinner=False)
def fetch_kraken_ohlc(pair: str, interval: int) -> pd.DataFrame:
    """Fetch public OHLC candles. No account or API key is required."""
    query = urllib.parse.urlencode({"pair": pair, "interval": int(interval)})
    url = f"https://api.kraken.com/0/public/OHLC?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATB99-PaperTerminal/1.4"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    errors = payload.get("error", [])
    if errors:
        raise RuntimeError("Kraken API: " + "; ".join(errors))

    result = payload.get("result", {})
    candle_key = next(
        (key for key, value in result.items() if key != "last" and isinstance(value, list)),
        None,
    )
    if candle_key is None:
        raise RuntimeError("Kraken не върна OHLC данни за тази двойка.")

    rows = result[candle_key]
    # Kraken includes the currently forming candle as the final row.
    rows = rows[:-1]
    if len(rows) < 60:
        raise RuntimeError("Получените данни са недостатъчни за EMA 50.")

    frame = pd.DataFrame(
        [
            {
                "timestamp": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "vwap": float(row[5]),
                "volume": float(row[6]),
                "trades": int(row[7]),
            }
            for row in rows
        ]
    )
    return frame.sort_values("timestamp").reset_index(drop=True)


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    close = data["close"]

    data["ema20"] = close.ewm(span=20, adjust=False).mean()
    data["ema50"] = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    data["rsi14"] = 100 - (100 / (1 + rs))
    data.loc[avg_loss == 0, "rsi14"] = 100.0

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["atr14"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    # Signal is created only after the candle has closed.
    cross_up = (data["ema20"].shift(1) <= data["ema50"].shift(1)) & (data["ema20"] > data["ema50"])
    cross_down = (data["ema20"].shift(1) >= data["ema50"].shift(1)) & (data["ema20"] < data["ema50"])
    data["signal"] = "HOLD"
    data.loc[cross_up & data["rsi14"].between(45, 68), "signal"] = "BUY"
    data.loc[cross_down, "signal"] = "SELL"

    return data.dropna(subset=["ema20", "ema50", "rsi14", "atr14"]).reset_index(drop=True)


def market_snapshot(symbol: str, interval: int) -> pd.DataFrame:
    raw = fetch_kraken_ohlc(MARKETS[symbol], interval)
    return add_indicators(raw)


# ----------------------------- PORTFOLIO -----------------------------

def marked_equity(account: dict, positions: dict, market: dict) -> float:
    total = float(account["cash"])
    for symbol, position in positions.items():
        if symbol in market:
            price = float(market[symbol].iloc[-1]["close"])
            total += float(position["quantity"]) * price
    return total


def insert_trade(conn, symbol, side, price, quantity, fee, pnl, reason):
    conn.execute(
        """INSERT INTO trades (timestamp, symbol, side, price, quantity, fee, pnl, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            symbol,
            side,
            float(price),
            float(quantity),
            float(fee),
            float(pnl),
            reason,
        ),
    )


def execute_paper_cycle(market: dict) -> list[str]:
    messages = []
    today = datetime.now(timezone.utc).date().isoformat()

    with database() as conn:
        account_row = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
        account = dict(account_row)
        pos_rows = conn.execute("SELECT * FROM positions").fetchall()
        positions = {row["symbol"]: dict(row) for row in pos_rows}

        equity_now = marked_equity(account, positions, market)
        if account["daily_date"] != today:
            account["daily_date"] = today
            account["day_start_equity"] = equity_now
            account["halted"] = 0

        if account["day_start_equity"] > 0 and equity_now <= account["day_start_equity"] * (1 - DAILY_LOSS_LIMIT):
            account["halted"] = 1

        for symbol, frame in market.items():
            last = frame.iloc[-1]
            candle_time = int(last["timestamp"])
            processed_row = conn.execute(
                "SELECT candle_time FROM processed_candles WHERE symbol=?", (symbol,)
            ).fetchone()
            if processed_row and candle_time <= int(processed_row["candle_time"]):
                messages.append(f"{symbol}: тази затворена свещ вече е обработена.")
                continue

            conn.execute(
                "INSERT INTO processed_candles(symbol, candle_time) VALUES(?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET candle_time=excluded.candle_time",
                (symbol, candle_time),
            )

            position = positions.get(symbol)
            close_price = float(last["close"])
            signal = str(last["signal"])

            if position is not None:
                if candle_time <= int(position["entry_candle"]):
                    messages.append(f"{symbol}: изчакване на следваща затворена свещ.")
                    continue

                stop_hit = float(last["low"]) <= float(position["stop_price"])
                target_hit = float(last["high"]) >= float(position["target_price"])
                exit_reason = None
                exit_reference = None

                # Conservative assumption when both levels are reached in one candle.
                if stop_hit:
                    exit_reason = "STOP LOSS"
                    exit_reference = float(position["stop_price"])
                elif target_hit:
                    exit_reason = "TAKE PROFIT"
                    exit_reference = float(position["target_price"])
                elif signal == "SELL":
                    exit_reason = "SELL SIGNAL"
                    exit_reference = close_price

                if exit_reason is not None:
                    fill_price = exit_reference * (1 - SLIPPAGE_RATE)
                    quantity = float(position["quantity"])
                    exit_fee = quantity * fill_price * FEE_RATE
                    pnl = (
                        quantity * (fill_price - float(position["entry_price"]))
                        - float(position["entry_fee"])
                        - exit_fee
                    )
                    account["cash"] += quantity * fill_price - exit_fee
                    account["realized_pnl"] += pnl
                    insert_trade(
                        conn, symbol, "SELL", fill_price, quantity,
                        exit_fee, pnl, exit_reason
                    )
                    conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
                    positions.pop(symbol, None)
                    messages.append(f"{symbol}: {exit_reason} | резултат {pnl:+.2f} USDT")
                else:
                    messages.append(f"{symbol}: позицията остава отворена.")
                continue

            # Daily drawdown blocks new entries, but existing positions can still exit.
            if account["halted"]:
                messages.append(f"{symbol}: новите входове са спрени от Risk Manager.")
                continue

            if signal != "BUY":
                messages.append(f"{symbol}: HOLD — няма входящ сигнал.")
                continue

            atr = float(last["atr14"])
            if atr <= 0:
                messages.append(f"{symbol}: невалиден ATR, входът е пропуснат.")
                continue

            entry_price = close_price * (1 + SLIPPAGE_RATE)
            stop_distance = max(1.5 * atr, entry_price * 0.005)
            risk_budget = max(0.0, float(account["cash"])) * RISK_PER_TRADE
            quantity_by_risk = risk_budget / stop_distance
            quantity_by_allocation = (
                float(account["cash"]) * MAX_ALLOCATION
                / (entry_price * (1 + FEE_RATE))
            )
            quantity = min(quantity_by_risk, quantity_by_allocation)
            gross_cost = quantity * entry_price
            entry_fee = gross_cost * FEE_RATE

            if quantity <= 0 or gross_cost + entry_fee > float(account["cash"]):
                messages.append(f"{symbol}: недостатъчен виртуален баланс.")
                continue

            stop_price = entry_price - stop_distance
            target_price = entry_price + 2 * stop_distance
            account["cash"] -= gross_cost + entry_fee
            conn.execute(
                """INSERT INTO positions (symbol, quantity, entry_price, entry_fee, stop_price, target_price, entry_candle) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (symbol, quantity, entry_price, entry_fee, stop_price, target_price, candle_time),
            )
            positions[symbol] = {
                "symbol": symbol,
                "quantity": quantity,
                "entry_price": entry_price,
                "entry_fee": entry_fee,
                "stop_price": stop_price,
                "target_price": target_price,
                "entry_candle": candle_time,
            }
            insert_trade(
                conn, symbol, "BUY", entry_price, quantity,
                entry_fee, 0.0, "EMA CROSS"
            )
            messages.append(
                f"{symbol}: виртуална покупка @ {entry_price:,.2f} | "
                f"SL {stop_price:,.2f} | TP {target_price:,.2f}"
            )

        current_equity = marked_equity(account, positions, market)
        if account["day_start_equity"] > 0 and current_equity <= account["day_start_equity"] * (1 - DAILY_LOSS_LIMIT):
            account["halted"] = 1

        conn.execute(
            """UPDATE account SET cash=?, realized_pnl=?, daily_date=?, day_start_equity=?, halted=? WHERE id=1""",
            (
                account["cash"], account["realized_pnl"], account["daily_date"],
                account["day_start_equity"], account["halted"],
            ),
        )
        conn.execute(
            "INSERT INTO equity_history(timestamp, equity) VALUES(?, ?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), current_equity),
        )

    if not messages:
        messages.append("Няма нови действия.")
    return messages


# ----------------------------- BACKTEST -----------------------------

def run_backtest(frame: pd.DataFrame, starting_cash: float = START_BALANCE) -> dict:
    """Historical simulation: signal at close, fill at next candle open."""
    data = frame.reset_index(drop=True)
    if len(data) < 70:
        raise ValueError("Няма достатъчно исторически свещи за Backtesting.")

    cash = float(starting_cash)
    position = None
    trades = []
    equity_points = []

    for i in range(55, len(data)):
        candle = data.iloc[i]
        previous = data.iloc[i - 1]
        candle_open = float(candle["open"])
        candle_high = float(candle["high"])
        candle_low = float(candle["low"])
        candle_close = float(candle["close"])
        exited_this_candle = False

        # Existing position: previous-close SELL signal is filled at this open.
        if position is not None:
            exit_price = None
            reason = None

            if str(previous["signal"]) == "SELL":
                exit_price = candle_open * (1 - SLIPPAGE_RATE)
                reason = "SELL SIGNAL"
            else:
                stop_hit = candle_low <= position["stop"]
                target_hit = candle_high >= position["target"]
                if stop_hit:
                    exit_reference = min(candle_open, position["stop"])
                    exit_price = exit_reference * (1 - SLIPPAGE_RATE)
                    reason = "STOP LOSS"
                elif target_hit:
                    exit_price = position["target"] * (1 - SLIPPAGE_RATE)
                    reason = "TAKE PROFIT"

            if exit_price is not None:
                quantity = position["quantity"]
                exit_fee = quantity * exit_price * FEE_RATE
                pnl = (
                    quantity * (exit_price - position["entry"])
                    - position["entry_fee"] - exit_fee
                )
                cash += quantity * exit_price - exit_fee
                trades.append({
                    "Вход": position["entry"],
                    "Изход": exit_price,
                    "Количество": quantity,
                    "Резултат USDT": pnl,
                    "Причина": reason,
                })
                position = None
                exited_this_candle = True

        # Entry: a signal at the previous close is filled at current open.
        if position is None and not exited_this_candle and str(previous["signal"]) == "BUY":
            entry_price = candle_open * (1 + SLIPPAGE_RATE)
            atr_value = float(previous["atr14"])
            if atr_value > 0:
                stop_distance = max(1.5 * atr_value, entry_price * 0.005)
                risk_budget = cash * RISK_PER_TRADE
                qty_by_risk = risk_budget / stop_distance
                qty_by_cap = cash * MAX_ALLOCATION / (entry_price * (1 + FEE_RATE))
                quantity = min(qty_by_risk, qty_by_cap)
                entry_fee = quantity * entry_price * FEE_RATE
                gross_cost = quantity * entry_price

                if quantity > 0 and gross_cost + entry_fee <= cash:
                    cash -= gross_cost + entry_fee
                    position = {
                        "entry": entry_price,
                        "quantity": quantity,
                        "entry_fee": entry_fee,
                        "stop": entry_price - stop_distance,
                      
