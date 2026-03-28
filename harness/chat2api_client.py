"""Minimal chat2api client."""
from __future__ import annotations

import json
from typing import Any, Optional
from urllib import request

from config import settings


class Chat2APIClient:
    """Simple stdlib HTTP client for the local chat2api gateway.

    Model name resolution is handled externally by ModelRegistry.
    This client accepts whatever model string it receives and sends
    it directly to the chat2api gateway.
    """

    def __init__(
        self,
        base_url: str = settings.CHAT2API_BASE_URL,
        timeout: float = settings.CHAT2API_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def list_models(self) -> list[str]:
        payload = self._get_json("/v1/models")
        return [item["id"] for item in payload.get("data", []) if "id" in item]

    def chat(
        self,
        *,
        model: str,
        prompt: str,
        system: Optional[str] = None,
    ) -> str:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = self._post_json(
            "/v1/chat/completions",
            {"model": model, "messages": messages},
        )
        return payload["choices"][0]["message"]["content"]

    def acquire_account(self, provider: str, model: str) -> dict[str, Any]:
        """Request the best available account for a given provider and model."""
        return self._post_json(
            "/v1/admin/acquire-account",
            {"provider": provider, "model": model},
        )

    def report_exhaustion(self, provider: str, email: str, model_tier: Optional[str] = None) -> dict[str, Any]:
        """Report that an account has hit a quota limit."""
        return self._post_json(
            "/v1/admin/report-exhaustion",
            {"provider": provider, "email": email, "model_tier": model_tier},
        )

    def _get_json(self, path: str) -> dict[str, Any]:
        req = request.Request(f"{self.base_url}{path}", method="GET")
        with request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))
