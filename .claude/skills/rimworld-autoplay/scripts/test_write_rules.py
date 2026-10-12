"""Tests of which file a cycle may write. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import inspect
import os
import pathlib
import subprocess

import pytest

import write_rules
from play_files import PLAN, PLAY_ROOT, REPO_ROOT
from write_rules import NOT_A_PLAN_FILE, NOT_THERE, UNJUDGED, Kind, refusal, same_name, shown

COLONIES = ("A", "カルバーソン休憩所")


@pytest.fixture
def checkout(tmp_path):
    """A checkout with two colonies and their plan files, laid out as the main one is. A
    `k` is in its path on purpose (see the test of the Kelvin sign)."""
    root = tmp_path / "checkout"
    for name in COLONIES:
        colony = root / ".claude" / "play" / name
        colony.mkdir(parents=True)
        (colony / PLAN).write_text("# plan\n", encoding="utf-8", newline="")
    return root


def play(root: pathlib.Path) -> pathlib.Path:
    return root / ".claude" / "play"


def link_directory(link: pathlib.Path, target: pathlib.Path) -> None:
    """Make a directory link: a junction on Windows, which needs no privilege there."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


PLAN_FILES = [
    ".claude/play/A/plan.md",
    ".claude/play/A/../A/plan.md",
    ".claude/play/A/./plan.md",
    # A name outside ASCII.
    ".claude/play/カルバーソン休憩所/plan.md",
]

# The ways a session is run that the problem this guards against names (settings and hooks
# in and out of the checkout, git's own configuration, compiled scripts, the definition and
# the skills), the state next to the plan file, and paths that only look like a plan file.
OTHER_FILES = [
    ".claude/play/A/cycle.json",
    ".claude/play/A/watch.json",
    ".claude/play/A/usage.json",
    ".claude/play/A/plan.md.before-20261004T122537Z",
    ".claude/play/A/plan.tmp",
    ".claude/play/A/sub/plan.md",
    ".claude/play/A/plan.md/plan.md",
    # Straight under the colonies' directory, where no colony is.
    ".claude/play/plan.md",
    ".claude/play/.hidden/plan.md",
    ".claude/play/CON/plan.md",
    ".claude/plan.md",
    ".claude/rate-limits.jsonl",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/agents/rimworld-cycle.md",
    ".claude/agents/another.md",
    ".claude/skills/rimworld-autoplay/SKILL.md",
    ".claude/skills/rimworld-autoplay/scripts/write_gate.py",
    ".claude/skills/rimworld-autoplay/scripts/__pycache__/write_gate.cpython-314.pyc",
    ".git/config",
    ".git/hooks/pre-commit",
    "mcp_server/main.py",
    "mcp_server/uv.lock",
    "plan.md",
    ".claude/play/A/../../settings.local.json",
    ".claude/play/A/../plan.md",
    ".claude/play/A/plan.md/../../../settings.local.json",
    # Spellings Windows opens as the plan file itself: refused by how they are spelled.
    ".claude/play/A/plan.md.",
    ".claude/play/A/plan.md ",
    ".claude/play/A/plan.md::$DATA",
    ".claude/play/A/plan.md:stream",
]


def both_ways(checkout: pathlib.Path, name: str) -> list[write_rules.Refusal | None]:
    """What the rule says of a path of the checkout, given in full and from the checkout."""
    return [refusal(str(checkout / name), str(checkout), play(checkout)),
            refusal(name, str(checkout), play(checkout))]


@pytest.mark.parametrize("name", PLAN_FILES)
def test_a_plan_file_is_let_through(checkout, name):
    assert both_ways(checkout, name) == [None, None]


@pytest.mark.parametrize("name", OTHER_FILES)
def test_any_other_file_is_refused(checkout, name):
    for refused in both_ways(checkout, name):
        assert refused.kind is Kind.ANOTHER_FILE
        assert refused.reason.startswith(f"{NOT_A_PLAN_FILE}: ")


