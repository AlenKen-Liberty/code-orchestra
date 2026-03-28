"""Requirement intake and default stage planning."""
from __future__ import annotations

import re

from harness.models import ClarificationQuestion, IntakeResult, PlannedStage


class IntakeAgent:
    """Heuristic intake agent used before LLM-backed clarification exists."""

    COMPLEXITY_RULES = {
        "trivial": {
            "max_questions": 0,
            "stages": [("code", "coder"), ("github_ops", "github_ops")],
        },
        "simple": {
            "max_questions": 1,
            "stages": [("code", "coder"), ("review", "reviewer"), ("github_ops", "github_ops")],
        },
        "medium": {
            "max_questions": 2,
            "stages": [
                ("plan", "planner"),
                ("code", "coder"),
                ("review", "reviewer"),
                ("test", "tester"),
                ("github_ops", "github_ops"),
            ],
        },
        "complex": {
            "max_questions": 3,
            "stages": [
                ("plan", "planner"),
                ("code", "coder"),
                ("review", "reviewer"),
                ("test", "tester"),
                ("e2e_test", "e2e_tester"),
                ("github_ops", "github_ops"),
            ],
        },
        "epic": {
            "max_questions": 4,
            "stages": [
                ("plan", "planner"),
                ("code", "coder"),
                ("review", "reviewer"),
                ("test", "tester"),
                ("e2e_test", "e2e_tester"),
                ("github_ops", "github_ops"),
                ("summary", "summarizer"),
            ],
        },
    }

    COMPLEXITY_KEYWORDS = {
        "complex": {"architecture", "migrate", "quota", "checkpoint", "permission", "workflow"},
        "epic": {"rewrite", "distributed", "multi-repo", "end-to-end platform"},
    }

    def assess_complexity(self, description: str) -> str:
        normalized = " ".join(description.lower().split())
        word_count = len(normalized.split())
        line_count = len([line for line in description.splitlines() if line.strip()])

        if any(keyword in normalized for keyword in self.COMPLEXITY_KEYWORDS["epic"]) or word_count > 220:
            return "epic"
        if any(keyword in normalized for keyword in self.COMPLEXITY_KEYWORDS["complex"]) or word_count > 120:
            return "complex"
        if line_count >= 4 or word_count > 40:
            return "medium"
        if word_count <= 10:
            return "trivial"
        return "simple"

    def generate_title(self, description: str) -> str:
        first_line = next((line.strip() for line in description.splitlines() if line.strip()), "Untitled task")
        cleaned = re.sub(r"\s+", " ", first_line).strip(" -")
        if len(cleaned) <= 80:
            return cleaned
        clipped = cleaned[:80].rstrip()
        last_space = clipped.rfind(" ")
        if last_space > 40:
            clipped = clipped[:last_space]
        return clipped

    def plan_task(
        self,
        description: str,
        *,
        goal: str | None = None,
        verify_cmd: str | None = None,
        model_overrides: dict[str, tuple[str, str]] | None = None,
    ) -> IntakeResult:
        complexity = self.assess_complexity(description)
        stage_defs = self.COMPLEXITY_RULES[complexity]["stages"]
        overrides = model_overrides or {}
        stages = [
            PlannedStage(
                stage_type=stage_type,
                stage_order=index,
                model_role=model_role,
                assigned_model=overrides.get(stage_type, (None, None))[0],
                assigned_provider=overrides.get(stage_type, (None, None))[1],
                verify_cmd=verify_cmd if stage_type in {"test", "e2e_test"} else None,
                metadata=self._stage_metadata(stage_type),
            )
            for index, (stage_type, model_role) in enumerate(stage_defs, start=1)
        ]
        return IntakeResult(
            title=self.generate_title(description),
            description=description.strip(),
            complexity=complexity,
            stages=stages,
            goal=goal,
            verify_cmd=verify_cmd,
            questions=[],
        )

    GITHUB_OPS_COMMANDS = [
        'git add -A',
        'git commit -m "auto: {summary}"',
        'git push',
    ]

    def _stage_metadata(self, stage_type: str) -> dict:
        if stage_type == "github_ops":
            return {
                "instructions": "Commit all changes and push to remote.",
                "commands": list(self.GITHUB_OPS_COMMANDS),
            }
        return {
            "instructions": f"Execute the `{stage_type}` stage and leave a concise handoff for the next stage."
        }

    def generate_questions(self, description: str, complexity: str | None = None) -> list[ClarificationQuestion]:
        normalized = description.lower()
        resolved_complexity = complexity or self.assess_complexity(description)
        max_questions = self.COMPLEXITY_RULES[resolved_complexity]["max_questions"]
        questions: list[ClarificationQuestion] = []

        if any(keyword in normalized for keyword in {"blacklist", "whitelist", "config", "setting"}):
            questions.append(
                ClarificationQuestion(
                    key="storage",
                    prompt="配置或列表应该存在哪里？",
                    default="config file",
                )
            )

        if "test" not in normalized and "pytest" not in normalized:
            questions.append(
                ClarificationQuestion(
                    key="verify_cmd",
                    prompt="验收命令是什么？没有就留空。",
                    default="pytest",
                )
            )

        if resolved_complexity in {"medium", "complex", "epic"}:
            questions.append(
                ClarificationQuestion(
                    key="goal",
                    prompt="你最关心的验收目标是什么？",
                    default="实现需求并通过相关测试",
                )
            )

        if resolved_complexity in {"simple", "medium", "complex", "epic"}:
            questions.append(
                ClarificationQuestion(
                    key="needs_cli",
                    prompt="是否需要额外的 CLI 或管理入口？(y/N)",
                    default="n",
                )
            )

        return questions[:max_questions]

    def apply_answers(
        self,
        description: str,
        answers: dict[str, str],
        *,
        goal: str | None = None,
        verify_cmd: str | None = None,
    ) -> IntakeResult:
        result = self.plan_task(description, goal=goal, verify_cmd=verify_cmd)
        questions = self.generate_questions(description, result.complexity)

        enriched_lines = [result.description]
        effective_goal = goal or result.goal
        effective_verify = verify_cmd or result.verify_cmd

        storage = answers.get("storage", "").strip()
        if storage:
            enriched_lines.append(f"Storage preference: {storage}.")

        answer_goal = answers.get("goal", "").strip()
        if answer_goal:
            effective_goal = answer_goal

        answer_verify = answers.get("verify_cmd", "").strip()
        if answer_verify:
            effective_verify = answer_verify

        needs_cli = answers.get("needs_cli", "").strip().lower()
        if needs_cli in {"y", "yes", "true", "1"}:
            enriched_lines.append("User requested a CLI or management entrypoint.")

        return IntakeResult(
            title=result.title,
            description="\n".join(enriched_lines).strip(),
            complexity=result.complexity,
            stages=result.stages,
            goal=effective_goal,
            verify_cmd=effective_verify,
            questions=[question.prompt for question in questions],
        )
