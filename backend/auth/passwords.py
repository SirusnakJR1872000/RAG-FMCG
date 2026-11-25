"""Password hashing and policy (PROJECT_SPEC §13.2; SEC-03, SEC-05).

Argon2id via argon2-cffi's defaults; the parameters live inside each hash string, so they can
be raised later and old hashes are upgraded at the next login (`needs_rehash`).

Policy: at least 12 characters, not a common password, not the username, not one of the last
5 passwords. Expiry (90 days) is enforced at login (auth/service.py).
"""

from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # Argon2id; tests swap in a cheap one via configure_hasher()
MAX_LENGTH = 128  # a limit, so a huge "password" cannot be used to burn CPU
COMMON_FILE = Path(__file__).with_name("common_passwords.txt")

# Rule codes: the UI shows each one as a ✓/✗ line (design brief §5.2).
TOO_SHORT, TOO_LONG, COMMON, SAME_AS_USERNAME, REUSED = (
    "TOO_SHORT", "TOO_LONG", "COMMON", "SAME_AS_USERNAME", "REUSED")


def configure_hasher(hasher: PasswordHasher) -> None:
    global _hasher
    _hasher = hasher
    _dummy_hash.cache_clear()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False  # wrong password, or a placeholder like '!' that is not a hash at all


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("never-a-real-password")


def dummy_verify(password: str) -> None:
    """Spend the time of a real check, so an unknown username cannot be told from a wrong
    password by how long the answer takes (§13.2)."""
    verify_password(_dummy_hash(), password)


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    lines = COMMON_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#"))


def is_common(password: str) -> bool:
    """On the list, or on the list with digits/symbols added at the end ("Summer2024!")."""
    lowered = password.strip().lower()
    stripped = lowered.rstrip("0123456789!@#$%^&*._- ")
    common = _common_passwords()
    return lowered in common or (len(stripped) >= 4 and stripped in common)


def check_policy(password: str, *, username: str, min_length: int,
                 recent_hashes: list[str]) -> list[str]:
    """Codes of every rule the password breaks (empty list = acceptable)."""
    broken = []
    if len(password) < min_length:
        broken.append(TOO_SHORT)
    if len(password) > MAX_LENGTH:
        broken.append(TOO_LONG)
    if is_common(password):
        broken.append(COMMON)
    if password.lower() == username.lower():
        broken.append(SAME_AS_USERNAME)
    if any(verify_password(old, password) for old in recent_hashes):
        broken.append(REUSED)
    return broken
