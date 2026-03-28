from harness.intake import IntakeAgent


def test_intake_plans_simple_task() -> None:
    agent = IntakeAgent()

    result = agent.plan_task(
        "Add a blacklist setting to the scheduler, wire config loading, and cover it with tests."
    )

    assert result.title == "Add a blacklist setting to the scheduler, wire config loading, and cover it"
    assert result.complexity == "simple"
    assert [stage.stage_type for stage in result.stages] == ["code", "review", "github_ops"]
    assert [stage.model_role for stage in result.stages] == ["coder", "reviewer", "github_ops"]


def test_intake_marks_complex_work() -> None:
    agent = IntakeAgent()

    result = agent.plan_task(
        "Build a quota-aware scheduler with checkpoint recovery, permission voting, "
        "workflow persistence, and a resumable execution loop."
    )

    assert result.complexity == "complex"
    assert [stage.stage_type for stage in result.stages] == [
        "plan",
        "code",
        "review",
        "test",
        "e2e_test",
        "github_ops",
    ]


def test_intake_generates_questions_and_applies_answers() -> None:
    agent = IntakeAgent()
    description = "Add a blacklist setting for subreddit filtering."

    questions = agent.generate_questions(description, "simple")
    result = agent.apply_answers(
        description,
        {
            "storage": "config/blacklist.yaml",
            "verify_cmd": "pytest tests/test_blacklist.py",
            "needs_cli": "y",
        },
    )

    assert [question.key for question in questions] == ["storage"]
    assert "Storage preference: config/blacklist.yaml." in result.description
    assert "User requested a CLI or management entrypoint." in result.description
    assert result.verify_cmd == "pytest tests/test_blacklist.py"