@pytest.mark.parametrize("name", [".claude/play/B/plan.md", ".claude/play/新しい名/plan.md"])
def test_a_plan_file_that_is_not_there_is_not_made(checkout, name):
    for refused in both_ways(checkout, name):
        assert refused.kind is Kind.NO_PLAN_FILE
        assert refused.reason.startswith(f"{NOT_THERE}: ")
    assert not (checkout / name).parent.exists()


def test_a_directory_named_as_the_plan_file_is_not_one(checkout):
    (play(checkout) / "C" / PLAN).mkdir(parents=True)
    assert both_ways(checkout, ".claude/play/C/plan.md")[0].kind is Kind.NO_PLAN_FILE


def test_a_file_outside_the_checkout_is_refused(checkout, tmp_path):
    elsewhere = tmp_path / "elsewhere" / ".claude" / "play" / "A"
    elsewhere.mkdir(parents=True)
    (elsewhere / PLAN).write_text("# plan\n", encoding="utf-8", newline="")
    for path in (pathlib.Path.home() / ".claude" / "settings.json", elsewhere / PLAN):
        assert refusal(str(path), str(checkout), play(checkout)).kind is Kind.ANOTHER_FILE


def test_a_relative_path_is_taken_from_the_directory_of_the_call(checkout, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    there = refusal(".claude/play/A/plan.md", str(elsewhere), play(checkout))
    assert there.kind is Kind.ANOTHER_FILE
    for cwd in (None, "", "checkout"):
        unknown = refusal(".claude/play/A/plan.md", cwd, play(checkout))
        assert unknown.kind is Kind.UNREADABLE
        assert unknown.reason.startswith(f"{UNJUDGED}: ") and "not known" in unknown.reason
    if os.name == "nt":
        # A drive with no place on it, taken from a directory of another drive, would be
        # taken from wherever the hook runs.
        other = "D:" if checkout.drive.upper() != "D:" else "C:"
        adrift = refusal(f"{other}plan.md", str(checkout), play(checkout))
        assert adrift.kind is Kind.UNREADABLE
        assert adrift.reason.startswith(f"{UNJUDGED}: ") and "no place on it" in adrift.reason


@pytest.mark.parametrize("path", [None, "", 7, ["a"], "a\0b"], ids=repr)
def test_a_path_that_cannot_be_read_is_refused(checkout, path):
    refused = refusal(path, str(checkout), play(checkout))
    assert refused == write_rules.Refusal(f"{UNJUDGED}: the tool call names none this can read",
                                          Kind.UNREADABLE)


def test_the_case_of_a_name_is_folded_on_windows_and_nowhere_else(checkout):
    shouted = refusal(str(play(checkout) / "A" / "PLAN.MD"), str(checkout), play(checkout))
    assert same_name("PLAN.MD", PLAN) == (os.name == "nt")
    if os.name == "nt":
        # The same file there, where names differ in case only.
        assert shouted is None
    else:
        assert shouted.kind is Kind.ANOTHER_FILE


def test_a_letter_that_only_folds_to_one_of_the_path_does_not_lead_to_another_tree(checkout):
    # U+212A, the Kelvin sign, is `k` once lowered, which is how Windows paths are compared
    # here; to the file system it is another name. The tree it names is not there, and
    # must not be made by letting the write through.
    kelvin = str(checkout).replace("k", chr(0x212A), 1)
    assert kelvin != str(checkout)
    refused = refusal(str(pathlib.Path(kelvin) / ".claude" / "play" / "A" / PLAN), str(checkout),
                      play(checkout))
    assert refused.kind is (Kind.NO_PLAN_FILE if os.name == "nt" else Kind.ANOTHER_FILE)
    assert not pathlib.Path(kelvin).exists()


def test_a_link_leading_out_of_the_colonies_is_refused(checkout):
    link = play(checkout) / "J"
    link_directory(link, checkout / ".claude")
    (checkout / ".claude" / PLAN).write_text("# not a plan\n", encoding="utf-8", newline="")
    assert refusal(str(link / PLAN), str(checkout), play(checkout)).kind is Kind.ANOTHER_FILE


def test_a_link_leading_to_a_colony_is_judged_as_the_plan_file_it_is(checkout):
    link = checkout / "elsewhere"
    link_directory(link, play(checkout) / "A")
    assert refusal(str(link / PLAN), str(checkout), play(checkout)) is None
    assert refusal(str(link / "cycle.json"), str(checkout),
                   play(checkout)).kind is Kind.ANOTHER_FILE


def test_a_file_named_as_the_plan_file_that_leads_to_another_file_is_refused(checkout, monkeypatch):
    # A link to a file, which takes a privilege to make on Windows: the file system's
    # answer is stood in for. The spelling is the plan file's, and where it leads is not.
    plan, state = play(checkout) / "A" / PLAN, play(checkout) / "A" / "usage.json"
    state.write_text("{}", encoding="utf-8", newline="")
    resolve = pathlib.Path.resolve
    monkeypatch.setattr(pathlib.Path, "resolve", lambda path, *args, **kwargs: (
        state if path == plan else resolve(path, *args, **kwargs)))
    assert refusal(str(plan), str(checkout), play(checkout)).kind is Kind.ANOTHER_FILE


def test_another_machine_is_not_asked_where_a_path_leads(checkout, monkeypatch):
    asked = []
    resolve = pathlib.Path.resolve

    def recorded(path, *args, **kwargs):
        asked.append(str(path))
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "resolve", recorded)
    assert refusal(str(play(checkout) / "A" / PLAN), str(checkout), play(checkout)) is None
    # The recorder sees what the rule asks: a plan file is asked about, with the root.
    assert len(asked) == 2
    del asked[:]
    for path in (r"\\host.invalid\share\.claude\play\A\plan.md", "//host.invalid/share/plan.md",
                 r"\\?\C:\Windows\plan.md", r"\\.\pipe\plan.md"):
        refused = refusal(path, str(checkout), play(checkout))
        assert refused.kind is Kind.ANOTHER_FILE
        # A relative path taken from a share is on that share.
        assert refusal("plan.md", path, play(checkout)) is not None
    # Elsewhere than on Windows the one with slashes is a path of this machine like any
    # other, and is asked about.
    assert (asked == []) == (os.name == "nt")


