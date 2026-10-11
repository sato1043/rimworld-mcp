"""Tests of the check that the watcher's letter table names every Core LetterDef. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import pytest

from check_letter_table import Untrusted, check, core_letter_defs

# Shaped like the game's Data/Core/Defs/Misc/LetterDefs: an abstract parent without a
# defName, children naming it, and a def other defs name as their parent.
CHOICE = """\
<?xml version="1.0" encoding="utf-8"?>
<Defs>
  <LetterDef Abstract="True" Name="CustomChoiceLetterBase">
    <letterClass>ChoiceLetter</letterClass>
  </LetterDef>
  <LetterDef ParentName="CustomChoiceLetterBase">
    <defName>RansomDemand</defName>
  </LetterDef>
</Defs>
"""
STANDARD = """\
<?xml version="1.0" encoding="utf-8"?>
<Defs>
  <LetterDef Name="ThreatBig">
    <defName>ThreatBig</defName>
  </LetterDef>
  <LetterDef ParentName="ThreatBig">
    <defName>NewQuest_ThreatBig</defName>
  </LetterDef>
</Defs>
"""


@pytest.fixture
def letter_defs(tmp_path):
    (tmp_path / "CustomChoiceLetters.xml").write_text(CHOICE, encoding="utf-8", newline="")
    (tmp_path / "StandardLetters.xml").write_text(STANDARD, encoding="utf-8", newline="")
    return tmp_path


def test_reads_every_letter_def_that_is_not_abstract(letter_defs):
    assert core_letter_defs(letter_defs) == {"RansomDemand", "ThreatBig", "NewQuest_ThreatBig"}


def test_reads_letter_defs_in_any_directory_below(letter_defs):
    below = letter_defs / "Quests" / "Letters"
    below.mkdir(parents=True)
    (below / "More.xml").write_text("<Defs><LetterDef><defName>Death</defName></LetterDef></Defs>",
                                    encoding="utf-8", newline="")
    assert "Death" in core_letter_defs(letter_defs)


def test_a_missing_directory_cannot_be_trusted(tmp_path):
    with pytest.raises(Untrusted, match="cannot read"):
        core_letter_defs(tmp_path / "missing")


def test_a_directory_without_xml_cannot_be_trusted(tmp_path):
    with pytest.raises(Untrusted, match="no XML"):
        core_letter_defs(tmp_path)


def test_a_file_that_does_not_parse_cannot_be_trusted(letter_defs):
    (letter_defs / "Broken.xml").write_text("<Defs><LetterDef>", encoding="utf-8", newline="")
    with pytest.raises(Untrusted, match="Broken.xml"):
        core_letter_defs(letter_defs)


def test_a_letter_def_without_a_name_cannot_be_trusted(letter_defs):
    (letter_defs / "Nameless.xml").write_text("<Defs><LetterDef><x/></LetterDef></Defs>",
                                              encoding="utf-8", newline="")
    with pytest.raises(Untrusted, match="no defName"):
        core_letter_defs(letter_defs)


def test_files_without_letter_defs_cannot_be_trusted(tmp_path):
    (tmp_path / "Other.xml").write_text("<Defs><ThingDef><defName>A</defName></ThingDef></Defs>",
                                        encoding="utf-8", newline="")
    with pytest.raises(Untrusted, match="no LetterDef"):
        core_letter_defs(tmp_path)


def test_the_same_names_have_no_problems():
    assert check({"ThreatBig", "Death"}, {"ThreatBig", "Death"}) == []


def test_a_core_name_missing_from_the_table_is_named():
    assert check({"ThreatBig"}, {"ThreatBig", "Death"}) == [
        "the table does not name the Core LetterDef 'Death'"]


def test_a_table_name_core_does_not_have_is_named():
    assert check({"ThreatBig", "Threatbig"}, {"ThreatBig"}) == [
        "the table names 'Threatbig', which is not a Core LetterDef"]
