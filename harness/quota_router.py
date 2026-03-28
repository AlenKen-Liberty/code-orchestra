"""Quota-aware model routing."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from config import settings
from harness.chat2api_client import Chat2APIClient
from harness.model_registry import ModelRegistry
from harness.models import ModelChoice, StageRecord, TaskRecord
from models.quota_manager import QuotaManager, QuotaSnapshot


class AllQuotaExhaustedError(RuntimeError):
    """Raised when no configured candidate model is currently usable."""


@dataclass(frozen=True)
class EligibleCandidate:
    model: str
    provider: str
    role_index: int
    snapshot: Optional[QuotaSnapshot] = None


class QuotaRouter:
    """Select a model using role preferences, availability, and quota heuristics."""

    def __init__(
        self,
        *,
        registry: Optional[ModelRegistry] = None,
        quota_manager: Optional[QuotaManager] = None,
        chat_client: Optional[Chat2APIClient] = None,
        min_remaining_pct: int = settings.HARNESS_MIN_QUOTA_PCT,
        enable_llm_selector: bool = True,
    ) -> None:
        self.registry = registry or ModelRegistry()
        self.quota_manager = quota_manager or QuotaManager()
        self.chat_client = chat_client or Chat2APIClient()
        self.min_remaining_pct = min_remaining_pct
        self.enable_llm_selector = enable_llm_selector

    def models_for_role(self, role: str) -> list[str]:
        return self.registry.models_for_role(role)

    def get_model_info(self, model: str) -> dict[str, Any]:
        return self.registry.get_info(model)

    def list_available_models(self) -> list[str]:
        """Return canonical model names whose chat2api_id is currently live."""
        try:
            live_ids = set(self.chat_client.list_models())
        except Exception:
            return self.registry.canonical_names()
        if not live_ids:
            return self.registry.canonical_names()
        return self.registry.available_canonical_names(live_ids)

    def can_run_stage(
        self,
        task: TaskRecord,
        stage: StageRecord,
        *,
        quota_snapshot: Optional[list[QuotaSnapshot]] = None,
        available_models: Optional[list[str]] = None,
    ) -> bool:
        try:
            self.select_model(task, stage, quota_snapshot=quota_snapshot, available_models=available_models)
        except AllQuotaExhaustedError:
            return False
        return True

    def select_model(
        self,
        task: TaskRecord,
        stage: StageRecord,
        *,
        quota_snapshot: Optional[list[QuotaSnapshot]] = None,
        available_models: Optional[list[str]] = None,
    ) -> ModelChoice:
        quotas = quota_snapshot if quota_snapshot is not None else self.quota_manager.fetch_all_quotas()
        available = set(available_models or self.list_available_models())
        eligible = self._eligible_candidates(self.models_for_role(stage.model_role), quotas, available)

        if not eligible:
            raise AllQuotaExhaustedError(
                f"No eligible model for role={stage.model_role} with min_remaining={self.min_remaining_pct}%"
            )

        if self.enable_llm_selector:
            llm_choice = self._select_with_llm(task, stage, quotas, eligible)
            if llm_choice is not None:
                return llm_choice

        return self._fallback_select(task, stage, eligible)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _eligible_candidates(
        self,
        candidates: list[str],
        quotas: list[QuotaSnapshot],
        available: set[str],
    ) -> list[EligibleCandidate]:
        eligible: list[EligibleCandidate] = []
        for role_index, model in enumerate(candidates):
            if model not in available:
                continue
            provider = self.registry.provider(model)
            if not provider:
                continue

            provider_snapshots = [
                snapshot
                for snapshot in quotas
                if snapshot.provider.value == provider and snapshot.remaining_percent >= self.min_remaining_pct
            ]
            if provider_snapshots:
                for snapshot in provider_snapshots:
                    eligible.append(
                        EligibleCandidate(model=model, provider=provider, role_index=role_index, snapshot=snapshot)
                    )
            elif provider == "github":
                eligible.append(
                    EligibleCandidate(model=model, provider=provider, role_index=role_index, snapshot=None)
                )
        return eligible

    def _select_with_llm(
        self,
        task: TaskRecord,
        stage: StageRecord,
        quotas: list[QuotaSnapshot],
        eligible: list[EligibleCandidate],
    ) -> ModelChoice | None:
        selector_model = self._pick_selector_model()
        if selector_model is None:
            return None

        prompt = self._build_selection_prompt(task, stage, quotas, eligible)
        try:
            raw = self.chat_client.chat(
                model=selector_model,
                prompt=prompt,
                system=(
                    "You are code-orchestra's model router. "
                    "Return compact JSON with fields model, provider, account, reason."
                ),
            )
            parsed = json.loads(raw)
        except Exception:
            return None

        chosen_model = parsed.get("model")
        if not isinstance(chosen_model, str):
            return None

        # LLM might respond with any alias — resolve to canonical
        chosen_model = self.registry.resolve(chosen_model)

        selected = self._match_llm_choice(chosen_model, parsed.get("account"), eligible)
        if selected is None:
            return None

        provider = selected.provider
        snapshot = selected.snapshot
        if snapshot is not None:
            requested_account = parsed.get("account")
            if isinstance(requested_account, str) and requested_account and requested_account != snapshot.email:
                alternative = next(
                    (
                        quota
                        for quota in quotas
                        if quota.provider.value == provider
                        and quota.email == requested_account
                        and quota.remaining_percent >= self.min_remaining_pct
                    ),
                    None,
                )
                if alternative is not None:
                    snapshot = alternative

        return ModelChoice(
            model=chosen_model,
            provider=provider,
            account_email=snapshot.email if snapshot is not None else None,
            reason=str(parsed.get("reason") or "llm_selector"),
        )

    def _fallback_select(
        self,
        task: TaskRecord,
        stage: StageRecord,
        eligible: list[EligibleCandidate],
    ) -> ModelChoice:
        best_choice: ModelChoice | None = None
        best_score: float | None = None

        for candidate in eligible:
            role_bonus = max(0, 40 - candidate.role_index * 10)
            model = candidate.model
            provider = candidate.provider
            snapshot = candidate.snapshot
            if snapshot is not None:
                total_score = role_bonus + self._score_snapshot(snapshot)
                choice = ModelChoice(
                    model=model,
                    provider=provider,
                    account_email=snapshot.email,
                    reason=(
                        f"fallback: role={stage.model_role}, complexity={task.complexity}, "
                        f"remaining={snapshot.remaining_percent}%, "
                        f"reset_in={snapshot.time_until_reset_hours:.1f}h"
                    ),
                )
            else:
                total_score = role_bonus + self._score_provider_without_snapshot(provider)
                choice = ModelChoice(
                    model=model,
                    provider=provider,
                    account_email=None,
                    reason=f"fallback: role={stage.model_role}, complexity={task.complexity}, provider={provider}",
                )

            if best_score is None or total_score > best_score:
                best_score = total_score
                best_choice = choice

        if best_choice is None:
            raise AllQuotaExhaustedError(
                f"No eligible model for role={stage.model_role} with min_remaining={self.min_remaining_pct}%"
            )
        return best_choice

    def _pick_selector_model(self) -> str | None:
        """Pick cheapest available model for LLM selection. Returns chat2api_id."""
        preferred = ("gpt-4o", "claude-haiku-4-5", "gemini-3.1-pro", "gpt-5.4-codex")
        available = set(self.list_available_models())
        for model in preferred:
            if model in available:
                return self.registry.chat2api_id(model)
        return None

    def _build_selection_prompt(
        self,
        task: TaskRecord,
        stage: StageRecord,
        quotas: list[QuotaSnapshot],
        eligible: list[EligibleCandidate],
    ) -> str:
        lines = [
            f"Task: {task.title}",
            f"Description: {task.description}",
            f"Complexity: {task.complexity}",
            f"Stage: {stage.stage_type} ({stage.model_role})",
            "",
            "Eligible models:",
        ]
        for candidate in eligible:
            if candidate.snapshot is None:
                lines.append(f"- {candidate.model} | provider={candidate.provider} | remaining=n/a")
            else:
                lines.append(
                    f"- {candidate.model} | provider={candidate.provider} | account={candidate.snapshot.email} | "
                    f"remaining={candidate.snapshot.remaining_percent}% | reset_in={candidate.snapshot.time_until_reset_hours:.1f}h"
                )
        lines.extend(
            [
                "",
                "Prefer use-it-or-lose-it quota, but keep role fit.",
                'Respond as JSON: {"model": "...", "provider": "...", "account": "...", "reason": "..."}',
            ]
        )
        return "\n".join(lines)

    def _match_llm_choice(
        self,
        model: str,
        account: object,
        eligible: list[EligibleCandidate],
    ) -> EligibleCandidate | None:
        model_candidates = [c for c in eligible if c.model == model]
        if not model_candidates:
            return None
        requested_account = account if isinstance(account, str) else None
        if requested_account:
            exact = next(
                (c for c in model_candidates if c.snapshot is not None and c.snapshot.email == requested_account),
                None,
            )
            if exact is not None:
                return exact
        return max(
            model_candidates,
            key=lambda c: self._score_snapshot(c.snapshot) if c.snapshot is not None else -1.0,
        )

    def _score_snapshot(self, snapshot: QuotaSnapshot) -> float:
        scorer = getattr(self.quota_manager, "_score_account", None)
        if callable(scorer):
            try:
                return float(scorer(snapshot, False))
            except TypeError:
                return float(scorer(snapshot))
        waste_bonus = 0.0
        if snapshot.time_until_reset_hours <= 6:
            waste_bonus = snapshot.remaining_percent * (6 - max(snapshot.time_until_reset_hours, 0)) / 6
        safety_bonus = 15.0 if snapshot.remaining_percent >= 40 else 0.0
        return snapshot.remaining_percent + waste_bonus + safety_bonus

    def _score_provider_without_snapshot(self, provider: str) -> float:
        if provider == "github":
            return 85.0
        if provider == "claude":
            return 70.0
        return 50.0
