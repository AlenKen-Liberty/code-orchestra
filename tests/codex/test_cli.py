import argparse
import time
from unittest import mock

import pytest
from models.codex.account import CodexAccount
from models.codex.cli import (
    _format_bar,
    _format_reset,
    cmd_import,
    cmd_list,
    cmd_login,
    cmd_remove,
    cmd_rotate,
    cmd_status,
    cmd_switch,
)
from models.codex.quota import CodexQuota


def test_format_bar():
    assert _format_bar(0, width=10) == "[..........]"
    assert _format_bar(50, width=10) == "[#####.....]"
    assert _format_bar(100, width=10) == "[##########]"
    assert _format_bar(150, width=10) == "[##########]"  # Cap at 100%
    assert _format_bar(-10, width=10) == "[..........]"  # Floor at 0%


def test_format_reset():
    assert _format_reset(0) == "n/a"
    assert _format_reset(None) == "n/a"

    now = int(time.time())
    # 2 days, 3 hours ahead
    future = now + (2 * 86400) + (3 * 3600)
    assert _format_reset(future) == "2d 3h"

    # Past time should show 0d 0h
    past = now - 3600
    assert _format_reset(past) == "0d 0h"


@mock.patch("models.codex.cli._load_accounts_in_order")
@mock.patch("models.codex.cli.account.get_active_email")
@mock.patch("models.codex.cli._fetch_quotas_parallel")
def test_cmd_status(mock_fetch, mock_active, mock_load, capsys):
    acc1 = CodexAccount("a@test", "", "", "", "", "free", {}, False, 0, 0)
    acc2 = CodexAccount("b@test", "", "", "", "", "plus", {}, False, 0, 0)
    
    mock_load.return_value = [acc1, acc2]
    mock_active.return_value = "a@test"
    
    q1 = CodexQuota("a@test", "free", 50, int(time.time()) + 86400, False, 0, 0, 0, 0)
    # Simulate an error for acc2
    mock_fetch.return_value = ([(acc1, q1)], [(acc2, Exception("API Error"))])

    with mock.patch("models.codex.cli.account.save_account"):
        result = cmd_status(argparse.Namespace())

    assert result == 0
    captured = capsys.readouterr()
    stdout = captured.out

    assert "Codex Account Status" in stdout
    # Ensure active account is marked
    assert "> a@test" in stdout
    # Ensure progress bar exists
    assert "[#####.....]  50%" in stdout
    # Ensure error is reported for b@test
    assert "error: API Error" in stdout


@mock.patch("models.codex.cli._load_accounts_in_order")
@mock.patch("models.codex.cli.account.get_active_email")
def test_cmd_list(mock_active, mock_load, capsys):
    acc1 = CodexAccount("a@test", "", "", "", "", "", {}, False, 0, 0)
    acc2 = CodexAccount("b@test", "", "", "", "", "", {}, False, 0, 0)
    
    mock_load.return_value = [acc1, acc2]
    mock_active.return_value = "b@test"

    result = cmd_list(argparse.Namespace())
    
    assert result == 0
    captured = capsys.readouterr()
    assert "  a@test" in captured.out
    assert "> b@test" in captured.out


@mock.patch("models.codex.cli.account.set_active_account")
def test_cmd_switch(mock_set_active, capsys):
    mock_target = mock.MagicMock()
    mock_target.email = "target@test.com"
    mock_set_active.return_value = mock_target

    args = argparse.Namespace(email="target@test.com")
    result = cmd_switch(args)

    assert result == 0
    mock_set_active.assert_called_once_with("target@test.com")
    assert "Active account set to target@test.com" in capsys.readouterr().out


@mock.patch("models.codex.cli.account.import_current_account")
def test_cmd_import(mock_import, capsys):
    mock_acc = mock.MagicMock()
    mock_acc.email = "imported@test.com"
    mock_import.return_value = mock_acc

    result = cmd_import(argparse.Namespace())
    
    assert result == 0
    assert "Imported account imported@test.com" in capsys.readouterr().out


@mock.patch("subprocess.run")
def test_cmd_login(mock_run):
    args = argparse.Namespace(device_auth=False)
    result = cmd_login(args)
    
    assert result == 0
    mock_run.assert_called_once_with(["codex", "login"], check=True)

    # Test device auth
    mock_run.reset_mock()
    args.device_auth = True
    result = cmd_login(args)
    assert result == 0
    mock_run.assert_called_once_with(["codex", "login", "--device-auth"], check=True)


@mock.patch("models.codex.cli.account.remove_account")
def test_cmd_remove(mock_remove, capsys):
    args = argparse.Namespace(email="remove@test.com")
    result = cmd_remove(args)
    
    assert result == 0
    mock_remove.assert_called_once_with("remove@test.com")
    assert "Removed account remove@test.com" in capsys.readouterr().out


@mock.patch("models.codex.cli._load_accounts_in_order")
@mock.patch("models.codex.cli._fetch_quotas_parallel")
@mock.patch("models.codex.cli.account.get_active_email")
@mock.patch("models.codex.cli.account.set_active_account")
def test_cmd_rotate(mock_set_active, mock_active, mock_fetch, mock_load, capsys):
    acc1 = CodexAccount("high@test", "", "", "", "", "", {}, False, 0, 0)
    acc2 = CodexAccount("low@test", "", "", "", "", "", {}, False, 0, 0)
    acc3 = CodexAccount("exhausted@test", "", "", "", "", "", {}, False, 0, 0)
    
    mock_load.return_value = [acc1, acc2, acc3]
    mock_active.return_value = "high@test"
    
    q1 = CodexQuota("high@test", "free", 90, 0, False, 0, 0, 0, 0)
    q2 = CodexQuota("low@test", "free", 20, 0, False, 0, 0, 0, 0)
    q3 = CodexQuota("exhausted@test", "free", 100, 0, True, 0, 0, 0, 0)
    
    mock_fetch.return_value = ([(acc1, q1), (acc2, q2), (acc3, q3)], [])

    result = cmd_rotate(argparse.Namespace())
    
    assert result == 0
    mock_set_active.assert_called_once_with("low@test")
    assert "Switched to low@test (20% used)" in capsys.readouterr().out


@mock.patch("models.codex.cli._load_accounts_in_order")
@mock.patch("models.codex.cli._fetch_quotas_parallel")
@mock.patch("models.codex.cli.account.get_active_email")
def test_cmd_rotate_already_best(mock_active, mock_fetch, mock_load, capsys):
    acc1 = CodexAccount("best@test", "", "", "", "", "", {}, False, 0, 0)
    acc2 = CodexAccount("worst@test", "", "", "", "", "", {}, False, 0, 0)
    
    mock_load.return_value = [acc1, acc2]
    mock_active.return_value = "best@test"
    
    q1 = CodexQuota("best@test", "free", 10, 0, False, 0, 0, 0, 0)
    q2 = CodexQuota("worst@test", "free", 99, 0, False, 0, 0, 0, 0)
    
    mock_fetch.return_value = ([(acc1, q1), (acc2, q2)], [])

    with mock.patch("models.codex.cli.account.set_active_account") as mock_set:
        result = cmd_rotate(argparse.Namespace())
    
    assert result == 0
    mock_set.assert_not_called()
    assert "Already on best account best@test" in capsys.readouterr().out
