import hashlib
import os
import secrets
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session
import smtp
import stocks
import wallet
app = Flask(__name__)
app.secret_key = "jcz"
DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                birthdate TEXT NOT NULL,
                is_verified INTEGER NOT NULL DEFAULT 0,
                verification_token TEXT
            )
            """
        )


def hash_password(password, salt):
    return hashlib.sha256(salt + password.encode("utf-8")).hexdigest()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not (email and password):
            flash("Email and password required.")
            return redirect(url_for("login"))

        with get_db() as conn:
            user = conn.execute(
                "SELECT id, name, password_hash, salt, is_verified FROM users WHERE email = ?",
                (email,),
            ).fetchone()

        if user is None or not user["salt"] or user["password_hash"] != hash_password(password, bytes.fromhex(user["salt"])):
            flash("Invalid email or password.")
            return redirect(url_for("login"))

        if not user["is_verified"]:
            flash("Please confirm your email before logging in. Check your inbox.")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/home")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("home.html", name=session.get("user_name"))


@app.route("/search")
def search():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ticker = request.args.get("ticker", "").strip()
    period = request.args.get("period", "1y").strip()
    result = None
    history = None
    error = None

    if ticker:
        try:
            result = stocks.get_price(ticker)
            if result is None:
                error = f"No price found for '{ticker.upper()}'."
            else:
                try:
                    history = stocks.get_history(ticker, period=period)
                except Exception:
                    history = None
        except Exception as e:
            error = f"Lookup failed: {e}"

    wallet.ensure_wallet(session["user_id"])
    w = wallet.get_wallet(session["user_id"])
    return render_template(
        "search.html",
        name=session.get("user_name"),
        ticker=ticker,
        result=result,
        history=history,
        period=period,
        error=error,
        balance=w["balance_usd"] if w else 0.0,
    )


@app.route("/buy", methods=["POST"])
def buy():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ticker = request.form.get("ticker", "").strip()
    amount_raw = request.form.get("amount", "").strip()

    try:
        amount = float(amount_raw)
    except ValueError:
        flash("Enter a valid USD amount.")
        return redirect(url_for("search", ticker=ticker))

    try:
        price_info = stocks.get_price(ticker)
    except Exception as e:
        flash(f"Price lookup failed: {e}")
        return redirect(url_for("search", ticker=ticker))

    if price_info is None:
        flash(f"No price for '{ticker.upper()}'.")
        return redirect(url_for("search", ticker=ticker))

    wallet.ensure_wallet(session["user_id"])
    ok, msg = wallet.buy(session["user_id"], ticker, amount, price_info["price"])
    flash(msg)
    return redirect(url_for("wallet_page") if ok else url_for("search", ticker=ticker))


@app.route("/wallet")
def wallet_page():
    if "user_id" not in session:
        return redirect(url_for("login"))

    wallet.ensure_wallet(session["user_id"])
    w = wallet.get_wallet(session["user_id"])
    holdings = wallet.get_holdings(session["user_id"])

    enriched = []
    total_value = 0.0
    for h in holdings:
        current_price = None
        try:
            info = stocks.get_price(h["ticker"])
            if info:
                current_price = info["price"]
        except Exception:
            current_price = None
        market_value = (current_price * h["shares"]) if current_price else None
        if market_value is not None:
            total_value += market_value
        enriched.append({**h, "current_price": current_price, "market_value": market_value})

    return render_template(
        "wallet.html",
        name=session.get("user_name"),
        balance=w["balance_usd"] if w else 0.0,
        holdings=enriched,
        total_value=total_value,
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        birthdate = request.form.get("birthdate", "")

        if not (name and email and password and birthdate):
            flash("All fields are required.")
            return redirect(url_for("signup"))

        salt = os.urandom(16)
        password_hash = hash_password(password, salt)
        token = secrets.token_urlsafe(32)

        try:
            with get_db() as conn:
                cursor = conn.execute(
                    "INSERT INTO users (name, email, password_hash, salt, birthdate, is_verified, verification_token) "
                    "VALUES (?, ?, ?, ?, ?, 0, ?)",
                    (name, email, password_hash, salt.hex(), birthdate, token),
                )
                user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            flash("Email already registered.")
            return redirect(url_for("signup"))

        wallet.create_wallet(user_id)

        link = url_for("verify", token=token, _external=True)
        try:
            smtp.send_verification(email, name, link)
        except Exception as e:
            with get_db() as conn:
                conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            flash(f"Could not send confirmation email: {e}")
            return redirect(url_for("signup"))

        return render_template("check_email.html", email=email)

    return render_template("signup.html")


@app.route("/verify/<token>")
def verify(token):
    with get_db() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE verification_token = ? AND is_verified = 0",
            (token,),
        ).fetchone()
        if user is None:
            return render_template("verify_result.html", ok=False)
        conn.execute(
            "UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?",
            (user["id"],),
        )
    return render_template("verify_result.html", ok=True)


if __name__ == "__main__":
    init_db()
    wallet.init_db()
    app.run(debug=True)
