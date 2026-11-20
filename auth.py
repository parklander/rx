"""Users, password hashing and sessions (cookie)."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request

import db

COOKIE = "rx_session"
SESSION_DAYS = 14
ROLES = ["viewer", "planner", "burn_boss", "admin"]


def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + salt.hex() + "$" + h.hex()


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        test = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(test.hex(), h)
    except Exception:
        return False


def create_user(username, display_name, role, password):
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    with db.tx() as c:
        c.execute("""insert into meta.app_user (username, display_name, role, pw_hash) values (%s,%s,%s,%s)
                     on conflict (username) do update set display_name = excluded.display_name,
                       role = excluded.role, pw_hash = excluded.pw_hash, active = true""",
                  (username, display_name, role, hash_pw(password)))


def login(username, password):
    u = db.one("select * from meta.app_user where username = %s and active", (username,))
    if not u or not check_pw(password, u["pw_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    with db.tx() as c:
        c.execute("delete from meta.session where expires_at < now()")
        c.execute("insert into meta.session (token, user_id, expires_at) values (%s,%s,%s)",
                  (token, u["id"], datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)))
    return token


def logout(token):
    with db.tx() as c:
        c.execute("delete from meta.session where token = %s", (token,))


def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "login required")
    u = db.one("""select u.id, u.username, u.display_name, u.role from meta.session s
                  join meta.app_user u on u.id = s.user_id
                  where s.token = %s and s.expires_at > now() and u.active""", (token,))
    if not u:
        raise HTTPException(401, "login required")
    return u


def require(role):
    """Dependency: the user must hold `role` or higher."""
    need = ROLES.index(role)

    def dep(user=Depends(current_user)):
        if ROLES.index(user["role"]) < need:
            raise HTTPException(403, f"needs the {role} role")
        return user
    return dep
