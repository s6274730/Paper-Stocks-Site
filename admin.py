import json
import socket
import sys
import hashlib

def send(sock_file, payload):
    sock_file.write((json.dumps(payload) + "\n").encode("utf-8"))
    sock_file.flush()
    line = sock_file.readline()
    if not line:
        raise ConnectionError("Server closed connection.")
    try:
        return json.loads(line.decode("utf-8"))
    except:
        return None


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


def menu_loop(f):
    while True:
        print()
        print("1) List active users")
        print("2) View wallet")
        print("3) Add funds")
        print("4) Quit")
        choice = input("> ").strip()
        if choice == "1":
            cmd_list(f)
        elif choice == "2":
            uid = prompt_int("user_id: ")
            if uid is not None:
                cmd_wallet(f, uid)
        elif choice == "3":
            uid = prompt_int("user_id: ")
            if uid is None:
                continue
            amt = prompt_float("amount USD: ")
            if amt is None:
                continue
            cmd_add(f, uid, amt)
        elif choice == "4":
            try:
                send(f, {"cmd": "QUIT"})
            except Exception:
                pass
            return
        else:
            print("Unknown choice.")


def main():
    entered_pass = ""
    while entered_pass!="0b14d501a594442a01c6859541bcb3e8164d183d32937b851835442f69d5c94e":
        if entered_pass!="":
            print("Incorrect password.")
        entered_pass = hashlib.sha256(input("Enter admin password: ").encode()).hexdigest() #הסיסמה הוא password1
    host = input("Host: (leave blank for 127.0.0.1): ")
    port = input("Port: (leave blank for 5000): ")
    if host == "":
        host = "127.0.0.1"
    if port == "":
        port = 5000

    try:
        s = socket.create_connection((host, port), timeout=10)
    except OSError as e:
        print(f"Connect failed: {e}")
        sys.exit(1)

    print(f"Connected to {host}:{port}")
    with s:
        f = s.makefile("rwb")
        try:
            menu_loop(f)
        except (KeyboardInterrupt, EOFError):
            print()
        finally:
            f.close()


if __name__ == "__main__":
    main()
