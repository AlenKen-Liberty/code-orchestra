import pytest

from harness.model_registry import AliasCollisionError, ModelRegistry


@pytest.fixture()
def registry(tmp_path):
    catalog = tmp_path / "models.yaml"
    catalog.write_text(
        """\
models:
  claude-opus-4-6:
    provider: claude
    chat2api_id: copilot-claude-opus
    cli_model_id: opus
    aliases: [opus, claude-opus]
  gpt-5.4-codex:
    provider: codex
    chat2api_id: codex
    aliases: [codex, gpt-5.4]
  gemini-3.1-pro:
    provider: google
    chat2api_id: gemini-pro
    cli_model_id: gemini-3.1-pro-preview
    aliases: [gemini-pro, gemini]
  gpt-4o:
    provider: github
    chat2api_id: copilot-gpt4o
    aliases: [gpt4o]
roles:
  coder:
    - gpt-5.4-codex
    - gemini-3.1-pro
""",
        encoding="utf-8",
    )
    return ModelRegistry(catalog)


def test_resolve_canonical_unchanged(registry):
    assert registry.resolve("claude-opus-4-6") == "claude-opus-4-6"


def test_resolve_alias(registry):
    assert registry.resolve("opus") == "claude-opus-4-6"
    assert registry.resolve("codex") == "gpt-5.4-codex"
    assert registry.resolve("gemini") == "gemini-3.1-pro"
    assert registry.resolve("gpt4o") == "gpt-4o"


def test_resolve_unknown_returns_input(registry):
    assert registry.resolve("unknown-model") == "unknown-model"


def test_chat2api_id(registry):
    assert registry.chat2api_id("claude-opus-4-6") == "copilot-claude-opus"
    assert registry.chat2api_id("opus") == "copilot-claude-opus"
    assert registry.chat2api_id("gpt-5.4-codex") == "codex"


def test_cli_model_id(registry):
    assert registry.cli_model_id("claude-opus-4-6") == "opus"
    assert registry.cli_model_id("gemini-3.1-pro") == "gemini-3.1-pro-preview"
    # Falls back to canonical when cli_model_id not set
    assert registry.cli_model_id("gpt-5.4-codex") == "gpt-5.4-codex"


def test_provider(registry):
    assert registry.provider("claude-opus-4-6") == "claude"
    assert registry.provider("codex") == "codex"
    assert registry.provider("gpt4o") == "github"


def test_models_for_role(registry):
    assert registry.models_for_role("coder") == ["gpt-5.4-codex", "gemini-3.1-pro"]


def test_models_for_unknown_role_returns_all(registry):
    result = registry.models_for_role("nonexistent")
    assert set(result) == {"claude-opus-4-6", "gpt-5.4-codex", "gemini-3.1-pro", "gpt-4o"}


def test_available_canonical_names(registry):
    live = {"codex", "gemini-pro", "copilot-gpt4o"}
    available = registry.available_canonical_names(live)
    assert "gpt-5.4-codex" in available
    assert "gemini-3.1-pro" in available
    assert "gpt-4o" in available
    assert "claude-opus-4-6" not in available


def test_alias_collision_raises(tmp_path):
    catalog = tmp_path / "bad.yaml"
    catalog.write_text(
        """\
models:
  model-a:
    provider: test
    aliases: [shared-alias]
  model-b:
    provider: test
    aliases: [shared-alias]
""",
        encoding="utf-8",
    )
    with pytest.raises(AliasCollisionError, match="shared-alias"):
        ModelRegistry(catalog)
