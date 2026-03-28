"""Runtime helpers for Codex account activation."""
from __future__ import annotations

from typing import Callable, Optional

from models.codex import account as codex_account


class CodexAccountRuntime:
    """Switch Codex auth state only when a stage needs a different account."""

    def __init__(
        self,
        *,
        get_active_email: Optional[Callable[[], str]] = None,
        set_active_account: Optional[Callable[[str], object]] = None,
    ) -> None:
        self._get_active_email = get_active_email or codex_account.get_active_email
        self._set_active_account = set_active_account or codex_account.set_active_account

    def ensure_active(self, account_email: str | None) -> bool:
        if not account_email:
            return False

        try:
            current_email = self._get_active_email()
        except Exception:
            current_email = ""

        if current_email == account_email:
            return False

        self._set_active_account(account_email)
        return True
