"""Tests of reading a subagent definition's frontmatter. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import pytest

from cycle_agent import CYCLE_AGENT, AgentUnreadable, FrontmatterUnreadable, agent_model, frontmatter

DEFINITION = """\
---
name: rimworld-cycle
description: >-
  RimWorld を
  1 サイクル回す
skills:
  - rimworld-play
hooks:
  PreToolUse:
    # A comment line is passed over, inside a nested block too.

    - matcher: "Write"
      hooks:
        - type: command
# A comment line is passed over.
model: sonnet
tools:
  - Read
  - Write
---

# 本文
"""


def test_frontmatter_reads_lists_strings_and_block_scalars():
    fields = frontmatter(DEFINITION)
    assert fields == {"name": "rimworld-cycle", "description": "RimWorld を 1 サイクル回す",
                      "skills": ["rimworld-play"], "model": "sonnet", "tools": ["Read", "Write"],
                      "hooks": '  PreToolUse:\n    - matcher: "Write"\n      hooks:\n'
                               "        - type: command"}


@pytest.mark.parametrize("text, hooks", [
    ("---\nhooks:\n---\n", ""),
    ("---\nhooks:\nname: x\n---\n", ""),
    ("---\nhooks: off\n---\n", "off"),
    ("---\nhooks: []\n---\n", []),
    ("---\nhooks:\n  - a  \n  - b\n---\n", "  - a\n  - b"),
], ids=["nothing under it", "the next key under it", "a value", "an empty list", "a list"])
def test_the_hooks_field_is_kept_as_what_is_under_it(text, hooks):
    assert frontmatter(text)["hooks"] == hooks


@pytest.mark.parametrize("text, reason", [
    ("# no frontmatter\n", "does not open"),
    ("---\nname: x\n", "not closed"),
    ("---\nname: x\nname: y\n---\n", "given twice"),
    ("---\nname: x\nstray line\n---\n", "not in a form"),
    ("---\n  - stray\n---\n", "not in a form"),
    # A nested block is kept for the hooks field only, and its lines are indented.
    ("---\nmcpServers:\n  rimworld:\n    command: x\n---\n", "line 3: the frontmatter is not"),
    ("---\nhooks:\n  PreToolUse:\nstray line\n---\n", "line 4: the frontmatter is not"),
    ("---\nhooks:\n\tPreToolUse:\n---\n", "line 3: the frontmatter is not"),
    ("---\nhooks:\n  a:\nhooks:\n  b:\n---\n", "given twice"),
    # The one who runs the definition may end the frontmatter at a '---' this would read past.
    ("---\nname: x --- y\nhooks:\n  a:\n---\n", "line 2: '---' inside a line"),
    ("---\nname: x\n# ---- a rule\nhooks:\n  a:\n---\n", "line 3: '---' inside a line"),
    # Or may read on past a line of hyphens this would end at.
    ("---\nname: x\n ---\nhooks:\n  a:\n---\n", "line 3: '---' inside a line"),
    ("---\nname: x\n--- \nhooks:\n  a:\n---\n", "line 3: '---' inside a line"),
    (" ---\nname: x\n---\n", "does not open"),
])
def test_a_frontmatter_it_cannot_read_is_refused(text, reason):
    with pytest.raises(FrontmatterUnreadable, match=reason):
        frontmatter(text)


NO_BREAK_SPACE, WIDE_SPACE, LINE_SEPARATOR, NEXT_LINE = chr(0xA0), chr(0x3000), chr(0x2028), chr(0x85)


@pytest.mark.parametrize("text, reason", [
    # A blank Python strips and YAML keeps as part of the value.
    (f"---\nmodel: sonnet{NO_BREAK_SPACE}\n---\n", "line 2: .*U\\+00A0"),
    (f"---\nhooks:\n  a: b{WIDE_SPACE}\n---\n", "line 3: .*U\\+3000"),
    # An end of a line to Python and not to YAML: the key below is a comment's tail there.
    (f"---\nname: x\n#{LINE_SEPARATOR}hooks:\n---\n", "line 3: .*U\\+2028"),
    (f"---\nname: x\n#{NEXT_LINE}hooks:\n---\n", "line 3: .*U\\+0085"),
    ("---\nname: x\n#\x0bhooks:\n---\n", "line 3: .*U\\+000B"),
    ("---\nname: x\n#\x1chooks:\n---\n", "line 3: .*U\\+001C"),
    (f"---\nname: x{chr(0xFEFF)}\n---\n", "line 2: .*U\\+FEFF"),
])
def test_a_character_python_and_yaml_read_apart_is_refused(text, reason):
    with pytest.raises(FrontmatterUnreadable, match=reason):
        frontmatter(text)


def test_a_line_ends_where_yaml_ends_one():
    assert frontmatter("---\r\nname: x\r\nmodel: y\r---\n") == {"name": "x", "model": "y"}


NOT_READ = ['"sonnet', "'sonnet", '"', "'a' b", "'it's'", "&anchor x", "*alias", "!!str x",
            "{a: b}", "|+", ">2", "%TAG", "@x", "`x`"]
# Outside brackets only: inside them a comma parts the items, and a bracket opens no list.
NOT_READ_ALONE = ["'a', \"b\"", "[a, b"]


@pytest.mark.parametrize("text", [place.format(value) for place, values in (
    ("model: {}", NOT_READ + NOT_READ_ALONE),
    ("tools:\n  - {}", NOT_READ + NOT_READ_ALONE),
    ("tools: [a, {}]", NOT_READ),
) for value in values])
def test_a_value_yaml_would_read_another_way_is_refused(text):
    with pytest.raises(FrontmatterUnreadable, match="line [23]: the frontmatter is not"):
        frontmatter(f"---\n{text}\n---\n")


def test_an_item_with_nothing_in_it_is_an_empty_one():
    assert frontmatter("---\ntools:\n  - \n  - a\n---\n") == {"tools": ["", "a"]}


def test_a_value_in_quotes_that_close_on_its_line_is_read():
    assert frontmatter("---\nmodel: \"sonnet\"\ntools: ['a', \"b\"]\nskills:\n  - 'c'\n---\n") == {
        "model": '"sonnet"', "tools": ["'a'", '"b"'], "skills": ["'c'"]}


def test_the_model_a_definition_runs_on_is_read_from_it(tmp_path):
    (tmp_path / "cycle.md").write_text(DEFINITION, encoding="utf-8", newline="")
    assert agent_model("cycle", tmp_path) == "sonnet"


@pytest.mark.parametrize("text, reason", [
    (None, "cannot read the definition"),
    ("---\nname: x\n", "cannot read the definition"),
    ("---\nname: x\n---\n", "names no model"),
])
def test_a_definition_that_does_not_tell_its_model_is_refused(tmp_path, text, reason):
    if text is not None:
        (tmp_path / "cycle.md").write_text(text, encoding="utf-8", newline="")
    with pytest.raises(AgentUnreadable, match=reason):
        agent_model("cycle", tmp_path)


def test_the_cycle_definition_is_there_and_names_a_model():
    assert agent_model(CYCLE_AGENT)
