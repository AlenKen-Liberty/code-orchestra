"""Runtime helpers for Gemini account activation."""
from __future__ import annotations

from typing import Callable, Optional

from models.google import account as gemini_account


class GeminiAccountRuntime:
    """Switch Gemini auth state only when a stage needs a different account."""

    def __init__(
        self,
        *,
        get_active_email: Optional[Callable[[], Optional[str]]] = None,
        set_active_account: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._get_active_email = get_active_email or gemini_account.get_active_email
        self._set_active_account = set_active_account or gemini_account.set_active_account

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
