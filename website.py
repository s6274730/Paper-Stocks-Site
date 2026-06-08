import datetime
import hashlib
import ipaddress
import json
import os
import secrets
import socket as sock
import sqlite3
import threading
import time
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
from cryptography.x509.oid import NameOID
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from crypto_channel import SecureChannel, generate_rsa_keypair
from aichat import AIChatService
from smtp import Mailer
from stocks import StockService
from wallet import WalletService

CERT_FILE = os.path.join(os.path.dirname(__file__), "cert.pem")
KEY_FILE  = os.path.join(os.path.dirname(__file__), "key.pem")

ADMIN_PORT = 5001
_admin_rsa_key = None  # RSA private key for the admin channel, set when the server starts

def _ensure_tls_cert():
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return
    key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(KEY_FILE, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))


active_users = {}  # user_id -> {id, name, email, last_seen}
_active_lock = threading.Lock()
ACTIVE_TIMEOUT = 15  # seconds without a heartbeat before a user drops off the list


def _touch_active(user):
    with _active_lock:
        active_users[user["id"]] = {**user, "last_seen": time.time()}


def _prune_active_users():
    cutoff = time.time() - ACTIVE_TIMEOUT
    with _active_lock:
        stale = [uid for uid, u in active_users.items() if u["last_seen"] < cutoff]
        for uid in stale:
            active_users.pop(uid, None)


def _handle_admin_client(conn):
    f = conn.makefile("rwb")
    try:
        try:
            chan = SecureChannel.server_handshake(f, _admin_rsa_key)
        except Exception:
            return

        admin_status = None  # None = not authenticated

        while True:
            try:
                req = chan.recv_json()
            except Exception:
                chan.send_json({"ok": False, "error": "bad request"})
                continue
            if req is None:
                break

            cmd = req.get("cmd", "")

            if cmd == "AUTH":
                username = (req.get("username") or "").strip()
                password = req.get("password", "")
                with users_repo.get_db() as db:
                    row = db.execute(
                        "SELECT id, password_hash, salt, status FROM users WHERE name = ?",
                        (username,),
                    ).fetchone()
                if row is None or UserRepository.hash_password(password, bytes.fromhex(row["salt"])) != row["password_hash"]:
                    resp = {"ok": False, "error": "Invalid username or password."}
                elif row["status"] not in ("Admin", "Owner"):
                    resp = {"ok": False, "error": "Not an admin account."}
                else:
                    admin_status = row["status"]
                    resp = {"ok": True, "status": admin_status}

            elif admin_status is None:
                resp = {"ok": False, "error": "Not authenticated."}

            elif cmd == "LIST":
                _prune_active_users()
                with _active_lock:
                    users = sorted(
                        ({"id": u["id"], "name": u["name"], "email": u["email"]}
                         for u in active_users.values()),
                        key=lambda u: u["id"],
                    )
                resp = {"ok": True, "users": users}

            elif cmd == "SEARCH":
                q = (req.get("query") or "").strip()
                if not q:
                    resp = {"ok": True, "users": []}
                else:
                    with users_repo.get_db() as db:
                        rows = db.execute(
                            "SELECT id, name, email, status FROM users WHERE name LIKE ? ORDER BY name LIMIT 50",
                            (f"%{q}%",),
                        ).fetchall()
                    _prune_active_users()
                    with _active_lock:
                        online = set(active_users.keys())
                    resp = {"ok": True, "users": [
                        {"id": r["id"], "name": r["name"], "email": r["email"],
                         "status": r["status"], "online": r["id"] in online}
                        for r in rows
                    ]}

            elif cmd == "WALLET":
                uid = req.get("user_id")
                w = wallet_service.get_wallet(uid)
                if w is None:
                    resp = {"ok": False, "error": f"User {uid} has no wallet."}
                else:
                    holdings = wallet_service.get_holdings(uid)
                    resp = {"ok": True, "balance_usd": w["balance_usd"], "holdings": holdings}

            elif cmd == "ADD":
                uid = req.get("user_id")
                amount = req.get("amount", 0)
                with users_repo.get_db() as db:
                    row = db.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
                    if row is None:
                        resp = {"ok": False, "error": f"User {uid} not found."}
                    else:
                        wallet_service.ensure_wallet(uid)
                        db.execute(
                            "UPDATE wallets SET balance_usd = balance_usd + ? WHERE user_id = ?",
                            (amount, uid),
                        )
                        resp = {"ok": True, "message": f"Added ${amount:,.2f} to user {uid}."}

            elif cmd == "SET_STATUS":
                if admin_status != "Owner":
                    resp = {"ok": False, "error": "Only Owners can change user status."}
                else:
                    uid = req.get("user_id")
                    new_status = req.get("status")
                    if new_status not in ("User", "Admin"):
                        resp = {"ok": False, "error": "Status must be 'User' or 'Admin'."}
                    else:
                        with users_repo.get_db() as db:
                            row = db.execute(
                                "SELECT id, status FROM users WHERE id = ?", (uid,)
                            ).fetchone()
                            if row is None:
                                resp = {"ok": False, "error": f"User {uid} not found."}
                            elif row["status"] == "Owner":
                                resp = {"ok": False, "error": "Cannot change Owner status."}
                            else:
                                db.execute(
                                    "UPDATE users SET status = ? WHERE id = ?", (new_status, uid)
                                )
                                resp = {"ok": True, "message": f"User {uid} status set to {new_status}."}

            elif cmd == "QUIT":
                chan.send_json({"ok": True, "message": "bye"})
                break

            else:
                resp = {"ok": False, "error": f"Unknown command: {cmd}"}

            chan.send_json(resp)
    except Exception:
        pass
    finally:
        f.close()
        conn.close()


