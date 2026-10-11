"""Tests of the recorder the user's status line passes its input to. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import datetime
import io
import json
import os
import sys

import pytest

import record_rate_limits

T0 = datetime.datetime(2026, 9, 28, 12, 0, tzinfo=datetime.timezone.utc)
FIVE_HOUR = {"used_percentage": 23.5, "resets_at": 1790600400}
SEVEN_DAY = {"used_percentage": 41.2, "resets_at": 1791000000}


def status(five_hour=FIVE_HOUR, seven_day=SEVEN_DAY, session="s1", **extra) -> str:
    limits = {}
    if five_hour is not None:
        limits["five_hour"] = five_hour
    if seven_day is not None:
        limits["seven_day"] = seven_day
    body = {"session_id": session, "model": {"id": "claude-opus-5-5"}, "rate_limits": limits} | extra
    # As Claude Code writes it: text outside ASCII (a path under a user's name, say) is not escaped.
    return json.dumps(body, ensure_ascii=False)


def lines(record) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]


def feed(record, text: str, now=T0) -> None:
    record_rate_limits.record_input(record, text, now)


def test_the_windows_are_recorded_with_the_time_and_the_session(tmp_path):
    record = tmp_path / "rate-limits.jsonl"
    feed(record, status())
    assert lines(record) == [{"time": T0.isoformat(), "session_id": "s1",
                              "five_hour": FIVE_HOUR, "seven_day": SEVEN_DAY}]


def test_an_input_without_rate_limits_writes_nothing(tmp_path):
    record = tmp_path / "rate-limits.jsonl"
    feed(record, json.dumps({"session_id": "s1", "model": {"id": "claude-opus-5-5"}}))
    assert not record.exists()


def test_a_missing_window_is_kept_as_null(tmp_path):
    record = tmp_path / "rate-limits.jsonl"
    feed(record, status(five_hour=None))
    [entry] = lines(record)
    assert entry["five_hour"] is None
    assert entry["seven_day"] == SEVEN_DAY


@pytest.mark.parametrize("text, reason", [
    ("{not json", "Expecting property name"),
    ("", "Expecting value"),
    ("[1, 2]", "not a JSON object"),
    (json.dumps({"rate_limits": [1]}), "rate_limits is not an object"),
    (status(five_hour={"used_percentage": "23", "resets_at": 1790600400}), "five_hour.used_percentage"),
    (status(five_hour={"used_percentage": -5, "resets_at": 1790600400}), "five_hour.used_percentage"),
    (status(five_hour={"used_percentage": 150, "resets_at": 1790600400}), "five_hour.used_percentage"),
    (status(five_hour={"used_percentage": 3, "resets_at": "2026-09-28"}), "five_hour.resets_at"),
    (status(five_hour=[3, 1790600400]), "five_hour is not an object"),
])
def test_an_input_it_cannot_read_leaves_an_error_line(tmp_path, text, reason):
    record = tmp_path / "rate-limits.jsonl"
    feed(record, text)
    [entry] = lines(record)
    assert entry["time"] == T0.isoformat()
    assert reason in entry["error"]


@pytest.mark.parametrize("seven_day", [
    {"used_percentage": 3, "resets_at": "2026-09-28"},
    {"used_percentage": 3, "resets_at": 1791000000.5},
    {"used_percentage": "3", "resets_at": 1791000000},
    {"resets_at": 1791000000},
    [3, 1791000000],
])
def test_a_7_day_window_that_does_not_read_does_not_lose_the_5_hour_one(tmp_path, seven_day):
    # No check reads the 7-day window, so it is not what an input is refused for.
    record = tmp_path / "rate-limits.jsonl"
    feed(record, status(seven_day=seven_day))
    assert lines(record) == [{"time": T0.isoformat(), "session_id": "s1", "five_hour": FIVE_HOUR,
                              "seven_day": None}]


def test_the_same_windows_are_not_written_again_within_the_heartbeat(tmp_path):
    record = tmp_path / "rate-limits.jsonl"
    feed(record, status(session="s1"))
    feed(record, status(session="s2"), T0 + datetime.timedelta(minutes=4, seconds=59))
    assert len(lines(record)) == 1


def test_the_same_windows_are_written_again_after_the_heartbeat(tmp_path):
    record = tmp_path / "rate-limits.jsonl"
    feed(record, status())
    later = T0 + datetime.timedelta(minutes=5)
    feed(record, status(), later)
    assert [entry["time"] for entry in lines(record)] == [T0.isoformat(), later.isoformat()]


@pytest.mark.parametrize("changed", [
    {"five_hour": {"used_percentage": 23.6, "resets_at": 1790600400}},
    {"five_hour": {"used_percentage": 23.5, "resets_at": 1790618400}},
    {"seven_day": {"used_percentage": 41.3, "resets_at": 1791000000}},
    {"five_hour": None},
    {"seven_day": None},
])
def test_a_change_in_either_window_is_written_at_once(tmp_path, changed):
    record = tmp_path / "rate-limits.jsonl"
    feed(record, status())
    feed(record, status(**changed), T0 + datetime.timedelta(seconds=1))
    assert len(lines(record)) == 2
    assert all(lines(record)[-1][name] == value for name, value in changed.items())


def test_the_windows_are_written_again_after_an_error_line(tmp_path):
    # With both windows gone, the error line's missing windows would compare as the same.
    record = tmp_path / "rate-limits.jsonl"
    feed(record, status(five_hour=None, seven_day=None))
    feed(record, "{not json", T0 + datetime.timedelta(seconds=1))
    feed(record, status(five_hour=None, seven_day=None), T0 + datetime.timedelta(seconds=2))
    assert ["error" in entry for entry in lines(record)] == [False, True, False]


def test_a_line_cut_short_is_closed_before_the_next(tmp_path):
    record = tmp_path / "rate-limits.jsonl"
    record.write_text('{"time": "2026-09-28T11:59:00+00:00", "five_h', encoding="utf-8", newline="")
    feed(record, status())
    text = record.read_text(encoding="utf-8").splitlines()
    assert len(text) == 2
    assert json.loads(text[1])["five_hour"] == FIVE_HOUR


def test_a_last_line_without_a_time_zone_is_no_guide(tmp_path):
    record = tmp_path / "rate-limits.jsonl"
    last = {"time": "2026-09-28T12:00:00", "session_id": "s1", "five_hour": FIVE_HOUR, "seven_day": SEVEN_DAY}
    record.write_text(json.dumps(last) + "\n", encoding="utf-8", newline="")
    feed(record, status(), T0 + datetime.timedelta(seconds=1))
    assert len(lines(record)) == 2


def test_it_prints_nothing(tmp_path, monkeypatch, capsys):
    record = tmp_path / "rate-limits.jsonl"
    for text in (status(), "{not json", json.dumps({"session_id": "s1"})):
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(text.encode("utf-8"))))
        assert record_rate_limits.main(["--record", str(record)]) == 0
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
    assert len(lines(record)) == 2


def test_a_record_it_cannot_write_is_told_on_standard_error_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(status().encode("utf-8"))))
    assert record_rate_limits.main(["--record", str(tmp_path / "no-such-dir" / "r.jsonl")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot keep the record: FileNotFoundError" in captured.err and "r.jsonl" in captured.err


@pytest.mark.parametrize("heartbeat, written", [("0", 3), ("300", 1)])
def test_the_heartbeat_can_be_set(tmp_path, monkeypatch, heartbeat, written):
    record = tmp_path / "rate-limits.jsonl"
    for _ in range(3):
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(status().encode("utf-8"))))
        assert record_rate_limits.main(["--record", str(record), "--heartbeat", heartbeat]) == 0
    assert len(lines(record)) == written


# ── The user's status line command ─────────────────────────────────────────────

# A stand-in for the user's command: it shows its arguments and the input it was given,
# byte for byte, so what it shows does not turn on the encoding of the platform.
SHOW = "import sys; sys.stdout.buffer.write(' '.join(sys.argv[1:]).encode() + b'|' + sys.stdin.buffer.read())"


def run_with(monkeypatch, record, text: str, *users_command: str) -> int:
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(text.encode("utf-8"))))
    return record_rate_limits.main(["--record", str(record), "--", *users_command])


def test_the_users_command_is_given_the_same_input_and_shows_what_it_prints(tmp_path, monkeypatch, capfd):
    record = tmp_path / "rate-limits.jsonl"
    text = status(note="日本語")
    assert "日本語" in text
    assert run_with(monkeypatch, record, text, sys.executable, "-c", SHOW) == 0
    captured = capfd.readouterr()
    assert (captured.out, captured.err) == ("|" + text, "")
    assert len(lines(record)) == 1


def test_what_follows_the_cut_is_the_commands_own(tmp_path, monkeypatch, capfd):
    record = tmp_path / "rate-limits.jsonl"
    assert run_with(monkeypatch, record, status(), sys.executable, "-c", SHOW, "--record", "x", "--", "-h") == 0
    assert capfd.readouterr().out.startswith("--record x -- -h|")
    assert len(lines(record)) == 1


def test_the_record_is_written_before_the_users_command_runs(tmp_path, monkeypatch, capfd):
    record = tmp_path / "rate-limits.jsonl"
    count = "import sys; sys.stdout.write(str(len(open(sys.argv[1], encoding='utf-8').readlines())))"
    assert run_with(monkeypatch, record, status(), sys.executable, "-c", count, str(record)) == 0
    assert capfd.readouterr().out == "1"


def test_the_users_command_runs_though_the_record_cannot_be_written(tmp_path, monkeypatch, capfd):
    code = run_with(monkeypatch, tmp_path / "no-such-dir" / "r.jsonl", status(), sys.executable, "-c", SHOW)
    captured = capfd.readouterr()
    # A status line command that fails is shown as nothing, so the failure is not in the status.
    assert code == 0
    assert captured.out == "|" + status()
    assert "cannot keep the record: FileNotFoundError" in captured.err


def test_a_record_that_cannot_be_read_is_not_told_as_one_that_cannot_be_written(tmp_path, monkeypatch, capfd):
    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(record_rate_limits, "read_tail", refuse)
    assert run_with(monkeypatch, tmp_path / "rate-limits.jsonl", status()) == 1
    told = capfd.readouterr().err
    assert "cannot keep the record: PermissionError" in told and "write" not in told


@pytest.mark.parametrize("names_the_record, own, told", [
    (True, ["--heartbeat", "nan"], "ValueError"),
    (True, ["--heartbeat", "soon"], "invalid float value"),
    (True, ["--no-such-option"], "unrecognized arguments"),
    (False, [], "--record"),
])
def test_the_users_command_runs_whatever_goes_wrong_in_recording(tmp_path, monkeypatch, capfd,
                                                                 names_the_record, own, told):
    record = tmp_path / "rate-limits.jsonl"
    arguments = (["--record", str(record)] if names_the_record else []) + own
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(status().encode("utf-8"))))
    code = record_rate_limits.main([*arguments, "--", sys.executable, "-c", SHOW])
    captured = capfd.readouterr()
    assert (code, captured.out) == (0, "|" + status())
    assert told in captured.err
    assert not record.exists()


@pytest.mark.parametrize("own, code", [(["--heartbeat", "nan"], 1), (["--heartbeat", "soon"], 2)])
def test_without_a_command_the_status_tells_what_went_wrong_in_recording(tmp_path, monkeypatch, capfd, own, code):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(status().encode("utf-8"))))
    assert record_rate_limits.main(["--record", str(tmp_path / "rate-limits.jsonl"), *own]) == code
    assert capfd.readouterr().out == ""


@pytest.mark.parametrize("own, code, told", [(["--help"], 0, "out"), (["--no-such-option"], 2, "err")])
def test_arguments_alone_are_answered_without_waiting_for_the_input(monkeypatch, capfd, own, code, told):
    class AtATerminal:
        """Standard input that has no end: reading it would wait."""

        @property
        def buffer(self):
            pytest.fail("waited for the input")

    monkeypatch.setattr("sys.stdin", AtATerminal())
    assert record_rate_limits.main(own) == code
    assert "--record" in getattr(capfd.readouterr(), told)


def test_the_exit_status_of_a_failing_command_is_returned(tmp_path, monkeypatch, capfd):
    record = tmp_path / "rate-limits.jsonl"
    assert run_with(monkeypatch, record, status(), sys.executable, "-c", "import sys; sys.exit(7)") == 7
    assert len(lines(record)) == 1


def test_a_command_that_is_not_found_is_told_on_standard_error(tmp_path, monkeypatch, capfd):
    record = tmp_path / "rate-limits.jsonl"
    assert run_with(monkeypatch, record, status(), "no-such-program-here", "x") == 127
    captured = capfd.readouterr()
    assert captured.out == ""
    assert "cannot find no-such-program-here" in captured.err and "bash <script>" in captured.err
    assert len(lines(record)) == 1


def test_a_command_that_cannot_be_run_is_told_on_standard_error(tmp_path, monkeypatch, capfd):
    record = tmp_path / "rate-limits.jsonl"

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(record_rate_limits.subprocess, "run", refuse)
    assert run_with(monkeypatch, record, status(), sys.executable, "-c", SHOW) == 126
    captured = capfd.readouterr()
    assert captured.out == ""
    assert "cannot run" in captured.err and "Permission denied" in captured.err


def test_without_a_command_nothing_is_run(tmp_path, monkeypatch, capfd):
    record = tmp_path / "rate-limits.jsonl"
    monkeypatch.setattr(record_rate_limits.subprocess, "run", lambda *args, **kwargs: pytest.fail("ran a command"))
    assert run_with(monkeypatch, record, status()) == 0
    assert capfd.readouterr().out == ""


# ── Where the user's command is looked for ─────────────────────────────────────

def plant(directory, name: str = "planted"):
    """A program of this name in the directory, as the platform runs one."""
    if sys.platform == "win32":
        program = directory / f"{name}.bat"
        program.write_text("@echo planted", encoding="ascii")
    else:
        program = directory / name
        program.write_text("#!/bin/sh" + chr(10) + "echo planted", encoding="ascii")
        program.chmod(0o755)
    return program


@pytest.fixture
def beside_a_program(tmp_path, monkeypatch):
    """The current directory holds a program, as a checkout may hold a file named bash."""
    program = plant(tmp_path)
    monkeypatch.chdir(tmp_path)
    # With this set, Python 3.12 and later leave the current directory out by themselves.
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    return program


def test_a_program_lying_in_the_current_directory_is_not_the_one_named(beside_a_program):
    # Only Windows looks there unasked; elsewhere this holds without the guard.
    assert record_rate_limits.on_path("planted") is None


def test_a_program_lying_in_the_current_directory_is_not_run(beside_a_program, monkeypatch, capfd):
    record = beside_a_program.parent / "rate-limits.jsonl"
    assert run_with(monkeypatch, record, status(), "planted") == 127
    captured = capfd.readouterr()
    assert captured.out == ""
    assert "cannot find planted" in captured.err


def test_a_program_on_path_is_found(tmp_path, monkeypatch):
    directory = tmp_path / "bin"
    directory.mkdir()
    program = plant(directory)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    found = record_rate_limits.on_path("planted")
    assert found is not None and os.path.samefile(found, program)


def test_a_name_with_its_ending_is_found_as_it_stands(tmp_path, monkeypatch):
    directory = tmp_path / "bin"
    directory.mkdir()
    program = plant(directory)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    found = record_rate_limits.on_path(program.name)
    assert found is not None and os.path.samefile(found, program)


@pytest.mark.skipif(sys.platform != "win32", reason="elsewhere an empty entry of PATH names the current directory")
def test_an_empty_entry_of_path_does_not_name_the_current_directory(beside_a_program, monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep + os.environ["PATH"] + os.pathsep)
    assert record_rate_limits.on_path("planted") is None


def test_a_program_on_path_is_found_though_one_of_its_name_lies_in_the_current_directory(
        beside_a_program, tmp_path, monkeypatch):
    directory = tmp_path / "bin"
    directory.mkdir()
    program = plant(directory)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    found = record_rate_limits.on_path("planted")
    assert found is not None and os.path.samefile(found, program)


@pytest.mark.parametrize("named", [os.curdir, os.curdir + os.sep])
def test_a_path_that_names_the_current_directory_is_the_users_choice(beside_a_program, monkeypatch, named):
    monkeypatch.setenv("PATH", os.environ["PATH"] + os.pathsep + named)
    found = record_rate_limits.on_path("planted")
    assert found is not None and os.path.samefile(found, beside_a_program)


def test_where_the_path_names_the_current_directory_is_where_it_is_looked_in(beside_a_program, tmp_path, monkeypatch):
    directory = tmp_path / "bin"
    directory.mkdir()
    program = plant(directory)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.curdir)
    found = record_rate_limits.on_path("planted")
    assert found is not None and os.path.samefile(found, program)


def test_a_name_that_gives_its_directory_is_taken_as_given(beside_a_program):
    found = record_rate_limits.on_path(os.path.join(os.curdir, beside_a_program.name))
    assert found is not None and os.path.samefile(found, beside_a_program)
