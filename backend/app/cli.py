"""One-time / maintenance commands (run from the backend folder or inside the api container):

  python -m app.cli create-admin --username admin      # once: first global admin (asks for password)
  python -m app.cli reset-admin-password --username admin
  python -m app.cli seed-demo                           # optional: demo center + starter services

Docker:  docker compose exec -it api python -m app.cli create-admin --username admin
Everything else (centers, center logins, services) is managed inside the app by the global admin.
"""
import argparse, getpass, re, sys

from fastapi import HTTPException
from sqlalchemy import select

from app.main import Base, Center, SessionLocal, User, engine, hash_pw, make_center


def ask_password(given):
    pw = given
    if not pw:
        pw = getpass.getpass("Password (8-72 chars): ")
        if pw != getpass.getpass("Repeat password: "): sys.exit("Passwords do not match")
    if len(pw) < 8 or len(pw.encode()) > 72: sys.exit("Password must be 8-72 characters")
    return pw


def create_admin(a):
    Base.metadata.create_all(engine)
    name = a.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", name): sys.exit("Username: 3-40 characters, a-z 0-9 . _ -")
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.role == "global"))
        if existing and not a.force:
            sys.exit(f"A global admin already exists ('{existing.username}'). Use reset-admin-password, or --force to add another.")
        if db.scalar(select(User).where(User.username == name)) or db.scalar(select(Center).where(Center.slug == name)):
            sys.exit("That username is already in use")
        db.add(User(username=name, pw_hash=hash_pw(ask_password(a.password)), role="global")); db.commit()
    print(f"Global admin '{name}' created. Log in from the 👤 icon on the site root.")


def reset_admin(a):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == a.username.strip().lower(), User.role == "global"))
        if not u: sys.exit("No global admin with that username")
        u.pw_hash = hash_pw(ask_password(a.password)); db.commit()
    print("Password updated.")


def seed_demo(a):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(Center).where(Center.slug == "demo")): sys.exit("Demo center already exists")
        try: c, pw = make_center(db, "Demo CSC Centre", "demo")
        except HTTPException as e: sys.exit(e.detail)
    print(f"Demo center created: /demo   login: demo / {pw}   (the global admin can reset or delete it in the app)")


def main():
    ap = argparse.ArgumentParser(prog="python -m app.cli"); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin"); p.add_argument("--username", required=True); p.add_argument("--password"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=create_admin)
    p = sub.add_parser("reset-admin-password"); p.add_argument("--username", required=True); p.add_argument("--password"); p.set_defaults(fn=reset_admin)
    p = sub.add_parser("seed-demo"); p.set_defaults(fn=seed_demo)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
