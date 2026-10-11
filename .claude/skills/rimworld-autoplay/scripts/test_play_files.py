"""Tests of the files the autoplay keeps. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import os

import pytest

import play_files
from play_files import replace_file


def refusing(times: int, monkeypatch) -> list[int]:
    """Make os.replace refuse the given number of times, as a file held open does."""
    calls = []
    real = os.replace

    def replace(source, target):
        calls.append(1)
        if len(calls) <= times:
            raise PermissionError("held open by another process")
        real(source, target)
    monkeypatch.setattr(play_files.os, "replace", replace)
    return calls


def test_a_file_is_written_whole(tmp_path):
    replace_file(tmp_path / "a.json", "new\n")
    assert (tmp_path / "a.json").read_bytes() == b"new\n"
    assert not (tmp_path / "a.tmp").exists()


def test_a_replace_refused_for_an_instant_is_tried_again(tmp_path, monkeypatch):
    calls = refusing(play_files.REPLACE_TRIES - 1, monkeypatch)
    replace_file(tmp_path / "a.json", "new\n", sleep=lambda s: None)
    assert (tmp_path / "a.json").read_text(encoding="utf-8") == "new\n"
    assert len(calls) == play_files.REPLACE_TRIES


def test_a_replace_refused_every_time_is_raised(tmp_path, monkeypatch):
    refusing(play_files.REPLACE_TRIES, monkeypatch)
    with pytest.raises(PermissionError):
        replace_file(tmp_path / "a.json", "new\n", sleep=lambda s: None)


@pytest.mark.parametrize("plan, place", [
    ("## 出来事の位置\n\n- next: 74fce4d0.249\n- 読んだ tick: 35665859\n", "74fce4d0.249"),
    ("## 出来事の位置\n\n- next:\n", None),
    ("## 経過のメモ\n\n- next: g.1\n", None),
    ("```\n## 出来事の位置\n\n- next: g.1\n```\n", None),
], ids=["kept", "empty", "other section", "code block"])
def test_the_place_a_cycle_kept_in_the_plan_is_read(plan, place):
    assert play_files.events_place(plan) == place


@pytest.mark.parametrize("name", ["CON", "nul", "Com1", "LPT9.old", "aux .x"])
def test_a_name_windows_keeps_for_a_device_is_refused(name):
    assert "a name Windows keeps for a device" in play_files.colony_name_problem(name)


@pytest.mark.parametrize("name", ["Conrad", "CONSOLE", "COM10", "カルバーソン休憩所", "Base.1"])
def test_a_name_that_only_looks_like_a_device_is_taken(name):
    assert play_files.colony_name_problem(name) is None


def test_a_name_in_decomposed_form_is_refused():
    decomposed = "カ" + chr(0x3099)  # ガ as a kana and a combining voiced mark
    assert "not in composed form" in play_files.colony_name_problem(decomposed)
    assert play_files.colony_name_problem("ガ") is None


def test_a_relative_path_is_taken_from_the_checkout_the_scripts_are_in(tmp_path):
    assert play_files.user_path(".claude/play/colony/usage.log") == (
        play_files.REPO_ROOT / ".claude" / "play" / "colony" / "usage.log")
    assert play_files.user_path(str(tmp_path / "usage.log")) == tmp_path / "usage.log"
