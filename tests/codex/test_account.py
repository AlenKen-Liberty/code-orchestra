import json
from pathlib import Path
from unittest import mock

import pytest
from models.codex.account import (
    CodexAccount,
    add_account,
    get_active_account,
    get_active_email,
    get_account_index,
    import_current_account,
    list_accounts,
    load_account,
    load_all_accounts,
    refresh_account_tokens,
    remove_account,
    set_active_account,
    _is_codex_running,
    ACCOUNTS_DIR,
    ACCOUNTS_INDEX_PATH,
)


@pytest.fixture
def mock_fs(monkeypatch, tmp_path):
    accounts_dir = tmp_path / "accounts"
    accounts_index = accounts_dir / "accounts.json"
    codex_auth = tmp_path / "auth.json"

    monkeypatch.setattr("models.codex.account.ACCOUNTS_DIR", accounts_dir)
    monkeypatch.setattr("models.codex.account.ACCOUNTS_INDEX_PATH", accounts_index)
    monkeypatch.setattr("models.codex.account.CODEX_AUTH_PATH", codex_auth)
    monkeypatch.setattr("models.codex.auth.CODEX_AUTH_PATH", codex_auth)
    monkeypatch.setattr("models.codex.auth.CODEX_DIR", tmp_path)

    return {"dir": accounts_dir, "index": accounts_index, "auth": codex_auth}


def test_add_and_list_accounts(mock_fs):
    tokens = {"access_token": "a1", "refresh_token": "r1", "id_token": "i1"}

    acc = add_account("test@example.com", tokens, account_id="acc123")
    assert acc.email == "test@example.com"
    assert acc.account_id == "acc123"

    accounts = list_accounts()
    assert accounts == ["test@example.com"]

    acc2 = add_account("test2@example.com", tokens, account_id="acc456", set_active=True)
    assert acc2.email == "test2@example.com"
    assert get_active_email() == "test2@example.com"
    assert "test2@example.com" in list_accounts()


def test_load_all_accounts(mock_fs):
    tokens = {"access_token": "a", "refresh_token": "r"}
    add_account("a@1", tokens)
    add_account("b@1", tokens)

    loaded = load_all_accounts()
    assert len(loaded) == 2
    emails = [a.email for a in loaded]
    assert "a@1" in emails
    assert "b@1" in emails


def test_add_account_missing_tokens():
    with pytest.raises(RuntimeError, match="Missing access_token or refresh_token"):
        add_account("test@test.com", {"id_token": "only"})


def test_remove_account(mock_fs):
    tokens = {"access_token": "a", "refresh_token": "r"}
    add_account("test@test.com", tokens, set_active=True)
    assert get_active_email() == "test@test.com"

    remove_account("test@test.com")
    assert list_accounts() == []
    assert get_active_email() == ""
    with pytest.raises(FileNotFoundError):
        load_account("test@test.com")


def test_get_active_account_none(mock_fs):
    with pytest.raises(RuntimeError, match="No active account set"):
        get_active_account()


@mock.patch("models.codex.account.auth.ensure_fresh_tokens")
@mock.patch("models.codex.account.auth.extract_account_info")
def test_refresh_account_tokens(mock_extract, mock_ensure_fresh, mock_fs):
    mock_ensure_fresh.return_value = {
        "access_token": "new_a",
        "refresh_token": "new_r",
        "id_token": "new_i",
        "account_id": "new_acc",
    }
    mock_info = mock.MagicMock()
    mock_info.account_id = "new_acc"
    mock_info.plan_type = "plus"
    mock_extract.return_value = mock_info

    tokens = {"access_token": "a", "refresh_token": "r"}
    acc = add_account("test@test", tokens)

    refreshed = refresh_account_tokens(acc)
    assert refreshed.access_token == "new_a"
    assert refreshed.refresh_token == "new_r"
    assert refreshed.account_id == "new_acc"
    assert refreshed.plan_type == "plus"


@mock.patch("models.codex.auth.read_codex_auth")
def test_import_current_account(mock_read_auth, mock_fs):
    mock_read_auth.return_value = {
        "tokens": {
            "access_token": "curr_a",
            "refresh_token": "curr_r",
            "id_token": "curr_i",
            "account_id": "curr_acc",
        }
    }

    with mock.patch("models.codex.account.auth.extract_account_info") as mock_extract:
        mock_info = mock.MagicMock()
        mock_info.email = "current@example.com"
        mock_info.account_id = "curr_acc"
        mock_info.plan_type = "free"
        mock_extract.return_value = mock_info

        acc = import_current_account()
        assert acc.email == "current@example.com"
        assert get_active_email() == "current@example.com"


@mock.patch("subprocess.run")
def test_is_codex_running(mock_run):
    mock_result = mock.MagicMock()
    mock_result.returncode = 0
    mock_run.return_value = mock_result
    assert _is_codex_running() is True

    mock_result.returncode = 1
    assert _is_codex_running() is False

    mock_run.side_effect = FileNotFoundError()
    assert _is_codex_running() is False


@mock.patch("models.codex.account._is_codex_running", return_value=False)
@mock.patch("models.codex.account.refresh_account_tokens")
def test_set_active_account(mock_refresh, mock_is_running, mock_fs):
    # Setup two accounts
    tokens1 = {"access_token": "a1", "refresh_token": "r1"}
    tokens2 = {"access_token": "a2", "refresh_token": "r2"}
    
    add_account("old@a", tokens1, set_active=True)
    add_account("new@a", tokens2)

    # Set mock refresh to just return the account as-is (already tested refresh logic)
    mock_refresh.side_effect = lambda a, **kw: a

    # Fake current auth.json
    from models.codex.auth import write_codex_auth
    write_codex_auth({"access_token": "a1", "refresh_token": "r1", "account_id": "old-acc"})

    with mock.patch("models.codex.account.auth.extract_account_info") as mock_extract:
        mock_info = mock.MagicMock()
        mock_info.email = "old@a"
        mock_info.account_id = "old-acc"
        mock_info.plan_type = "free"
        mock_extract.return_value = mock_info

        # Perform switch
        target = set_active_account("new@a")
        
        assert target.email == "new@a"
        assert get_active_email() == "new@a"
        
        # Verify auth.json was rewritten properly
        from models.codex.auth import read_codex_auth
        new_auth = read_codex_auth()
        assert new_auth["tokens"]["access_token"] == "a2"
