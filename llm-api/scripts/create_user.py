"""
Create llm-api users, via the running API (default) or directly in the
SQLite database (--direct, for initial setup when the API is down).

Usage:
    python scripts/create_user.py alice secret123 [--role admin]
    python scripts/create_user.py alice secret123 --direct
    python scripts/create_user.py --list [--direct]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config

API_URL = f"http://localhost:{config.SERVER_PORT}"


def create_via_api(username: str, password: str, role: str) -> bool:
    import requests

    resp = requests.post(
        f"{API_URL}/api/auth/login",
        data={"username": config.DEFAULT_ADMIN_USERNAME, "password": config.DEFAULT_ADMIN_PASSWORD},
    )
    if resp.status_code != 200:
        print(f"[FAIL] Admin login failed: {resp.status_code}")
        return False
    token = resp.json()["access_token"]

    resp = requests.post(
        f"{API_URL}/api/admin/users",
        json={"username": username, "password": password, "role": role},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 200:
        print(f"[OK] Created '{username}' (role: {role})")
        return True
    print(f"[FAIL] {resp.json().get('detail', resp.status_code)}")
    return False


def create_direct(username: str, password: str, role: str) -> bool:
    from passlib.context import CryptContext
    from backend.core.database import db

    if len(password.encode('utf-8')) > 72:
        print("[FAIL] Password exceeds bcrypt's 72-byte limit")
        return False

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    if db.create_user(username, pwd_context.hash(password), role):
        print(f"[OK] Created '{username}' (role: {role})")
        return True
    print(f"[FAIL] Could not create '{username}' (may already exist)")
    return False


def list_users(direct: bool):
    if direct:
        from backend.core.database import db
        with db.get_connection() as conn:
            users = conn.execute(
                "SELECT username, role, created_at FROM users ORDER BY created_at"
            ).fetchall()
        users = [dict(u) for u in users]
    else:
        import requests
        resp = requests.post(
            f"{API_URL}/api/auth/login",
            data={"username": config.DEFAULT_ADMIN_USERNAME, "password": config.DEFAULT_ADMIN_PASSWORD},
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        resp = requests.get(
            f"{API_URL}/api/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        users = resp.json()

    for u in users:
        print(f"  {u['username']:20} | {u['role']:10} | {u['created_at']}")
    print(f"Total: {len(users)} users")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("username", nargs="?", help="Username to create")
    parser.add_argument("password", nargs="?", help="Password for the new user")
    parser.add_argument("--role", default="user", choices=["user", "admin"])
    parser.add_argument("--direct", action="store_true", help="Write to the SQLite DB directly (API not required)")
    parser.add_argument("--list", action="store_true", help="List existing users and exit")
    args = parser.parse_args()

    if args.list:
        list_users(args.direct)
        return

    if not args.username or not args.password:
        parser.error("username and password are required (or use --list)")

    ok = (create_direct if args.direct else create_via_api)(args.username, args.password, args.role)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
