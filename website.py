import hashlib
import os
import secrets
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session
import smtp
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
                birthdate TEXT NOT NULL,
                is_verified INTEGER NOT NULL DEFAULT 0,
                verification_token TEXT
            )
            """
        )
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "is_verified" not in existing:
            conn.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
        if "verification_token" not in existing:
            conn.execute("ALTER TABLE users ADD COLUMN verification_token TEXT")


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


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
                "SELECT id, name, password_hash, is_verified FROM users WHERE email = ?",
                (email,),
            ).fetchone()

        if user is None or user["password_hash"] != hash_password(password):
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

        password_hash = hash_password(password)
        token = secrets.token_urlsafe(32)

        try:
            with get_db() as conn:
                cursor = conn.execute(
                    "INSERT INTO users (name, email, password_hash, birthdate, is_verified, verification_token) "
                    "VALUES (?, ?, ?, ?, 0, ?)",
                    (name, email, password_hash, birthdate, token),
                )
                user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            flash("Email already registered.")
            return redirect(url_for("signup"))

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
    app.run(debug=True)
