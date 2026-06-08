import socket
import sys

from crypto_channel import SecureChannel


def send(chan, payload):
    chan.send_json(payload)
    try:
        resp = chan.recv_json()
    except Exception:
        return None
    if resp is None:
        raise ConnectionError("Server closed connection.")
    return resp


def cmd_auth(chan, username, password):
    resp = send(chan, {"cmd": "AUTH", "username": username, "password": password})
    if resp is None or not resp.get("ok"):
        return None
    return resp.get("status")


def cmd_list(f):
    resp = send(f, {"cmd": "LIST"})
    if resp is None:
        print("No Active Users")
        return None
    if not resp.get("ok"):
        print(f"Error: {resp.get('error')}")
        return []
    users = resp.get("users", [])
    print(f"Active users ({len(users)}):")
    for u in users:
        print(f"  [{u['id']}] {u['name']} <{u['email']}>")
    return users


def cmd_search(f, query):
    resp = send(f, {"cmd": "SEARCH", "query": query})
    if not resp.get("ok"):
        print(f"Error: {resp.get('error')}")
        return []
    users = resp.get("users", [])
    if not users:
        print("No matching users.")
        return []
    print(f"Matches ({len(users)}):")
    for u in users:
        status = "online" if u.get("online") else "offline"
        print(f"  [{u['id']}] {u['name']} <{u['email']}> ({status}) [{u.get('status', 'User')}]")
    return users


def cmd_wallet(f, uid):
    resp = send(f, {"cmd": "WALLET", "user_id": uid})
    if not resp.get("ok"):
        print(f"Error: {resp.get('error')}")
        return
    print(f"Balance: ${resp['balance_usd']:,.2f}")
    holdings = resp.get("holdings", [])
    if not holdings:
        print("Holdings: (none)")
        return
    print("Holdings:")
    for h in holdings:
        print(f"  {h['ticker']:<8} {h['shares']:.6f} sh   cost=${h['cost_basis_usd']:,.2f}   avg=${h['avg_price']:,.2f}")


def cmd_add(f, uid, amount):
    resp = send(f, {"cmd": "ADD", "user_id": uid, "amount": amount})
    print(resp.get("message") or resp.get("error") or resp)


def cmd_set_status(f, uid, new_status):
    resp = send(f, {"cmd": "SET_STATUS", "user_id": uid, "status": new_status})
    print(resp.get("message") or resp.get("error") or resp)


def prompt_int(label):
    raw = input(label).strip()
    try:
        return int(raw)
    except ValueError:
        print("Not an integer.")
        return None


def prompt_float(label):
    raw = input(label).strip()
    try:
        return float(raw)
    except ValueError:
        print("Not a number.")
        return None


def menu_loop(chan, admin_status):
    while True:
        print()
        print("1) List active users")
        print("2) Search users by username")
        print("3) View wallet")
        print("4) Add funds")
        if admin_status == "Owner":
            print("5) Change user status")
            print("6) Quit")
        else:
            print("5) Quit")
        choice = input("> ").strip()
        if choice == "1":
            cmd_list(chan)
        elif choice == "2":
            q = input("username: ").strip()
            cmd_search(chan, q)
        elif choice == "3":
            uid = prompt_int("user_id: ")
            if uid is not None:
                cmd_wallet(chan, uid)
        elif choice == "4":
            uid = prompt_int("user_id: ")
            if uid is None:
                continue
            amt = prompt_float("amount USD: ")
            if amt is None:
                continue
            cmd_add(chan, uid, amt)
        elif choice == "5" and admin_status == "Owner":
            uid = prompt_int("user_id: ")
            if uid is None:
                continue
            new_status = input("new status (User/Admin): ").strip()
            if new_status not in ("User", "Admin"):
                print("Must be 'User' or 'Admin'.")
                continue
            cmd_set_status(chan, uid, new_status)
        elif (choice == "6" and admin_status == "Owner") or (choice == "5" and admin_status != "Owner"):
            try:
                send(chan, {"cmd": "QUIT"})
            except Exception:
                pass
            return
        else:
            print("Unknown choice.")


def main():
    username = input("Username: ").strip()
    password = input("Enter admin password: ")
    host = input("Host: (leave blank for 127.0.0.1): ")
    port = input("Port: (leave blank for 5001): ")
    if host == "":
        host = "127.0.0.1"
    if port == "":
        port = 5001

    try:
        s = socket.create_connection((host, port), timeout=10)
    except OSError as e:
        print(f"Connect failed: {e}")
        sys.exit(1)

    print(f"Connected to {host}:{port}")
    with s:
        f = s.makefile("rwb")
        try:
            chan = SecureChannel.client_handshake(f)
        except Exception as e:
            print(f"Secure handshake failed: {e}")
            f.close()
            sys.exit(1)
        print("Secure channel established (RSA key exchange + AES-256-GCM).")

        admin_status = cmd_auth(chan, username, password)
        if admin_status is None:
            print("Authentication failed.")
            f.close()
            sys.exit(1)
        print(f"Logged in as {username} ({admin_status}).")

        try:
            menu_loop(chan, admin_status)
        except (KeyboardInterrupt, EOFError):
            print()
        finally:
            f.close()


if __name__ == "__main__":
    main()
