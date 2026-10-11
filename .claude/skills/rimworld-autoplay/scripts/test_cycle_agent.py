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
                      "skills": ["rimworld-play"], "model": "sonnet", "tools": ["Read", "Write"]}


@pytest.mark.parametrize("text, reason", [
    ("# no frontmatter\n", "does not open"),
    ("---\nname: x\n", "not closed"),
    ("---\nname: x\nname: y\n---\n", "given twice"),
    ("---\nname: x\nstray line\n---\n", "not in a form"),
    ("---\n  - stray\n---\n", "not in a form"),
])
def test_a_frontmatter_it_cannot_read_is_refused(text, reason):
    with pytest.raises(FrontmatterUnreadable, match=reason):
        frontmatter(text)


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
