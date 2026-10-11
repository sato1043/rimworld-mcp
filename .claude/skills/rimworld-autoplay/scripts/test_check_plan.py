"""Tests of the check that a cycle wrote the plan file and kept its sections. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib

import pytest

import check_plan
from check_plan import (ITEM_FIELDS, Untrusted, check, items_without_fields, keep_start, kept_start,
                        plan_sections, required_headings, template_body)

# Shaped like colony-plan-template.md: prose and a title outside the code block, a
# placeholder title and sections of two levels inside it.
TEMPLATE = """\
# コロニー方針ファイルの雛形

## 説明の見出し

```markdown
# <コロニー名>

## 長期方針

- クリアの経路:

## 書き足しの候補

### 承認済み

## 経過のメモ
```
"""
SECTIONS = ["## 長期方針", "## 書き足しの候補", "### 承認済み", "## 経過のメモ"]
PLAN = "# テスト\n\n" + "\n\n".join(f"{heading}\n\n- x" for heading in SECTIONS) + "\n"
STARTED = 1_000_000.0


def write_plan(directory, text=PLAN, mtime=STARTED + 10):
    plan = directory / "plan.md"
    plan.write_text(text, encoding="utf-8", newline="")
    os.utime(plan, (mtime, mtime))
    return plan


def test_reads_the_sections_inside_the_code_block_only():
    assert required_headings(TEMPLATE) == SECTIONS


def test_a_template_without_sections_cannot_be_trusted():
    with pytest.raises(Untrusted, match="no headings"):
        required_headings("# 雛形\n\n## 説明\n\n```\n## not markdown\n```\n")


def test_the_real_template_has_sections():
    headings = required_headings(check_plan.TEMPLATE.read_text(encoding="utf-8"))
    assert "## 出来事の位置" in headings
    assert "# <コロニー名>" not in headings


def test_a_plan_written_during_the_cycle_with_every_section_passes(tmp_path):
    assert check(write_plan(tmp_path), TEMPLATE, STARTED) == []


def test_a_plan_saved_with_a_byte_order_mark_is_read_from_its_first_heading(tmp_path):
    byte_order_mark = chr(0xFEFF)
    plan = write_plan(tmp_path, byte_order_mark + PLAN.replace("# テスト\n\n", ""))
    assert plan.read_bytes().startswith(b"\xef\xbb\xbf## ")
    assert check(plan, TEMPLATE, STARTED) == []


def test_a_plan_not_written_during_the_cycle_fails(tmp_path):
    assert check(write_plan(tmp_path, mtime=STARTED), TEMPLATE, STARTED) == [
        "plan.md was not written during the cycle"]


@pytest.mark.parametrize("heading", SECTIONS)
def test_a_missing_section_is_named(tmp_path, heading):
    plan = write_plan(tmp_path, PLAN.replace(f"{heading}\n", ""))
    assert check(plan, TEMPLATE, STARTED) == [f"plan.md misses the sections {heading}"]


def test_a_section_heading_at_another_level_does_not_count(tmp_path):
    plan = write_plan(tmp_path, PLAN.replace("### 承認済み", "## 承認済み"))
    assert check(plan, TEMPLATE, STARTED) == ["plan.md misses the sections ### 承認済み"]


def test_a_heading_inside_a_code_block_of_the_plan_does_not_count():
    assert plan_sections("```\n## 長期方針\n```\n## 経過のメモ\n") == ({"## 経過のメモ": []}, False)


# Sections of a plan with items shaped as rimworld-play's step 6 asks.
WORK = "### 進行中の対応"
PREMISES = "### 前提と根拠"
# Written out rather than imported, so that a change to what the line tells a cycle fails.
ONE_ITEM = (" (a list entry at the start of a line is one item, with the lines under it; "
            "keep all the fields of an item in that one entry)")


def fields_problems(text: str) -> list[str]:
    return items_without_fields(plan_sections(text)[0])


def test_items_with_their_fields_pass():
    assert fields_problems(f"{WORK}\n\n- 北に 3 人: 襲撃に備える。終わる条件: 敵が去る。次に確かめること: 負傷者\n\n"
                           f"{PREMISES}\n\n- 狩りを止めた: 食料が 10 日分。見直す条件: 5 日分を切る\n") == []


def test_sections_without_items_pass():
    assert fields_problems(f"{WORK}\n\n{PREMISES}\n\n## 利用者に頼むこと\n\n- なし\n") == []


def test_items_without_their_field_are_counted_per_section():
    text = (f"{WORK}\n\n- 北に 3 人: 襲撃に備える\n- 救護のエリアを作った。終わる条件: 負傷者がいない\n"
            f"- 招集している者はいない\n\n{PREMISES}\n\n- 撃つ位置は北の小屋の外\n")
    assert fields_problems(text) == [f"plan.md has 2 item(s) without the field 終わる条件: in {WORK}{ONE_ITEM}",
                                     f"plan.md has 1 item(s) without the field 見直す条件: in {PREMISES}{ONE_ITEM}"]


@pytest.mark.parametrize("body", ["1. 北に 3 人: 襲撃に備える", "対応なし", "北に 3 人\n- 救護。終わる条件: 負傷者がいない"])
def test_numbered_items_and_prose_are_items_too(body):
    assert fields_problems(f"{WORK}\n\n{body}\n") == [f"plan.md has 1 item(s) without the field 終わる条件: in {WORK}{ONE_ITEM}"]


def test_a_numbered_item_with_its_field_passes():
    assert fields_problems(f"{WORK}\n\n1. 北に 3 人: 襲撃に備える。終わる条件: 敵が去る\n") == []


def test_each_numbered_item_is_counted_on_its_own():
    text = f"{WORK}\n\n1. 北に 3 人: 襲撃に備える\n2. 救護のエリア。終わる条件: 負傷者がいない\n"
    assert fields_problems(text) == [f"plan.md has 1 item(s) without the field 終わる条件: in {WORK}{ONE_ITEM}"]


def test_an_empty_item_has_no_field():
    assert fields_problems(f"{WORK}\n\n-\n") == [f"plan.md has 1 item(s) without the field 終わる条件: in {WORK}{ONE_ITEM}"]


def test_the_field_of_the_other_section_does_not_count():
    text = f"{WORK}\n\n- 待機。見直す条件: 敵が去る\n\n{PREMISES}\n\n- 待機の根拠。終わる条件: 敵が去る\n"
    assert fields_problems(text) == [f"plan.md has 1 item(s) without the field 終わる条件: in {WORK}{ONE_ITEM}",
                                     f"plan.md has 1 item(s) without the field 見直す条件: in {PREMISES}{ONE_ITEM}"]


@pytest.mark.parametrize("item", [
    "- 北に 3 人: 襲撃に備える。\n  終わる条件: 敵が去る",
    "- 北に 3 人: 襲撃に備える。終わる\n  条件: 敵が去る",
    "- 北に 3 人: 襲撃に備える\n    - 終わる条件: 敵が去る",
    "- 北に 3 人: 襲撃に備える。終わる条件：敵が去る",
])
def test_the_field_is_found_on_the_lines_after_the_item(item):
    assert fields_problems(f"{WORK}\n\n{item}\n") == []


def test_the_field_of_the_next_item_does_not_count_for_the_one_before():
    text = f"{WORK}\n\n- 北に 3 人: 襲撃に備える\n- 救護のエリア。終わる条件: 負傷者がいない\n"
    assert fields_problems(text) == [f"plan.md has 1 item(s) without the field 終わる条件: in {WORK}{ONE_ITEM}"]


def test_an_item_written_as_a_bullet_per_field_fails_for_each_bullet_without_the_field():
    # What a cycle of the live run wrote for one piece of work, and took for one item.
    text = f"{WORK}\n\n- 何を: 北に 3 人\n- なぜ: 襲撃に備える\n- 終わる条件: 敵が去る\n- 次に確かめること: 負傷者\n"
    assert fields_problems(text) == [f"plan.md has 3 item(s) without the field 終わる条件: in {WORK}{ONE_ITEM}"]


def test_an_item_inside_a_code_block_does_not_count():
    assert fields_problems(f"{WORK}\n\n```\n- 北に 3 人\n```\n") == []


def test_the_real_template_shows_each_field_in_its_section():
    sections = plan_sections(template_body(check_plan.TEMPLATE.read_text(encoding="utf-8")))[0]
    for heading in ITEM_FIELDS:
        assert sections[heading], heading
    assert items_without_fields(sections) == []


def sample_problem(heading: str) -> str:
    return f"plan.md keeps the template's sample item in {heading}: write the colony's own or remove it"


def test_a_plan_made_from_the_template_as_it_is_keeps_its_samples(tmp_path):
    template = check_plan.TEMPLATE.read_text(encoding="utf-8")
    plan = write_plan(tmp_path, template_body(template))
    assert check(plan, template, STARTED) == [sample_problem(WORK), sample_problem(PREMISES)]


def test_a_plan_whose_samples_are_written_over_passes(tmp_path):
    template = check_plan.TEMPLATE.read_text(encoding="utf-8")
    body = template_body(template)
    samples = plan_sections(body)[0]
    own = {WORK: "北に 3 人: 襲撃に備える。終わる条件: 敵が去る", PREMISES: "狩りを止めた: 食料が 10 日分。見直す条件: 5 日分を切る"}
    for heading, item in own.items():
        [sample] = samples[heading]
        assert f"- {sample}\n" in body
        body = body.replace(f"- {sample}\n", f"- {item}\n")
    assert check(write_plan(tmp_path, body), template, STARTED) == []


def test_a_plan_with_an_item_without_its_field_fails(tmp_path):
    plan = write_plan(tmp_path, PLAN + f"\n{WORK}\n\n- 北に 3 人: 襲撃に備える\n")
    assert check(plan, TEMPLATE, STARTED) == [
        f"plan.md has 1 item(s) without the field 終わる条件: in {WORK}{ONE_ITEM}"]


def test_a_code_block_left_open_is_named(tmp_path):
    plan = write_plan(tmp_path, PLAN.replace("## 経過のメモ", "```\n## 経過のメモ"))
    assert check(plan, TEMPLATE, STARTED) == ["plan.md has a code block that is not closed",
                                              "plan.md misses the sections ## 経過のメモ"]


def test_a_missing_plan_fails(tmp_path):
    assert check(tmp_path / "plan.md", TEMPLATE, STARTED) == ["plan.md is missing"]


def test_the_kept_time_is_read_back(tmp_path):
    keep_start(tmp_path, STARTED)
    assert kept_start(tmp_path) == STARTED


@pytest.mark.parametrize("content", [None, "not json", '{"other": 1}', '{"started_at": "x"}',
                                     '{"started_at": true}'])
def test_a_time_that_was_not_kept_cannot_be_trusted(tmp_path, content):
    if content is not None:
        (tmp_path / "cycle.json").write_text(content, encoding="utf-8", newline="")
    with pytest.raises(Untrusted):
        kept_start(tmp_path)


def test_a_second_mark_is_not_kept_over_the_first(tmp_path):
    keep_start(tmp_path, STARTED)
    with pytest.raises(FileExistsError):
        keep_start(tmp_path, STARTED + 1)
    assert kept_start(tmp_path) == STARTED
    assert [path.name for path in tmp_path.iterdir()] == ["cycle.json"]


def test_the_mark_appears_with_its_time_already_in_it(tmp_path, monkeypatch):
    # The watcher stops on a mark without a time, so no moment may show an empty one.
    seen = []

    def link(source, target):
        seen.append(json.loads(pathlib.Path(source).read_text(encoding="utf-8")))
        real_link(source, target)
    real_link = os.link
    monkeypatch.setattr(check_plan.os, "link", link)
    keep_start(tmp_path, STARTED)
    assert seen == [{"started_at": STARTED}]
    assert [path.name for path in tmp_path.iterdir()] == ["cycle.json"]


@pytest.mark.parametrize("refusals, removed", [(check_plan.REMOVE_TRIES - 1, True),
                                               (check_plan.REMOVE_TRIES, False)])
def test_a_mark_held_open_for_an_instant_is_removed_on_a_later_try(tmp_path, monkeypatch, refusals,
                                                                     removed):
    keep_start(tmp_path, STARTED)
    real_unlink = pathlib.Path.unlink
    left = [refusals]

    def unlink(path, *args, **kwargs):
        if path.name == "cycle.json" and left[0]:
            left[0] -= 1
            raise PermissionError("held open by the watcher")
        real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(pathlib.Path, "unlink", unlink)
    monkeypatch.setattr(check_plan.time, "sleep", lambda seconds: None)
    if removed:
        check_plan.remove_mark(tmp_path / "cycle.json")
    else:
        with pytest.raises(PermissionError):
            check_plan.remove_mark(tmp_path / "cycle.json")
    assert (tmp_path / "cycle.json").exists() is not removed


@pytest.fixture
def play(tmp_path, monkeypatch):
    template = tmp_path / "template.md"
    template.write_text(TEMPLATE, encoding="utf-8", newline="")
    monkeypatch.setattr(check_plan, "PLAY_ROOT", tmp_path / ".claude" / "play")
    monkeypatch.setattr(check_plan, "TEMPLATE", template)
    colony = tmp_path / ".claude" / "play" / "テスト"
    colony.mkdir(parents=True)
    return colony


def one_line(capsys) -> str:
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return out.strip()


def test_main_keeps_the_time_then_passes_a_plan_written_after_it(play, capsys):
    assert check_plan.main(["--colony", "テスト", "--start"]) == 0
    assert one_line(capsys).startswith("started:")
    started = json.loads((play / "cycle.json").read_text(encoding="utf-8"))["started_at"]
    write_plan(play, mtime=started + 1)
    assert check_plan.main(["--colony", "テスト"]) == 0
    assert one_line(capsys).startswith("OK:")
    # The check used the time up: a next cycle without --start cannot pass on it.
    assert check_plan.main(["--colony", "テスト"]) == 2
    assert one_line(capsys).startswith("UNTRUSTED: cannot read the time kept by --start")


def test_main_refuses_to_open_a_cycle_while_one_is_open(play, capsys):
    keep_start(play, STARTED)
    assert check_plan.main(["--colony", "テスト", "--start"]) == 2
    assert one_line(capsys).startswith("UNTRUSTED: a cycle is still open")
    assert kept_start(play) == STARTED
    # The check after closes the old one, and a cycle can open again.
    write_plan(play, mtime=STARTED + 1)
    assert check_plan.main(["--colony", "テスト"]) == 0
    capsys.readouterr()
    assert check_plan.main(["--colony", "テスト", "--start"]) == 0


def test_main_removes_a_mark_that_keeps_no_time(play, capsys):
    (play / "cycle.json").write_text("{}\n", encoding="utf-8", newline="")
    assert check_plan.main(["--colony", "テスト"]) == 2
    assert one_line(capsys).endswith("the mark was removed, so a cycle can open again")
    assert not (play / "cycle.json").exists()
    assert check_plan.main(["--colony", "テスト", "--start"]) == 0


def test_main_writes_every_problem_on_one_line(play, capsys):
    keep_start(play, STARTED)
    write_plan(play, PLAN.replace("## 長期方針\n", "") + f"\n{PREMISES}\n\n- 撃つ位置は北\n", mtime=STARTED)
    assert check_plan.main(["--colony", "テスト"]) == 1
    assert one_line(capsys) == ("FAILED: plan.md was not written during the cycle; "
                                "plan.md misses the sections ## 長期方針; "
                                f"plan.md has 1 item(s) without the field 見直す条件: in {PREMISES}{ONE_ITEM}")


@pytest.mark.parametrize("colony, reason", [("a/b", "not a usable colony name"),
                                             ("無い", "there is no colony directory"),
                                             ("CON", "not a usable colony name")])
def test_main_refuses_a_colony_it_cannot_use(play, capsys, colony, reason):
    assert check_plan.main(["--colony", colony, "--start"]) == 2
    line = one_line(capsys)
    assert line.startswith(f"UNTRUSTED: {reason}")
    if reason == "there is no colony directory":
        assert "of the main checkout; run this from there" in line
    assert not (play.parent / colony / "cycle.json").exists()


def test_main_keeps_the_plan_as_it_was_and_names_it_when_the_check_fails(play, capsys):
    write_plan(play, mtime=STARTED)
    assert check_plan.main(["--colony", "テスト", "--start"]) == 0
    capsys.readouterr()
    assert (play / "plan.md.prev").read_text(encoding="utf-8") == PLAN
    started = kept_start(play)
    write_plan(play, "# 壊れた\n", mtime=started + 1)
    assert check_plan.main(["--colony", "テスト"]) == 1
    stamp = datetime.datetime.fromtimestamp(started, datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    assert one_line(capsys).endswith(f"; the plan as it was before the cycle is in plan.md.before-{stamp}")
    # The next cycle's start copies the spoiled plan to plan.md.prev; the named copy stays.
    assert check_plan.main(["--colony", "テスト", "--start"]) == 0
    capsys.readouterr()
    assert (play / "plan.md.prev").read_text(encoding="utf-8") == "# 壊れた\n"
    assert (play / f"plan.md.before-{stamp}").read_text(encoding="utf-8") == PLAN


def test_a_failed_check_after_a_start_without_a_plan_names_no_older_copy(play, capsys):
    (play / "plan.md.prev").write_text("# 前の前\n", encoding="utf-8", newline="")
    assert check_plan.main(["--colony", "テスト", "--start"]) == 0
    capsys.readouterr()
    assert not (play / "plan.md.prev").exists()
    assert check_plan.main(["--colony", "テスト"]) == 1
    assert "before the cycle" not in one_line(capsys)


def test_main_does_not_keep_the_plan_over_its_copy_while_a_cycle_is_open(play, capsys):
    write_plan(play, mtime=STARTED)
    assert check_plan.main(["--colony", "テスト", "--start"]) == 0
    write_plan(play, "# 途中\n", mtime=STARTED + 1)
    assert check_plan.main(["--colony", "テスト", "--start"]) == 2
    capsys.readouterr()
    assert (play / "plan.md.prev").read_text(encoding="utf-8") == PLAN
