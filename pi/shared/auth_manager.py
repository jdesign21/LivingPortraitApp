"""Persistent local administrator authentication for LivingPortraitApp."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

HOME = Path.home()
AUTH_DIR = HOME / ".livingportrait_auth"
AUTH_FILE = AUTH_DIR / "auth.json"
SECRET_FILE = AUTH_DIR / "secret_key"
PBKDF2_ITERATIONS = 600_000


def _ensure_private_dir():
    AUTH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        AUTH_DIR.chmod(0o700)
    except OSError:
        pass


def get_or_create_secret_key():
    _ensure_private_dir()
    try:
        value = SECRET_FILE.read_text(encoding="utf-8").strip()
        if len(value) >= 64:
            return value
    except OSError:
        pass

    value = secrets.token_hex(48)
    temp = SECRET_FILE.with_suffix(".tmp")
    temp.write_text(value + "\n", encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    os.replace(temp, SECRET_FILE)
    try:
        SECRET_FILE.chmod(0o600)
    except OSError:
        pass
    return value


def load_auth_data():
    _ensure_private_dir()
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_auth_data(data):
    _ensure_private_dir()
    temp = AUTH_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    os.replace(temp, AUTH_FILE)
    try:
        AUTH_FILE.chmod(0o600)
    except OSError:
        pass


def validate_username(username):
    username = (username or "").strip()
    if not 3 <= len(username) <= 32:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]+", username):
        return None
    return username


def validate_password(password):
    if not isinstance(password, str) or len(password) < 12:
        return False
    if len(password) > 1024 or password.strip() != password:
        return False
    return True


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return {
        "algorithm": "pbkdf2_sha256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": salt.hex(),
        "hash": digest.hex(),
    }


def verify_password(password, stored):
    if not isinstance(stored, dict):
        return False
    try:
        if stored.get("algorithm") != "pbkdf2_sha256":
            return False
        iterations = int(stored.get("iterations", 0))
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = bytes.fromhex(stored["salt"])
        expected = bytes.fromhex(stored["hash"])
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def create_admin(username, password):
    data = {
        "username": username,
        "password": hash_password(password),
        "session_version": secrets.token_hex(16),
        "created_at": int(time.time()),
    }
    save_auth_data(data)
    return data


def update_admin(username, password=None):
    data = load_auth_data()
    data["username"] = username
    if password is not None:
        data["password"] = hash_password(password)
    data["session_version"] = secrets.token_hex(16)
    data["updated_at"] = int(time.time())
    save_auth_data(data)
    return data


def reset_admin_password(password):
    data = load_auth_data()
    if not data.get("username") or not data.get("password"):
        raise RuntimeError("No administrator account exists yet.")
    data["password"] = hash_password(password)
    data["session_version"] = secrets.token_hex(16)
    data["updated_at"] = int(time.time())
    save_auth_data(data)
