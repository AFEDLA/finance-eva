import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "changeme-please-set-in-env")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

USERS_FILE = Path(os.getenv("USERS_FILE", "users.json"))


def _load_users() -> list[dict]:
    if not USERS_FILE.exists():
        return []
    with open(USERS_FILE, "r") as f:
        return json.load(f).get("users", [])


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode JWT — raise JWTError jika invalid/expired."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(req: LoginRequest):
    users = _load_users()
    user = next((u for u in users if u["username"] == req.username), None)
    if not user or not _verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Username atau password salah")
    token = _create_token(user["username"], user.get("role", "user"))
    return {
        "token": token,
        "username": user["username"],
        "role": user.get("role", "user")
    }
