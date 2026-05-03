import hashlib
import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "change-me-in-production"

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
                birthdate TEXT NOT NULL
            )
            """
        )


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login")
def login():
    return render_template("login.html")


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

        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO users (name, email, password_hash, birthdate) "
                    "VALUES (?, ?, ?, ?)",
                    (name, email, password_hash, birthdate),
                )
        except sqlite3.IntegrityError:
            flash("Email already registered.")
            return redirect(url_for("signup"))

        return redirect(url_for("login"))

    return render_template("signup.html")


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