def test_a_path_goes_into_a_reason_in_quotes_on_one_line_and_cut_short(checkout):
    assert shown("a b") == '"a b"'
    assert shown("a\nb\r\x1b[0m\u2028c") == '"a\\nb\\r\\x1b[0m\\u2028c"'
    assert shown("x" * 300) == '"' + "x" * write_rules.SHOWN + '..."'
    odd = ".claude/play/A/x\nrefused: the write gate is broken"
    for refused in both_ways(checkout, odd):
        assert "\n" not in refused.reason
        # The words a reason is read by come first, and the path's own come after them.
        assert refused.reason.startswith(f'{NOT_A_PLAN_FILE}: "')
        assert 'x\\nrefused: the write gate is broken". ' in refused.reason


def test_the_colonies_are_looked_for_where_the_scripts_are():
    assert inspect.signature(refusal).parameters["play_root"].default == PLAY_ROOT
    assert refusal(str(PLAY_ROOT / "A" / "cycle.json"), str(REPO_ROOT)).kind is Kind.ANOTHER_FILE


def files_of_this_checkout() -> list[pathlib.Path]:
    """Every tracked file, and every file under .claude/ whether tracked or not."""
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True,
                             check=True, timeout=60, stdin=subprocess.DEVNULL).stdout
    files = {REPO_ROOT / name for name in tracked.decode("utf-8").split("\0") if name}
    files |= {path for path in (REPO_ROOT / ".claude").rglob("*") if path.is_file()}
    return sorted(files)


def test_no_file_of_this_checkout_but_a_plan_file_is_let_through():
    files = files_of_this_checkout()
    # The files this guards have to be among those asked about, or nothing is tested.
    for guarded in (REPO_ROOT / ".claude" / "agents" / "rimworld-cycle.md",
                    pathlib.Path(write_rules.__file__).resolve(),
                    REPO_ROOT / "mcp_server" / "main.py"):
        assert guarded in files
    let_through = [path for path in files if refusal(str(path), str(REPO_ROOT)) is None]
    assert [path for path in let_through
            if path.name != PLAN or path.parent.parent != PLAY_ROOT] == []
