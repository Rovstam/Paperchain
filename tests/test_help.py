from __future__ import annotations

import json

from paperchain.cli import main


def test_help_works_outside_a_project(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = main(["help", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "help"
    commands = [
        command
        for step in payload["data"]["steps"]
        for command in step.get("commands", [])
    ]
    assert any("paperchain init . --title" in command for command in commands)
    assert any("paperchain init . --adopt" in command for command in commands)
    assert "paperchain import" in commands
    assert "paperchain convert" in commands
    assert "paperchain lock" in commands
    assert "paperchain check" in commands
    assert "paperchain build" in commands


def test_help_prints_readable_steps(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["help"]) == 0
    output = capsys.readouterr().out
    assert "Paperchain quick start" in output
    assert 'paperchain init . --title "Project Name"' in output
    assert 'paperchain init . --adopt --title "Project Name"' in output
    assert "paperchain check" in output
    assert "paperchain build" in output


def test_help_json_can_contain_unicode(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init", "Évaluación", "--title", "Fitoterapéuticos", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_argument_errors_keep_the_json_contract(capsys) -> None:
    exit_code = main(["check", "--not-an-option", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["command"] == "check"
    assert payload["errors"][0]["code"] == "usage"
    assert captured.err == ""
