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


class AuthDataError(RuntimeError):
    """Raised when existing authentication data cannot be read safely."""


def load_auth_data():
    _ensure_private_dir()
    try:
        raw_data = AUTH_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        # A missing file is expected on legacy installs and means UI Password
        # is disabled until the user explicitly enables it.
        return {}
    except OSError as exc:
        # Do not treat permission or I/O failures as an unconfigured account:
        # that could silently disable authentication on a protected install.
        raise AuthDataError(
            "Authentication data exists but cannot be read. Check its file "
            "permissions or restore a valid auth.json; access is blocked for safety."
        ) from exc

    try:
        data = json.loads(raw_data)
    except (ValueError, TypeError) as exc:
        raise AuthDataError(
            "Authentication data is malformed. Restore a valid auth.json; "
            "access is blocked for safety."
        ) from exc

    if not isinstance(data, dict):
        raise AuthDataError(
            "Authentication data has an invalid format. Restore a valid auth.json; "
            "access is blocked for safety."
        )
    return data


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
    # Preserve non-credential preferences (including UI Password state) when
    # creating an account after initial setup or from Account & Security.
    data = load_auth_data()
    data.update({
        "username": username,
        "password": hash_password(password),
        "session_version": secrets.token_hex(16),
        "created_at": int(time.time()),
    })
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
