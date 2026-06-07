"""Use case: authenticate a controller user against stored credentials."""

from __future__ import annotations

from collections.abc import Callable

from ...domain.interfaces import ConfigRepository
from ..dtos import AuthenticatedUser

PasswordVerifier = Callable[[str, str], bool]


class AuthenticateUser:
    """Verify a username/password pair and return a presentation-safe view."""

    def __init__(self, config: ConfigRepository, verify_password: PasswordVerifier) -> None:
        self._config = config
        self._verify = verify_password

    def execute(self, username: str, password: str) -> AuthenticatedUser | None:
        user = self._config.get_user(username)
        if user is None:
            return None
        if not self._verify(password, user.password_hash):
            return None
        return AuthenticatedUser(
            username=user.username,
            display_name=user.display_name or user.username,
            role=user.role.value,
        )