def _run_admin_server():
    global _admin_rsa_key
    _admin_rsa_key = generate_rsa_keypair()
    srv = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
    srv.setsockopt(sock.SOL_SOCKET, sock.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", ADMIN_PORT))
    srv.listen(5)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=_handle_admin_client, args=(conn,), daemon=True).start()


class UserRepository:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_db() as conn:
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
                    verification_token TEXT,
                    status TEXT NOT NULL DEFAULT 'User'
                )
                """
            )
            try:
                conn.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'User'")
            except sqlite3.OperationalError:
                pass
            conn.execute("UPDATE users SET status = 'Owner' WHERE name = 'titangamer334'")

    @staticmethod
    def hash_password(password, salt):
        return hashlib.sha256(salt + password.encode("utf-8")).hexdigest()

    def find_by_email(self, email):
        with self.get_db() as conn:
            return conn.execute(
                "SELECT id, name, password_hash, salt, is_verified FROM users WHERE email = ?",
                (email,),
            ).fetchone()

    def create(self, name, email, password, birthdate):
        salt = os.urandom(16)
        password_hash = self.hash_password(password, salt)
        token = secrets.token_urlsafe(32)
        with self.get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash, salt, birthdate, is_verified, verification_token) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (name, email, password_hash, salt.hex(), birthdate, token),
            )
            user_id = cursor.lastrowid
        return user_id, token

    def delete(self, user_id):
        with self.get_db() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def verify_token(self, token):
        with self.get_db() as conn:
            user = conn.execute(
                "SELECT id FROM users WHERE verification_token = ? AND is_verified = 0",
                (token,),
            ).fetchone()
            if user is None:
                return False
            conn.execute(
                "UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?",
                (user["id"],),
            )
        return True


DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

app = Flask(__name__)
app.secret_key = "jcz"

users_repo = UserRepository(DB_PATH)
wallet_service = WalletService(DB_PATH)
stock_service = StockService()
mailer = Mailer()
ai_service = AIChatService()


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

        user = users_repo.find_by_email(email)

        if user is None or not user["salt"] or user["password_hash"] != UserRepository.hash_password(password, bytes.fromhex(user["salt"])):
            flash("Invalid email or password.")
            return redirect(url_for("login"))

        if not user["is_verified"]:
            flash("Please confirm your email before logging in. Check your inbox.")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        with users_repo.get_db() as db:
            row = db.execute("SELECT email FROM users WHERE id = ?", (user["id"],)).fetchone()
        session["user_email"] = row["email"]
        _touch_active({"id": user["id"], "name": user["name"], "email": row["email"]})
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    with _active_lock:
        active_users.pop(session.get("user_id"), None)
    session.clear()
    return redirect(url_for("index"))


@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    uid = session.get("user_id")
    if uid is None:
        return ("", 401)
    _touch_active({
        "id": uid,
        "name": session.get("user_name"),
        "email": session.get("user_email"),
    })
    return ("", 204)


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
            result = stock_service.get_price(ticker)
            if result is None:
                error = f"No price found for '{ticker.upper()}'."
            else:
                try:
                    history = stock_service.get_history(ticker, period=period)
                except Exception:
                    history = None
        except Exception as e:
            error = f"Lookup failed: {e}"

    wallet_service.ensure_wallet(session["user_id"])
    w = wallet_service.get_wallet(session["user_id"])
    shares_owned = 0.0
    transactions = []
    if result:
        shares_owned = wallet_service.get_shares(session["user_id"], result["ticker"])
        transactions = wallet_service.get_transactions(session["user_id"], result["ticker"])
    return render_template(
        "search.html",
        name=session.get("user_name"),
        ticker=ticker,
        result=result,
        history=history,
        period=period,
        error=error,
        balance=w["balance_usd"] if w else 0.0,
        shares_owned=shares_owned,
        transactions=transactions,
    )


@app.route("/api/suggest")
def suggest():
    if "user_id" not in session:
        return jsonify([]), 401
    query = request.args.get("q", "").strip()
    if len(query) < 1:
        return jsonify([])
    return jsonify(stock_service.search_symbols(query))


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
        price_info = stock_service.get_price(ticker)
    except Exception as e:
        flash(f"Price lookup failed: {e}")
        return redirect(url_for("search", ticker=ticker))

    if price_info is None:
        flash(f"No price for '{ticker.upper()}'.")
        return redirect(url_for("search", ticker=ticker))

    wallet_service.ensure_wallet(session["user_id"])
    ok, msg = wallet_service.buy(session["user_id"], ticker, amount, price_info["price"])
    flash(msg)
    return redirect(url_for("wallet_page") if ok else url_for("search", ticker=ticker))


@app.route("/sell", methods=["POST"])
def sell():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ticker = request.form.get("ticker", "").strip()
    shares_raw = request.form.get("shares", "").strip()
    redirect_to = request.form.get("redirect_to", "wallet")

    def back():
        if redirect_to == "search":
            return redirect(url_for("search", ticker=ticker))
        return redirect(url_for("wallet_page"))

    if shares_raw.lower() == "all":
        shares = wallet_service.get_shares(session["user_id"], ticker)
    else:
        try:
            shares = float(shares_raw)
        except ValueError:
            flash("Enter a valid share amount.")
            return back()

    try:
        price_info = stock_service.get_price(ticker)
    except Exception as e:
        flash(f"Price lookup failed: {e}")
        return back()

    if price_info is None:
        flash(f"No price for '{ticker.upper()}'.")
        return back()

    ok, msg = wallet_service.sell(session["user_id"], ticker, shares, price_info["price"])
    flash(msg)
    return back()


@app.route("/wallet")
def wallet_page():
    if "user_id" not in session:
        return redirect(url_for("login"))

    wallet_service.ensure_wallet(session["user_id"])
    w = wallet_service.get_wallet(session["user_id"])
    holdings = wallet_service.get_holdings(session["user_id"])

    enriched = []
    total_value = 0.0
    for h in holdings:
        current_price = None
        try:
            info = stock_service.get_price(h["ticker"])
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


@app.route("/chat")
def chat():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template(
        "chat.html",
        name=session.get("user_name"),
        history=session.get("chat_history", []),
    )


@app.route("/chat/send", methods=["POST"])
def chat_send():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401

    message = (request.get_json(silent=True) or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message."}), 400

    history = session.get("chat_history", [])
    history.append({"role": "user", "content": message})

    try:
        reply = ai_service.reply(history)
    except Exception as e:
        history.pop()
        session["chat_history"] = history
        return jsonify({"error": f"AI request failed: {e}"}), 502

    history.append({"role": "assistant", "content": reply})
    session["chat_history"] = history
    return jsonify({"reply": reply})


@app.route("/chat/reset", methods=["POST"])
def chat_reset():
    session.pop("chat_history", None)
    return jsonify({"ok": True})


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

        try:
            user_id, token = users_repo.create(name, email, password, birthdate)
        except sqlite3.IntegrityError:
            flash("Email already registered.")
            return redirect(url_for("signup"))

        wallet_service.create_wallet(user_id)

        link = url_for("verify", token=token, _external=True)
        try:
            mailer.send_verification(email, name, link)
        except Exception as e:
            users_repo.delete(user_id)
            flash(f"Could not send confirmation email: {e}")
            return redirect(url_for("signup"))

        return render_template("check_email.html", email=email)

    return render_template("signup.html")


@app.route("/verify/<token>")
def verify(token):
    ok = users_repo.verify_token(token)
    return render_template("verify_result.html", ok=ok)


if __name__ == "__main__":
    _ensure_tls_cert()
    users_repo.init_db()
    wallet_service.init_db()
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=_run_admin_server, daemon=True).start()
    app.run(debug=True, host="0.0.0.0", ssl_context=(CERT_FILE, KEY_FILE), threaded=True)
