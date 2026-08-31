#!/usr/bin/env python3
"""
CLI untuk manage users.json

Usage:
  python manage_users.py add --username al --password secret123
  python manage_users.py add --username al --password secret123 --role admin
  python manage_users.py remove --username al
  python manage_users.py list
  python manage_users.py reset-password --username al --password newpassword
"""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from passlib.context import CryptContext

load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS_FILE = Path(os.getenv("USERS_FILE", "users.json"))


def _load() -> dict:
    if not USERS_FILE.exists():
        return {"users": []}
    with open(USERS_FILE, "r") as f:
        return json.load(f)


def _save(data: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"   → Disimpan ke: {USERS_FILE.resolve()}")


def cmd_add(username: str, password: str, role: str = "user"):
    data = _load()
    existing = next((u for u in data["users"] if u["username"] == username), None)
    if existing:
        existing["password_hash"] = pwd_context.hash(password)
        existing["role"] = role
        print(f"✅ User '{username}' diupdate (password + role).")
    else:
        data["users"].append({
            "username": username,
            "password_hash": pwd_context.hash(password),
            "role": role
        })
        print(f"✅ User '{username}' ditambahkan dengan role '{role}'.")
    _save(data)


def cmd_remove(username: str):
    data = _load()
    before = len(data["users"])
    data["users"] = [u for u in data["users"] if u["username"] != username]
    if len(data["users"]) == before:
        print(f"❌ User '{username}' tidak ditemukan.")
    else:
        print(f"✅ User '{username}' dihapus.")
        _save(data)


def cmd_list():
    data = _load()
    if not data["users"]:
        print("Belum ada user terdaftar.")
        return
    print(f"{'Username':<20} {'Role':<10}")
    print("-" * 30)
    for u in data["users"]:
        print(f"  {u['username']:<18} {u.get('role', 'user'):<10}")


def cmd_reset_password(username: str, password: str):
    data = _load()
    user = next((u for u in data["users"] if u["username"] == username), None)
    if not user:
        print(f"❌ User '{username}' tidak ditemukan.")
        return
    user["password_hash"] = pwd_context.hash(password)
    print(f"✅ Password '{username}' berhasil direset.")
    _save(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage users Admin Ola")
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="Tambah atau update user")
    p_add.add_argument("--username", required=True)
    p_add.add_argument("--password", required=True)
    p_add.add_argument("--role", default="user", choices=["user", "admin"])

    p_remove = sub.add_parser("remove", help="Hapus user")
    p_remove.add_argument("--username", required=True)

    sub.add_parser("list", help="Tampilkan semua user")

    p_reset = sub.add_parser("reset-password", help="Reset password user")
    p_reset.add_argument("--username", required=True)
    p_reset.add_argument("--password", required=True)

    args = parser.parse_args()

    if args.command == "add":
        cmd_add(args.username, args.password, args.role)
    elif args.command == "remove":
        cmd_remove(args.username)
    elif args.command == "list":
        cmd_list()
    elif args.command == "reset-password":
        cmd_reset_password(args.username, args.password)
    else:
        parser.print_help()
