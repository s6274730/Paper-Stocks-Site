import os
import sqlite3


class WalletService:
    DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")
    STARTING_BALANCE = 100000.0

    def __init__(self, db_path=None):
        if db_path:
            self.DB_PATH = db_path

    def get_db(self):
        conn = sqlite3.connect(self.DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_db() as conn:
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                    shares REAL NOT NULL,
                    price REAL NOT NULL,
                    usd_amount REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
                """
            )

    def create_wallet(self, user_id):
        with self.get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO wallets (user_id, balance_usd) VALUES (?, ?)",
                (user_id, self.STARTING_BALANCE),
            )

    def ensure_wallet(self, user_id):
        with self.get_db() as conn:
            row = conn.execute(
                "SELECT 1 FROM wallets WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO wallets (user_id, balance_usd) VALUES (?, ?)",
                    (user_id, self.STARTING_BALANCE),
                )

    def get_wallet(self, user_id):
        with self.get_db() as conn:
            row = conn.execute(
                "SELECT balance_usd FROM wallets WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return {"balance_usd": float(row["balance_usd"])}

    def get_holdings(self, user_id):
        with self.get_db() as conn:
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

    def buy(self, user_id, ticker, usd_amount, price):
        ticker = ticker.strip().upper()
        if not ticker:
            return False, "Ticker required."
        if usd_amount <= 0:
            return False, "Amount must be positive."
        if price <= 0:
            return False, "Invalid price."

        with self.get_db() as conn:
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
            conn.execute(
                "INSERT INTO transactions (user_id, ticker, side, shares, price, usd_amount) "
                "VALUES (?, ?, 'BUY', ?, ?, ?)",
                (user_id, ticker, shares, price, usd_amount),
            )

        return True, f"Bought {shares:.6f} shares of {ticker} at ${price:,.2f} for ${usd_amount:,.2f}."

    def get_shares(self, user_id, ticker):
        ticker = ticker.strip().upper()
        with self.get_db() as conn:
            row = conn.execute(
                "SELECT shares FROM holdings WHERE user_id = ? AND ticker = ?",
                (user_id, ticker),
            ).fetchone()
        return float(row["shares"]) if row else 0.0

    def sell(self, user_id, ticker, shares_to_sell, price):
        ticker = ticker.strip().upper()
        if not ticker:
            return False, "Ticker required."
        if shares_to_sell <= 0:
            return False, "Shares must be positive."
        if price <= 0:
            return False, "Invalid price."

        with self.get_db() as conn:
            row = conn.execute(
                "SELECT shares, cost_basis_usd FROM holdings WHERE user_id = ? AND ticker = ?",
                (user_id, ticker),
            ).fetchone()
            if row is None or float(row["shares"]) <= 0:
                return False, f"No {ticker} shares to sell."
            held = float(row["shares"])
            cost_basis = float(row["cost_basis_usd"])
            if shares_to_sell > held + 1e-9:
                return False, f"Only {held:.6f} shares available."
            if shares_to_sell > held:
                shares_to_sell = held

            proceeds = shares_to_sell * price
            basis_removed = cost_basis * (shares_to_sell / held) if held > 0 else 0.0
            remaining_shares = held - shares_to_sell
            remaining_basis = cost_basis - basis_removed
            if remaining_shares < 1e-9:
                remaining_shares = 0.0
                remaining_basis = 0.0

            conn.execute(
                "UPDATE wallets SET balance_usd = balance_usd + ? WHERE user_id = ?",
                (proceeds, user_id),
            )
            conn.execute(
                "UPDATE holdings SET shares = ?, cost_basis_usd = ? "
                "WHERE user_id = ? AND ticker = ?",
                (remaining_shares, remaining_basis, user_id, ticker),
            )
            conn.execute(
                "INSERT INTO transactions (user_id, ticker, side, shares, price, usd_amount) "
                "VALUES (?, ?, 'SELL', ?, ?, ?)",
                (user_id, ticker, shares_to_sell, price, proceeds),
            )

        return True, f"Sold {shares_to_sell:.6f} shares of {ticker} at ${price:,.2f} for ${proceeds:,.2f}."

    def get_transactions(self, user_id, ticker=None):
        with self.get_db() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT ticker, side, shares, price, usd_amount, created_at "
                    "FROM transactions WHERE user_id = ? AND ticker = ? "
                    "ORDER BY created_at DESC, id DESC",
                    (user_id, ticker.strip().upper()),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ticker, side, shares, price, usd_amount, created_at "
                    "FROM transactions WHERE user_id = ? "
                    "ORDER BY created_at DESC, id DESC",
                    (user_id,),
                ).fetchall()
        return [dict(r) for r in rows]
