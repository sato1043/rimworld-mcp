"""Tests of the hook that stops a cycle's write outside the plan file. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import ast
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

import cycle_agent
import write_gate
import write_rules
from play_files import PLAN, REPO_ROOT
from write_gate import BROKEN, REFUSED, REQUESTS, STOP, WHEN_BROKEN, step_after
from write_rules import NOT_A_PLAN_FILE, NOT_THERE, UNJUDGED, Kind

SCRIPTS = pathlib.Path(write_gate.__file__).resolve().parent
# What the hook loads when it runs: the gate and the modules behind it.
LOADED = ("write_gate.py", "write_rules.py", "play_files.py")
SKILL = SCRIPTS.parent / "SKILL.md"
DEFINITION = cycle_agent.AGENTS / f"{cycle_agent.CYCLE_AGENT}.md"
PLAN_TEMPLATE = REPO_ROOT / ".claude" / "skills" / "rimworld-play" / "references" / "colony-plan-template.md"
# What a reason opens with after `refused:`, by which SKILL.md tells what happened.
OPENINGS = (BROKEN, NOT_THERE, NOT_A_PLAN_FILE, UNJUDGED)
# What Claude Code puts before the gate's line when it hands it to a cycle (seen in
# 2.1.296), and how much of the whole the definition has a cycle return.
HOOK_PREFIX = ("PreToolUse:Write hook error: [python ${CLAUDE_PROJECT_DIR}/.claude/skills/"
               "rimworld-autoplay/scripts/write_gate.py]: ")
HANDED_ON = 400


@pytest.fixture(scope="module")
def checkout(tmp_path_factory):
    """A checkout the gate runs in: the scripts it loads where the main one has them, and
    two colonies with their plan files. The gate looks for the colonies beside itself."""
    root = tmp_path_factory.mktemp("gate") / "checkout"
    scripts = root / SCRIPTS.relative_to(REPO_ROOT)
    scripts.mkdir(parents=True)
    for name in LOADED:
        shutil.copy(SCRIPTS / name, scripts / name)
    for colony in ("A", "カルバーソン休憩所"):
        (root / ".claude" / "play" / colony).mkdir(parents=True)
        (root / ".claude" / "play" / colony / PLAN).write_text("# plan\n", encoding="utf-8",
                                                              newline="")
    return root


def gate_of(checkout: pathlib.Path) -> pathlib.Path:
    return checkout / SCRIPTS.relative_to(REPO_ROOT) / "write_gate.py"


def call(tool: object, path: object, cwd: object, **more: object) -> dict:
    """A tool call as Claude Code gives it to a PreToolUse hook."""
    return {"session_id": "s", "hook_event_name": "PreToolUse", "cwd": cwd, "tool_name": tool,
            "tool_input": {"file_path": path, **more}, "tool_use_id": "toolu_1"}


def run_gate(stdin: bytes, gate: pathlib.Path) -> subprocess.CompletedProcess:
    # -S and -E: with no site-packages and no PYTHON* variables, as far from the MCP
    # server's environment as the `python` a hook starts. A module of the gate that needs
    # more than the standard library fails every test here. -B: no compiled files are left.
    return subprocess.run([sys.executable, "-S", "-E", "-B", str(gate)], input=stdin,
                          capture_output=True, timeout=60)


def as_bytes(payload: object, ascii_only: bool = False) -> bytes:
    return json.dumps(payload, ensure_ascii=ascii_only).encode("utf-8")


def said(done: subprocess.CompletedProcess) -> str:
    """The reason the gate gave, which is one line."""
    text = done.stderr.decode("utf-8")
    assert text.endswith("\n") and "\n" not in text.rstrip("\r\n")
    return text.rstrip("\r\n")


@pytest.mark.parametrize("tool, colony, relative, more", [
    ("Write", "A", False, {"content": "# plan\n"}),
    ("Edit", "A", False, {"old_string": "a", "new_string": "b"}),
    ("Write", "A", True, {}),
    ("Edit", "カルバーソン休憩所", False, {}),
], ids=["write", "edit", "relative", "name outside ascii"])
@pytest.mark.parametrize("ascii_only", [False, True], ids=["utf-8", "escaped"])
def test_a_write_of_a_plan_file_goes_through(checkout, tool, colony, relative, more, ascii_only):
    path = f".claude/play/{colony}/{PLAN}" if relative else str(
        checkout / ".claude" / "play" / colony / PLAN)
    done = run_gate(as_bytes(call(tool, path, str(checkout), **more), ascii_only),
                    gate_of(checkout))
    assert (done.returncode, done.stdout, done.stderr) == (0, b"", b"")


@pytest.mark.parametrize("tool, path, cwd", [
    ("Write", ".claude/settings.local.json", "."),
    ("Edit", ".claude/settings.local.json", "."),
    ("Write", ".claude/play/A/usage.json", "."),
    ("Write", ".claude/play/A/plan.md", "mcp_server"),
    ("Write", str(pathlib.Path.home() / ".claude" / "settings.json"), "."),
], ids=["write", "edit", "state", "relative from elsewhere", "home"])
def test_a_write_of_another_file_is_stopped_with_the_reason(checkout, tool, path, cwd):
    done = run_gate(as_bytes(call(tool, path, str(checkout / cwd))), gate_of(checkout))
    assert (done.returncode, done.stdout) == (STOP, b"")
    reason = said(done)
    assert reason.startswith(f"{REFUSED} {NOT_A_PLAN_FILE}: ")
    assert reason.endswith(step_after(Kind.ANOTHER_FILE))


def test_a_plan_file_that_is_not_there_is_stopped_and_not_made(checkout):
    path = checkout / ".claude" / "play" / "B" / PLAN
    done = run_gate(as_bytes(call("Write", str(path), str(checkout), content="x")),
                    gate_of(checkout))
    assert (done.returncode, done.stdout) == (STOP, b"")
    assert said(done).startswith(f"{REFUSED} {NOT_THERE}: ")
    assert said(done).endswith(step_after(Kind.NO_PLAN_FILE))
    assert not path.parent.exists()


# A call the gate cannot read, how the reason it gives opens and what it tells the cycle to
# do next: a gate that judged nothing does not send the cycle to the plan file, while a
# call whose path alone cannot be read leaves the plan file as the way on.
GATE_BROKEN = (BROKEN, WHEN_BROKEN)
PATH_UNJUDGED = (UNJUDGED, step_after(Kind.UNREADABLE))
UNREADABLE = {
    "empty": (b"", "it cannot read the tool call: ", GATE_BROKEN),
    "not json": (b"not json", "it cannot read the tool call: ", GATE_BROKEN),
    "not utf-8": (b"\xff\xfe", "it failed: UnicodeDecodeError", GATE_BROKEN),
    "not an object": (["Write", "x"], "it is not a JSON object", GATE_BROKEN),
    "no input": ({"tool_name": "Write"}, "it has no tool_input", GATE_BROKEN),
    "input not an object": ({"tool_name": "Write", "tool_input": "x"}, "it has no tool_input",
                            GATE_BROKEN),
    "no path": (call("Write", None, "."), "names none", PATH_UNJUDGED),
    "path not text": (call("Write", 7, "."), "names none", PATH_UNJUDGED),
    "empty path": (call("Write", "", "."), "names none", PATH_UNJUDGED),
    "relative with no directory": (call("Write", ".claude/play/A/plan.md", None),
                                   "is not known", PATH_UNJUDGED),
}


@pytest.mark.parametrize("case", UNREADABLE)
def test_a_call_that_cannot_be_read_is_stopped(checkout, case):
    payload, reason, (opening, next_step) = UNREADABLE[case]
    done = run_gate(payload if isinstance(payload, bytes) else as_bytes(payload),
                    gate_of(checkout))
    assert (done.returncode, done.stdout) == (STOP, b"")
    assert said(done).startswith(f"{REFUSED} {opening}: ")
    assert reason in said(done)
    assert said(done).endswith(next_step)


@pytest.mark.parametrize("tool", ["Bash", "NotebookEdit", "Read", "write", None, ["Write"]],
                         ids=repr)
def test_a_tool_the_gate_is_not_meant_for_is_stopped(checkout, tool):
    plan = str(checkout / ".claude" / "play" / "A" / PLAN)
    done = run_gate(as_bytes(call(tool, plan, str(checkout))), gate_of(checkout))
    assert done.returncode == STOP
    assert said(done).startswith(
        f"{REFUSED} {BROKEN}: it judges Edit, Write only, not {tool!r}. ")
    assert said(done).endswith(WHEN_BROKEN)


def test_a_gate_whose_rules_do_not_load_stops_the_write(checkout, tmp_path):
    alone = tmp_path / "write_gate.py"
    shutil.copy(SCRIPTS / "write_gate.py", alone)
    plan = str(checkout / ".claude" / "play" / "A" / PLAN)
    done = run_gate(as_bytes(call("Write", plan, str(checkout))), alone)
    assert done.returncode == STOP
    assert said(done).startswith(f"{REFUSED} {BROKEN}: it failed: ModuleNotFoundError")
    assert said(done).endswith(WHEN_BROKEN)


def test_what_went_wrong_goes_into_a_reason_on_one_line_and_cut_short():
    odd = "a\nb\x1b" + chr(0x2028) + "c " + "x" * 300
    assert write_gate.broken(odd) == write_gate.Stopped(
        f"{BROKEN}: a b c " + "x" * (write_gate.SHOWN - len("a b c ")), WHEN_BROKEN)


def test_every_kind_of_refusal_has_a_step_of_its_own_and_only_one_names_the_plan_file():
    steps = {kind: step_after(kind) for kind in Kind}
    assert len(set(steps.values())) == len(Kind)
    assert [kind for kind, step in steps.items() if REQUESTS in step] == [Kind.ANOTHER_FILE]
    assert REQUESTS not in WHEN_BROKEN and BROKEN in WHEN_BROKEN
    assert all(BROKEN not in step for step in steps.values())


def test_a_byte_order_mark_before_the_call_is_not_part_of_it(checkout):
    mark = b"\xef\xbb\xbf"
    plan = str(checkout / ".claude" / "play" / "A" / PLAN)
    settings = str(checkout / ".claude" / "settings.local.json")
    gate = gate_of(checkout)
    assert run_gate(mark + as_bytes(call("Write", plan, str(checkout))), gate).returncode == 0
    assert run_gate(mark + as_bytes(call("Write", settings, str(checkout))), gate).returncode == STOP


def test_the_gate_decides_as_the_rules_do(tmp_path, monkeypatch):
    colony = tmp_path / ".claude" / "play" / "A"
    colony.mkdir(parents=True)
    (colony / PLAN).write_text("# plan\n", encoding="utf-8", newline="")
    rule = write_rules.refusal
    monkeypatch.setattr(write_rules, "refusal",
                        lambda path, cwd: rule(path, cwd, tmp_path / ".claude" / "play"))
    assert write_gate.decide(json.dumps(call("Write", str(colony / PLAN), str(tmp_path)))) is None
    stopped = write_gate.decide(json.dumps(call("Edit", str(colony / "usage.json"), str(tmp_path))))
    assert stopped == write_gate.Stopped(rule(str(colony / "usage.json"), None).reason,
                                         step_after(Kind.ANOTHER_FILE))


def test_what_the_hook_loads_reads_as_the_oldest_python_it_is_said_to_run_on():
    # The hook is started by the name `python`, which need not be the Python of the MCP
    # server. SKILL.md says 3.13 or later; this holds the syntax to it, not the library.
    for name in LOADED:
        ast.parse((SCRIPTS / name).read_text(encoding="utf-8"), filename=name,
                  feature_version=(3, 13))
    assert "Python 3.13 以降が起動できる" in SKILL.read_text(encoding="utf-8")


def test_the_words_a_reason_is_read_by_are_the_ones_the_skill_and_the_definition_name():
    skill = SKILL.read_text(encoding="utf-8")
    definition = DEFINITION.read_text(encoding="utf-8")
    for words in OPENINGS:
        assert f"| `{words}` |" in skill
    assert f"最初の `{REFUSED}` に続く語" in skill
    assert f"`{REFUSED}`" in definition
    # The line a cycle returns when it could not write the plan file, by which the parent
    # stops the run.
    assert "方針ファイルを書けなかった／" in definition
    assert "「方針ファイルを書けなかった」で始まる" in skill
    # The section the gate sends a cycle to is one the plan file has.
    assert f"## {REQUESTS}" in PLAN_TEMPLATE.read_text(encoding="utf-8").splitlines()


def test_the_words_a_reason_is_read_by_are_in_the_head_a_cycle_hands_on():
    # A cycle that could not write its plan file returns the head of the reason, and
    # the parent reads the words after the first `refused:` in it. The words, and a
    # path of the longest length shown, have to lie within that head.
    definition = DEFINITION.read_text(encoding="utf-8")
    assert definition.count(f"頭から {HANDED_ON} 字") == 2
    for words in OPENINGS:
        assert len(f"{HOOK_PREFIX}{REFUSED} {words}: ") + write_rules.SHOWN + len('"..."') <= HANDED_ON
