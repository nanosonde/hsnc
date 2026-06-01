"""Password hashing utilities (Werkzeug PBKDF2).

Kept in infrastructure so the application layer depends only on a callable
signature (``verify_password``) rather than a concrete library.
"""

from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)
