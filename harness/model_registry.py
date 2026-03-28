"""Unified model name resolution.

Every model has one canonical name (the key in role_models.yaml).
Each model may declare aliases — alternative names used by chat2api,
CLI tools, or shorthand references.

ModelRegistry enforces a strict invariant: **no alias may point to
more than one canonical name**.  This is validated at load time so
that name collisions are caught early rather than at runtime.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from config import settings


class AliasCollisionError(ValueError):
    """Raised when an alias resolves to more than one canonical model."""


class ModelRegistry:
    """Single source of truth for model name resolution."""

    def __init__(self, catalog_path: str | Path = settings.HARNESS_ROLE_MODELS_PATH) -> None:
        self._catalog = self._load(catalog_path)
        self._models: dict[str, dict[str, Any]] = self._catalog.get("models", {})
        # canonical name → set of aliases (including the canonical name itself)
        self._alias_to_canonical: dict[str, str] = {}
        self._build_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> str:
        """Resolve any name (canonical or alias) to its canonical name.

        Returns the input unchanged if it is not recognised — this keeps
        the system open to ad-hoc model names that haven't been catalogued.
        """
        return self._alias_to_canonical.get(name, name)

    def chat2api_id(self, name: str) -> str:
        """Return the chat2api model ID for *name* (canonical or alias)."""
        canonical = self.resolve(name)
        info = self._models.get(canonical, {})
        return info.get("chat2api_id", canonical)

    def cli_model_id(self, name: str) -> str:
        """Return the CLI model ID for *name* (canonical or alias).

        Falls back to the canonical name if no cli_model_id is configured.
        """
        canonical = self.resolve(name)
        info = self._models.get(canonical, {})
        return info.get("cli_model_id", canonical)

    def provider(self, name: str) -> str:
        """Return the provider string for *name*."""
        canonical = self.resolve(name)
        return self._models.get(canonical, {}).get("provider", "")

    def get_info(self, name: str) -> dict[str, Any]:
        """Return the full catalog entry for *name*."""
        canonical = self.resolve(name)
        return dict(self._models.get(canonical, {}))

    def canonical_names(self) -> list[str]:
        """Return all canonical model names."""
        return list(self._models.keys())

    def available_canonical_names(self, live_ids: set[str]) -> list[str]:
        """Return canonical names whose chat2api_id appears in *live_ids*."""
        return [
            name for name in self._models
            if self.chat2api_id(name) in live_ids
        ]

    def roles(self) -> dict[str, list[str]]:
        """Return role → [canonical model names] mapping."""
        return dict(self._catalog.get("roles", {}))

    def models_for_role(self, role: str) -> list[str]:
        """Return ordered candidate list for *role*."""
        roles = self._catalog.get("roles", {})
        configured = roles.get(role)
        if configured:
            return list(configured)
        return self.canonical_names()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _load(path: str | Path) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def _build_index(self) -> None:
        """Build alias → canonical mapping with collision detection.

        Only the canonical name and explicit aliases are registered.
        chat2api_id and cli_model_id are *not* registered as aliases
        because multiple models may share a gateway ID (e.g. sonnet
        and haiku both use ``copilot-claude``).  Outbound resolution
        uses the dedicated ``chat2api_id()`` / ``cli_model_id()``
        methods which look up the value directly.
        """
        for canonical, info in self._models.items():
            self._register(canonical, canonical)
            for alias in info.get("aliases", []):
                if alias and alias != canonical:
                    self._register(alias, canonical)

    def _register(self, alias: str, canonical: str) -> None:
        existing = self._alias_to_canonical.get(alias)
        if existing is not None and existing != canonical:
            raise AliasCollisionError(
                f"Alias {alias!r} maps to both {existing!r} and {canonical!r}. "
                f"Each alias must resolve to exactly one canonical model."
            )
        self._alias_to_canonical[alias] = canonical
