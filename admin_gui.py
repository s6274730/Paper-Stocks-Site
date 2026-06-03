
import socket
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

from admin import send, check_admin_password
from crypto_channel import SecureChannel

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5001
REFRESH_MS = 3000      # active-user list refresh interval
SOCK_TIMEOUT = 10      # seconds


class AdminGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Casino Admin")
        self.geometry("460x520")
        self.minsize(420, 460)

        self.sock = None
        self.f = None
        self.chan = None
        self._refresh_job = None
        self._users = []          # rows aligned with the listbox
        self._search_mode = False  # showing search results instead of live active list

        self.container = ttk.Frame(self, padding=16)
        self.container.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_login()

    # ---------- helpers ----------
    def _clear(self):
        for child in self.container.winfo_children():
            child.destroy()

    def _close_socket(self):
        if self.chan is not None:
            try:
                send(self.chan, {"cmd": "QUIT"})
            except Exception:
                pass
        if self.f is not None:
            try:
                self.f.close()
            except Exception:
                pass
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
        self.chan = None
        self.f = None
        self.sock = None

    # ---------- login screen ----------
    def _build_login(self):
        self._clear()
        self.title("Casino Admin - Login")

        ttk.Label(self.container, text="Admin Login",
                  font=("Segoe UI", 16, "bold")).pack(pady=(8, 16))

        form = ttk.Frame(self.container)
        form.pack()

        ttk.Label(form, text="Password:").grid(row=0, column=0, sticky="e", padx=4, pady=6)
        self.pass_var = tk.StringVar()
        pwd = ttk.Entry(form, textvariable=self.pass_var, width=26, show="*")
        pwd.grid(row=0, column=1, pady=6)

        ttk.Label(form, text="Host:").grid(row=1, column=0, sticky="e", padx=4, pady=6)
        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        ttk.Entry(form, textvariable=self.host_var, width=26).grid(row=1, column=1, pady=6)

        ttk.Label(form, text="Port:").grid(row=2, column=0, sticky="e", padx=4, pady=6)
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(form, textvariable=self.port_var, width=26).grid(row=2, column=1, pady=6)

        ttk.Button(self.container, text="Log In", command=self._do_login).pack(pady=16)
        pwd.bind("<Return>", lambda e: self._do_login())
        pwd.focus_set()

        self.login_status = ttk.Label(self.container, text="", foreground="red")
        self.login_status.pack()

    def _do_login(self):
        # same login logic as admin.py: SHA-256 password check
        if not check_admin_password(self.pass_var.get()):
            self.login_status.config(text="Incorrect password.")
            return

        host = self.host_var.get().strip() or DEFAULT_HOST
        try:
            port = int(self.port_var.get().strip() or DEFAULT_PORT)
        except ValueError:
            self.login_status.config(text="Port must be a number.")
            return

        self.login_status.config(text="Connecting...", foreground="black")
        self.update_idletasks()
        try:
            self.sock = socket.create_connection((host, port), timeout=SOCK_TIMEOUT)
            self.sock.settimeout(SOCK_TIMEOUT)
            self.f = self.sock.makefile("rwb")
        except OSError as exc:
            self.sock = None
            self.f = None
            self.login_status.config(text=f"Connect failed: {exc}", foreground="red")
            return

        try:
            self.chan = SecureChannel.client_handshake(self.f)
        except Exception as exc:
            self._close_socket()
            self.login_status.config(text=f"Secure handshake failed: {exc}", foreground="red")
            return

        self._build_dashboard()

    # ---------- dashboard screen ----------
    def _build_dashboard(self):
        self._clear()
        self.title("Casino Admin - Dashboard")

        header = ttk.Frame(self.container)
        header.pack(fill="x")
        self.list_title = ttk.Label(header, text="Active Users",
                                    font=("Segoe UI", 14, "bold"))
        self.list_title.pack(side="left")
        ttk.Button(header, text="Log Out", command=self._logout).pack(side="right")

        search = ttk.Frame(self.container)
        search.pack(fill="x", pady=(10, 0))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True)
        search_entry.bind("<Return>", lambda e: self._do_search())
        ttk.Button(search, text="Search", command=self._do_search).pack(
            side="left", padx=(4, 0))
        ttk.Button(search, text="Active", command=self._show_active).pack(
            side="left", padx=(4, 0))

        list_frame = ttk.Frame(self.container)
        list_frame.pack(fill="both", expand=True, pady=(10, 6))
        self.user_list = tk.Listbox(list_frame, font=("Consolas", 11), activestyle="none")
        self.user_list.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.user_list.yview)
        scroll.pack(side="right", fill="y")
        self.user_list.config(yscrollcommand=scroll.set)
        self.user_list.bind("<Double-Button-1>", lambda e: self._view_wallet())

        actions = ttk.Frame(self.container)
        actions.pack(fill="x", pady=6)
        ttk.Button(actions, text="View Wallet", command=self._view_wallet).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(actions, text="Add Funds", command=self._add_funds).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

        self.status = ttk.Label(self.container, text="", foreground="gray")
        self.status.pack(anchor="w", pady=(6, 0))

        self._refresh_users()

    def _selected_user(self):
        sel = self.user_list.curselection()
        if not sel:
            messagebox.showinfo("No selection", "Select a user first.")
            return None
        return self._users[sel[0]]

    def _refresh_users(self):
        if self._search_mode:
            # paused while viewing search results; check back later
            self._refresh_job = self.after(REFRESH_MS, self._refresh_users)
            return
        try:
            resp = send(self.chan, {"cmd": "LIST"})
        except Exception as exc:
            self.status.config(text=f"Disconnected: {exc}", foreground="red")
            messagebox.showerror("Connection lost", f"{exc}\n\nReturning to login.")
            self._logout()
            return

        if resp is None or not resp.get("ok"):
            self.status.config(text="Server error fetching users.", foreground="red")
        else:
            users = resp.get("users", [])
            prev_id = None
            sel = self.user_list.curselection()
            if sel:
                prev_id = self._users[sel[0]]["id"]

            self._users = users
            self.user_list.delete(0, tk.END)
            for u in users:
                self.user_list.insert(tk.END, f"[{u['id']}] {u['name']} <{u['email']}>")

            for i, u in enumerate(users):
                if u["id"] == prev_id:
                    self.user_list.selection_set(i)
                    break

            n = len(users)
            stamp = datetime.now().strftime("%H:%M:%S")
            self.status.config(
                text=f"{n} active user{'s' if n != 1 else ''} - updated {stamp}",
                foreground="gray")

        self._refresh_job = self.after(REFRESH_MS, self._refresh_users)

    # ---------- search ----------
    def _do_search(self):
        query = self.search_var.get().strip()
        if not query:
            self._show_active()
            return
        try:
            resp = send(self.chan, {"cmd": "SEARCH", "query": query})
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            return
        if resp is None or not resp.get("ok"):
            messagebox.showwarning("Search", (resp or {}).get("error", "Search failed."))
            return

        self._search_mode = True
        self.list_title.config(text=f"Search: {query}")
        users = resp.get("users", [])
        self._users = users
        self.user_list.delete(0, tk.END)
        for u in users:
            status = "online" if u.get("online") else "offline"
            self.user_list.insert(tk.END, f"[{u['id']}] {u['name']} <{u['email']}> ({status})")
        n = len(users)
        self.status.config(
            text=f"{n} match{'es' if n != 1 else ''} for '{query}'", foreground="gray")

    def _show_active(self):
        self.search_var.set("")
        self._search_mode = False
        self.list_title.config(text="Active Users")
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        self._refresh_users()

    # ---------- actions ----------
    def _view_wallet(self):
        user = self._selected_user()
        if not user:
            return
        try:
            resp = send(self.chan, {"cmd": "WALLET", "user_id": user["id"]})
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            return
        if resp is None or not resp.get("ok"):
            messagebox.showwarning("Wallet", (resp or {}).get("error", "No wallet."))
            return

        lines = [f"User:    [{user['id']}] {user['name']}",
                 f"Balance: ${resp['balance_usd']:,.2f}",
                 ""]
        holdings = resp.get("holdings", [])
        if holdings:
            lines.append("Holdings:")
            for h in holdings:
                lines.append(f"  {h['ticker']:<8} {h['shares']:.4f} sh"
                             f"   avg ${h['avg_price']:,.2f}")
        else:
            lines.append("Holdings: (none)")
        messagebox.showinfo(f"Wallet - {user['name']}", "\n".join(lines))

    def _add_funds(self):
        user = self._selected_user()
        if not user:
            return
        amount = simpledialog.askfloat(
            "Add Funds", f"Amount (USD) to add to {user['name']}:",
            parent=self)
        if amount is None:
            return
        try:
            resp = send(self.chan, {"cmd": "ADD", "user_id": user["id"], "amount": amount})
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            return
        if resp is None or not resp.get("ok"):
            messagebox.showwarning("Add Funds", (resp or {}).get("error", "Failed."))
            return
        messagebox.showinfo("Add Funds", resp.get("message", "Done."))

    # ---------- logout / close ----------
    def _logout(self):
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        self._close_socket()
        self._users = []
        self._build_login()

    def _on_close(self):
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
        self._close_socket()
        self.destroy()


if __name__ == "__main__":
    AdminGUI().mainloop()
