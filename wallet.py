import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")
STARTING_BALANCE = 100000.0


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wallets (
                user_id INTEGER PRIMARY KEY,
                balance_usd REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                shares REAL NOT NULL DEFAULT 0,
                cost_basis_usd REAL NOT NULL DEFAULT 0,
                UNIQUE(user_id, ticker),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )


def create_wallet(user_id):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO wallets (user_id, balance_usd) VALUES (?, ?)",
            (user_id, STARTING_BALANCE),
        )


def ensure_wallet(user_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM wallets WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO wallets (user_id, balance_usd) VALUES (?, ?)",
                (user_id, STARTING_BALANCE),
            )


def get_wallet(user_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT balance_usd FROM wallets WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {"balance_usd": float(row["balance_usd"])}


def get_holdings(user_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ticker, shares, cost_basis_usd FROM holdings "
            "WHERE user_id = ? AND shares > 0 ORDER BY ticker",
            (user_id,),
        ).fetchall()
    return [
        {
            "ticker": r["ticker"],
            "shares": float(r["shares"]),
            "cost_basis_usd": float(r["cost_basis_usd"]),
            "avg_price": (float(r["cost_basis_usd"]) / float(r["shares"])) if r["shares"] else 0.0,
        }
        for r in rows
    ]


def buy(user_id, ticker, usd_amount, price):
    ticker = ticker.strip().upper()
    if not ticker:
        return False, "Ticker required."
    if usd_amount <= 0:
        return False, "Amount must be positive."
    if price <= 0:
        return False, "Invalid price."

    with get_db() as conn:
        row = conn.execute(
            "SELECT balance_usd FROM wallets WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return False, "Wallet not found."
        balance = float(row["balance_usd"])
        if usd_amount > balance:
            return False, f"Not enough funds. Balance: ${balance:,.2f}"

        shares = usd_amount / price
        conn.execute(
            "UPDATE wallets SET balance_usd = balance_usd - ? WHERE user_id = ?",
            (usd_amount, user_id),
        )
        existing = conn.execute(
            "SELECT id FROM holdings WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE holdings SET shares = shares + ?, cost_basis_usd = cost_basis_usd + ? "
                "WHERE user_id = ? AND ticker = ?",
                (shares, usd_amount, user_id, ticker),
            )
        else:
            conn.execute(
                "INSERT INTO holdings (user_id, ticker, shares, cost_basis_usd) "
                "VALUES (?, ?, ?, ?)",
                (user_id, ticker, shares, usd_amount),
            )

    return True, f"Bought {shares:.6f} shares of {ticker} at ${price:,.2f} for ${usd_amount:,.2f}."
