"""The tools as an MCP client calls them, against a stand-in for the game's bridge.

Each test runs the real server in memory and swaps only the HTTP transport, so the
tool arguments, the output schema and the client's error handling are all exercised.
"""

import asyncio
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ToolAnnotations

import main

PAWN = {"id": "Human1", "name": "Isla", "position": {"x": 1, "z": 2}, "health": 1.0,
        "drafted": False, "downed": False, "job": "resting", "jobTarget": "none",
        "skills": {"Shooting": 8}, "passions": {}}

DEER = [
    {"id": "Deer1", "name": "deer", "race": "Deer", "position": {"x": 1, "z": 1},
     "health": 1.0, "faction": "wild", "tame": False, "job": "wandering"},
    {"id": "Deer2", "name": "deer", "race": "Deer", "position": {"x": 2, "z": 2},
     "health": 1.0, "faction": "wild", "tame": False, "job": "wandering"},
]

TRAINING = [{"id": "Dog1", "name": "dog", "race": "Dog", "position": {"x": 1, "z": 1},
             "health": 1.0, "bondedTo": [],
             "training": [{"defName": "Guard", "label": "guard",
                           "learned": False, "wanted": True}]}]

BRIDGE = {
    "/state": {"tick": 1, "speed": "Normal"},
    "/alerts": {"lowFood": False},
    "/threats": {"hostiles": 0},
    "/colony": {"colonists": 1},
    "/weather": {"weather": "Clear"},
    "/power": {"net": 0},
    "/messages": [],
    "/pawns": [PAWN],
    "/animals": DEER,
    "/animals/training": TRAINING,
}

# Written out rather than taken from main.OVERVIEW_READS, so that dropping a section
# there fails here.
SECTIONS = {"state", "alerts", "threats", "colony", "weather", "power", "messages",
            "colonists"}


def bridge(failing: dict[str, str] | None = None, delay: float = 0.0,
           answers: dict[str, httpx.Response] | None = None,
           raising: dict[str, Exception] | None = None):
    """A transport answering like the bridge. Paths in `failing` answer 500 with the
    given reason, paths in `answers` answer with that response, and paths in
    `raising` raise that exception. Returns the transport and a record of the most
    requests in flight."""
    failing, answers, raising = failing or {}, answers or {}, raising or {}
    seen = {"in_flight": 0, "most_in_flight": 0}

    async def handle(request: httpx.Request) -> httpx.Response:
        seen["in_flight"] += 1
        seen["most_in_flight"] = max(seen["most_in_flight"], seen["in_flight"])
        try:
            await asyncio.sleep(delay)
            path = request.url.path
            if path in raising:
                raise raising[path]
            if path in answers:
                return answers[path]
            if path in failing:
                return httpx.Response(500, json={"error": failing[path]})
            return httpx.Response(200, json=BRIDGE[path])
        finally:
            seen["in_flight"] -= 1

    return httpx.MockTransport(handle), seen


@pytest.fixture
def use_bridge(monkeypatch):
    """Put a transport under the server's client, keeping everything else it sets up."""
    def install(transport: httpx.MockTransport) -> None:
        real = main._new_client
        monkeypatch.setattr(main, "_new_client", lambda: real(transport=transport))
    return install


def call_result(tool: str, arguments: dict | None = None, server=None):
    async def run():
        async with create_connected_server_and_client_session(server or main.mcp) as session:
            return await session.call_tool(tool, arguments or {})
    return asyncio.run(run())


def call(tool: str, arguments: dict | None = None):
    result = call_result(tool, arguments)
    assert not result.isError, result.content
    # The tools send text only, as one block of JSON.
    assert result.structuredContent is None, tool
    assert len(result.content) == 1, tool
    return json.loads(result.content[0].text)


def list_tools(server=None):
    async def run():
        async with create_connected_server_and_client_session(server or main.mcp) as session:
            return (await session.list_tools()).tools
    return {t.name: t for t in asyncio.run(run())}


# ── Overview ──────────────────────────────────────────────────────────────────

def test_overview_returns_every_section_with_colonists_shaped(use_bridge):
    transport, _ = bridge()
    use_bridge(transport)
    overview = call("get_colony_overview")
    assert set(overview) == SECTIONS
    assert overview["state"] == BRIDGE["/state"]
    assert overview["colonists"] == [{"id": "Human1", "name": "Isla", "health": 1.0,
                                      "drafted": False, "downed": False,
                                      "job": "resting"}]


def test_overview_sends_every_read_at_once(use_bridge):
    transport, seen = bridge(delay=0.05)
    use_bridge(transport)
    call("get_colony_overview")
    assert seen["most_in_flight"] == len(SECTIONS)


@pytest.mark.parametrize("path, section", [("/threats", "threats"),
                                           ("/pawns", "colonists")])
def test_overview_keeps_the_other_sections_when_one_read_fails(use_bridge, path,
                                                               section):
    transport, _ = bridge(failing={path: "Self referencing loop detected"})
    use_bridge(transport)
    overview = call("get_colony_overview")
    assert "Self referencing loop detected" in overview[section]["error"]
    assert "500" in overview[section]["error"]
    assert overview["alerts"] == BRIDGE["/alerts"]
    assert set(overview) == SECTIONS


def test_overview_folds_a_failure_even_without_the_clients_error_hook(use_bridge,
                                                                      monkeypatch):
    # upstream's client does not raise on an error status, so the read must. Only the
    # status reaches the section then: the bridge's reason is carried by this fork's
    # client hook, which the test above exercises.
    monkeypatch.setattr(main, "_raise_with_reason", _no_hook)
    transport, _ = bridge(failing={"/power": "boom"})
    use_bridge(transport)
    overview = call("get_colony_overview")
    assert "500" in overview["power"]["error"]
    assert overview["state"] == BRIDGE["/state"]


async def _no_hook(response: httpx.Response) -> None:
    return None


def test_overview_folds_a_body_that_is_not_json(use_bridge):
    transport, _ = bridge(answers={"/weather": httpx.Response(200, text="<html>")})
    use_bridge(transport)
    overview = call("get_colony_overview")
    assert overview["weather"]["error"]
    assert overview["state"] == BRIDGE["/state"]


def test_overview_folds_colonists_of_an_unexpected_shape(use_bridge):
    transport, _ = bridge(answers={"/pawns": httpx.Response(200, json=[{"id": "x"}])})
    use_bridge(transport)
    overview = call("get_colony_overview")
    assert "unexpected shape" in overview["colonists"]["error"]
    assert overview["state"] == BRIDGE["/state"]


def test_overview_names_the_failure_when_it_has_no_message(use_bridge):
    transport, _ = bridge(raising={"/colony": httpx.ReadTimeout("")})
    use_bridge(transport)
    overview = call("get_colony_overview")
    assert overview["colony"] == {"error": "ReadTimeout"}


def test_overview_fails_when_no_section_can_be_read(use_bridge):
    transport, _ = bridge(failing={p: "not signed in" for p in main.OVERVIEW_READS.values()})
    use_bridge(transport)
    result = call_result("get_colony_overview")
    assert result.isError
    assert "not signed in" in result.content[0].text


def test_overview_lets_failures_other_than_a_read_propagate():
    transport, _ = bridge(raising={"/alerts": RuntimeError("a bug, not a read")})

    async def run():
        async with main._new_client(transport=transport) as client:
            return await main.collect_overview(client)

    with pytest.raises(RuntimeError, match="a bug, not a read"):
        asyncio.run(run())


# ── Output form ───────────────────────────────────────────────────────────────

def compact(text: str) -> str:
    """The text written again as JSON without indentation or escaped non-ASCII."""
    return json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))


def test_a_dict_answers_as_one_block_of_compact_json(use_bridge):
    weather = {"weather": "晴れ", "temperature": 21.5, "season": {"label": "夏"}}
    transport, _ = bridge(answers={"/weather": httpx.Response(200, json=weather)})
    use_bridge(transport)
    result = call_result("get_weather")
    assert len(result.content) == 1
    text = result.content[0].text
    assert text == compact(text)
    assert json.loads(text) == weather


def test_a_list_answers_as_one_json_array(use_bridge):
    transport, _ = bridge()
    use_bridge(transport)
    result = call_result("get_pawns")
    assert len(result.content) == 1
    text = result.content[0].text
    assert text == compact(text)
    assert json.loads(text) == [PAWN]


def test_an_empty_list_answers_as_an_empty_array(use_bridge):
    transport, _ = bridge()
    use_bridge(transport)
    assert [block.text for block in call_result("get_messages").content] == ["[]"]


def test_no_tool_lists_an_output_schema():
    # Without one FastMCP sends no structured content; call() checks what is sent.
    tools = list_tools()
    # get_animals returns a union, for which FastMCP would make a schema by default.
    assert "get_animals" in tools
    assert [name for name, t in tools.items() if t.outputSchema is not None] == []


def test_every_registered_tool_replies_through_the_wrapper():
    # Tools handed to the constructor or the tool manager would skip add_tool().
    wrapper = main.RimWorldMCP._replying_in_compact_json(lambda: None).__code__
    tools = main.mcp._tool_manager.list_tools()
    assert len(tools) == len(list_tools())
    assert [t.name for t in tools if t.fn.__code__ is not wrapper] == []


def test_wrapping_leaves_what_each_tool_lists_but_its_output_schema():
    plain = FastMCP("plain")
    for tool in main.mcp._tool_manager.list_tools():
        plain.add_tool(tool.fn.__wrapped__, name=tool.name, structured_output=False)
    wrapped, unwrapped = list_tools(), list_tools(plain)
    assert wrapped.keys() == unwrapped.keys()
    for name, tool in wrapped.items():
        assert tool.description == unwrapped[name].description, name
        assert tool.inputSchema == unwrapped[name].inputSchema, name


def test_a_tool_added_later_answers_the_same_way():
    server = main.RimWorldMCP("later")

    @server.tool(annotations=main.READS_GAME)
    async def mapping() -> dict | list:
        return {"a": [1, "ラベル"]}

    @server.tool(annotations=main.READS_GAME)
    def items() -> list:
        return [{"a": 1}, "x"]

    @server.tool(annotations=main.READS_GAME)
    async def label() -> str:
        return "晴れ"

    assert list_tools(server)["mapping"].outputSchema is None
    for name, text in (("mapping", '{"a":[1,"ラベル"]}'), ("items", '[{"a":1},"x"]'),
                       ("label", '"晴れ"')):
        result = call_result(name, server=server)
        assert result.structuredContent is None, name
        assert [block.text for block in result.content] == [text]


def test_a_value_json_cannot_hold_fails_the_call_naming_its_type():
    server = main.RimWorldMCP("later")

    @server.tool(annotations=main.READS_GAME)
    async def seasons() -> dict:
        return {"labels": {"夏"}}

    result = call_result("seasons", server=server)
    assert result.isError
    assert "seasons" in result.content[0].text
    assert "type set" in result.content[0].text


def test_nan_is_written_as_fastmcp_wrote_it():
    server = main.RimWorldMCP("later")

    @server.tool(annotations=main.READS_GAME)
    async def reading() -> dict:
        return {"value": float("nan")}

    result = call_result("reading", server=server)
    assert [block.text for block in result.content] == ['{"value":NaN}']


def test_asking_for_structured_output_is_refused():
    server = main.RimWorldMCP("later")

    async def mapping() -> dict:
        return {}

    with pytest.raises(ValueError, match="structured_output"):
        server.add_tool(mapping, structured_output=True, annotations=main.READS_GAME)
    # Given by position, last after name, title, description, annotations, icons, meta.
    with pytest.raises(ValueError, match="structured_output"):
        server.add_tool(mapping, "n", None, None, main.READS_GAME, None, None, True)
    assert list(list_tools(server)) == []
    # Everything else reaches FastMCP as given, by position or by name.
    server.add_tool(mapping, "renamed", structured_output=False,
                    annotations=main.READS_GAME)
    assert list(list_tools(server)) == ["renamed"]


def test_a_tool_without_annotations_is_refused():
    server = main.RimWorldMCP("later")

    async def mapping() -> dict:
        return {}

    every_hint = "readOnlyHint, destructiveHint, idempotentHint, openWorldHint"
    with pytest.raises(ValueError, match=f"^mapping: .*unset: {every_hint}"):
        server.tool()(mapping)
    with pytest.raises(ValueError, match=f"^renamed: .*unset: {every_hint}"):
        server.add_tool(mapping, "renamed")
    with pytest.raises(ValueError, match=f"unset: {every_hint}"):
        server.add_tool(mapping, annotations=ToolAnnotations())
    with pytest.raises(ValueError, match=r"\(unset: destructiveHint, idempotentHint\)$"):
        server.add_tool(mapping, annotations=ToolAnnotations(readOnlyHint=True,
                                                            openWorldHint=False))
    assert list(list_tools(server)) == []
    # Given by position, after name, title and description.
    server.add_tool(mapping, "renamed", None, None, main.READS_GAME)
    assert list_tools(server)["renamed"].annotations.readOnlyHint is True


def test_an_sdk_whose_add_tool_changed_is_named_as_the_cause(monkeypatch):
    server = main.RimWorldMCP("later")

    def add_tool(self, fn, name=None, hints=None, structured_output=None):
        pass

    monkeypatch.setattr(main.RimWorldMCP, "_ADD_TOOL", inspect.signature(add_tool))
    with pytest.raises(TypeError, match=r"takes no annotations; "):
        server.add_tool(len, annotations=main.READS_GAME)


# ── Tool surface ──────────────────────────────────────────────────────────────

def test_get_animals_defaults_to_counts_and_takes_race_and_detail(use_bridge):
    transport, _ = bridge()
    use_bridge(transport)
    counts = {"colony": [], "others": [{"race": "Deer", "faction": "wild", "count": 2}]}
    assert call("get_animals") == counts
    assert call("get_animals", {"race": ""}) == counts
    assert [a["id"] for a in call("get_animals", {"race": "Deer"})] == ["Deer1", "Deer2"]
    assert call("get_animals", {"detail": True}) == BRIDGE["/animals"]
    assert call("get_animals", {"race": "Deer", "detail": True}) == DEER


def test_get_animals_fails_on_a_race_that_matches_nothing(use_bridge):
    transport, _ = bridge()
    use_bridge(transport)
    result = call_result("get_animals", {"race": "Muffalo"})
    assert result.isError
    assert "Deer" in result.content[0].text


def test_get_animal_training_lists_pending_and_takes_detail(use_bridge):
    transport, _ = bridge()
    use_bridge(transport)
    assert call("get_animal_training")[0]["pending"] == ["guard"]
    assert call("get_animal_training", {"detail": True}) == TRAINING


def test_new_arguments_are_optional_in_the_schemas():
    tools = list_tools()
    for name, args in (("get_animals", {"race", "detail"}), ("get_buildings", {"detail"}),
                       ("get_animal_training", {"detail"})):
        schema = tools[name].inputSchema
        assert args <= set(schema["properties"]), name
        assert not args & set(schema.get("required", [])), name
    # Text like the other tools' optional arguments, not text-or-null.
    assert tools["get_animals"].inputSchema["properties"]["race"]["type"] == "string"


# ── Events ────────────────────────────────────────────────────────────────────

EVENTS = {"events": [{"tick": 5, "kind": "letter", "type": "ThreatBig", "label": "Raid"}],
          "next": "e724be81.203", "more": True, "gap": False, "reloaded": False}


def events_bridge(answer: httpx.Response | None = None):
    """A transport answering /events, and the path and query of each request."""
    asked = []

    async def handle(request: httpx.Request) -> httpx.Response:
        asked.append((request.url.path, dict(request.url.params)))
        return answer or httpx.Response(200, json=EVENTS)

    return httpx.MockTransport(handle), asked


def test_get_events_passes_since_and_limit_and_returns_the_answer(use_bridge):
    transport, asked = events_bridge()
    use_bridge(transport)
    assert call("get_events", {"since": "e724be81.202", "limit": 5}) == EVENTS
    assert asked == [("/events", {"since": "e724be81.202", "limit": "5"})]


def test_get_events_leaves_since_out_when_not_given(use_bridge):
    # The bridge refuses an empty since, so an omitted one must not be sent at all.
    transport, asked = events_bridge()
    use_bridge(transport)
    call("get_events")
    call("get_events", {"since": ""})
    assert asked == [("/events", {"limit": "30"})] * 2


def test_get_events_fails_with_the_bridges_reason(use_bridge):
    reason = "since is not a cursor returned by this endpoint; leave since out to read the latest"
    transport, _ = events_bridge(httpx.Response(400, json={"error": reason}))
    use_bridge(transport)
    result = call_result("get_events", {"since": "nope"})
    assert result.isError
    assert reason in result.content[0].text


def test_get_events_takes_optional_text():
    schema = list_tools()["get_events"].inputSchema
    assert {"since", "limit"} <= set(schema["properties"])
    assert not {"since", "limit"} & set(schema.get("required", []))
    assert schema["properties"]["since"]["type"] == "string"


# ── Annotations ───────────────────────────────────────────────────────────────

# What each tool declares, written out here rather than read from main.py, so that a
# tool added or changed there without a matching row fails below. The values are
# copied, under the names main.py gives them; the rules for the rows are those beside
# the constants in main.py.
READS_GAME = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
              "openWorldHint": False}
CHANGES_GAME_ONCE = {"readOnlyHint": False, "destructiveHint": True,
                     "idempotentHint": True, "openWorldHint": False}
CHANGES_GAME_EACH_CALL = {"readOnlyHint": False, "destructiveHint": True,
                          "idempotentHint": False, "openWorldHint": False}
ADDS_TO_GAME_EACH_CALL = {"readOnlyHint": False, "destructiveHint": False,
                          "idempotentHint": False, "openWorldHint": False}

READ_TOOLS = [
    "get_game_state", "get_weather", "get_colony_overview", "get_pawns",
    "get_pawn_status", "get_pawn_health", "get_pawn_needs", "get_pawn_mood",
    "get_pawn_inventory", "get_animals", "get_enemies", "get_fertile_cells",
    "get_things", "get_buildings", "get_designations", "get_research", "ping",
    "get_pawn_traits", "get_pawn_relations", "get_pawn_work", "get_pawn_schedule",
    "get_power", "get_rooms", "get_zones", "get_prisoners", "get_colony", "get_threats",
    "get_cell_info", "get_cells_info", "list_areas", "list_zones",
    "get_animal_training", "get_caravans", "get_world_factions", "get_world_sites",
    "get_messages", "get_events", "get_alerts", "get_medical", "get_production",
    "get_pawn_backstory", "get_pawn_capacities", "get_pawn_psycasts", "get_pawn_genes",
    "get_pawn_area", "get_stockpile_contents", "get_corpses", "get_drug_policies",
    "get_room_assignments", "get_mechs", "get_incidents", "get_colony_social",
    "get_apparel", "get_traders", "get_quests", "get_ideology",
]

WRITE_TOOLS = {
    "draft_pawn": CHANGES_GAME_ONCE,
    "move_pawn": CHANGES_GAME_EACH_CALL,
    "attack_target": CHANGES_GAME_EACH_CALL,
    "assign_job": CHANGES_GAME_EACH_CALL,
    "rescue_pawn": CHANGES_GAME_EACH_CALL,
    "hunt_animal": CHANGES_GAME_ONCE,
    "mine_cell": CHANGES_GAME_ONCE,
    "cut_plant": CHANGES_GAME_ONCE,
    "place_blueprint": CHANGES_GAME_EACH_CALL,
    "forbid_thing": CHANGES_GAME_ONCE,
    "set_research": CHANGES_GAME_ONCE,
    "set_pause": CHANGES_GAME_ONCE,
    "set_time_speed": CHANGES_GAME_ONCE,
    "create_allowed_area": ADDS_TO_GAME_EACH_CALL,
    "clear_area": CHANGES_GAME_ONCE,
    "delete_area": CHANGES_GAME_ONCE,
    "delete_zone": CHANGES_GAME_EACH_CALL,
    "add_bill": CHANGES_GAME_EACH_CALL,
    "remove_bill": CHANGES_GAME_ONCE,
    "equip_item": CHANGES_GAME_EACH_CALL,
    "recruit_prisoner": CHANGES_GAME_EACH_CALL,
    "assign_bed": CHANGES_GAME_ONCE,
    "set_allowed_area": CHANGES_GAME_ONCE,
    "set_schedule_hour": CHANGES_GAME_ONCE,
    "set_passion": CHANGES_GAME_ONCE,
    "queue_medical_operation": CHANGES_GAME_EACH_CALL,
    "deconstruct": CHANGES_GAME_ONCE,
    "area_paint": CHANGES_GAME_ONCE,
    "set_zone_plant": CHANGES_GAME_ONCE,
    "set_stockpile_priority": CHANGES_GAME_ONCE,
    "set_stockpile_filter": CHANGES_GAME_ONCE,
}

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def declared(tool) -> dict:
    return {h: getattr(tool.annotations, h, None) for h in HINTS}


def test_every_tool_declares_every_hint():
    # An unset hint takes the MCP default, which describes a destructive write.
    tools = list_tools()
    unset = {n: [h for h, v in declared(t).items() if v is None] for n, t in tools.items()}
    assert {n: hints for n, hints in unset.items() if hints} == {}
    assert [n for n, t in tools.items() if declared(t)["openWorldHint"] is not False] == []


def test_every_tool_declares_what_its_row_says():
    assert len(READ_TOOLS) == len(set(READ_TOOLS))
    # A tool moved between the two keeps no row in the one it left.
    assert sorted(set(READ_TOOLS) & set(WRITE_TOOLS)) == []
    expected = {name: READS_GAME for name in READ_TOOLS} | WRITE_TOOLS
    tools = list_tools()
    assert sorted(set(tools) - set(expected)) == []  # a tool without a row
    assert sorted(set(expected) - set(tools)) == []  # a row without a tool
    assert {n: declared(t) for n, t in tools.items() if declared(t) != expected[n]} == {}


def placeholder_arguments(schema: dict) -> dict:
    """A value of the declared type for each required argument.

    Only string, integer, number and boolean are made; a tool with a required argument
    of another type, or of a union with no single type, stops here with a KeyError and
    gets a value added.
    """
    values = {"string": "1", "integer": 1, "number": 1, "boolean": True}
    return {name: values[schema["properties"][name]["type"]]
            for name in schema.get("required", [])}


# Taken when the tests are collected. pytest turns an empty list into one skip, so the
# test below it checks the list against what the server lists.
TOOL_NAMES = sorted(t.name for t in main.mcp._tool_manager.list_tools())


def test_every_listed_tool_is_checked_against_what_it_sends():
    assert TOOL_NAMES == sorted(list_tools())
    assert TOOL_NAMES


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_a_tool_sends_what_it_declares(name, use_bridge):
    # Read from the bridge requests alone, not from the rows above, so that a row and a
    # declaration changed together still fail here when the tool does otherwise. Only
    # readOnlyHint can be read this way; destructiveHint and idempotentHint are held
    # by the rows alone. It sees the one path taken with the required arguments alone
    # and an empty answer: a tool that reads, then writes on what it read, is not
    # followed past its first answer, and a write that also reads fails here, so such
    # a tool needs this check revisited when it is added.
    sent = []

    async def handle(request: httpx.Request) -> httpx.Response:
        sent.append((request.method, request.url.path))
        return httpx.Response(200, json={})

    use_bridge(httpx.MockTransport(handle))
    tool = list_tools()[name]
    # The answer is not what the tool expects and may fail it; only the requests count.
    call_result(name, placeholder_arguments(tool.inputSchema))
    assert sent, "sent nothing to the bridge"
    if declared(tool)["readOnlyHint"] is True:
        assert [s for s in sent if s[0] != "GET"] == []
    else:
        assert [s for s in sent if s[0] != "POST" or not s[1].startswith("/command/")] == []


# ── Startup ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("token", ["secret-value ", "secret\tvalue", "sécret-value"])
def test_a_token_that_cannot_be_a_header_stops_the_server_without_showing_it(token):
    env = {**os.environ, main.TOKEN_ENV: token}
    started = subprocess.run([sys.executable, "-c", "import main"],
                             cwd=Path(main.__file__).parent, env=env,
                             capture_output=True, text=True, encoding="utf-8")
    assert started.returncode != 0
    assert main.TOKEN_ENV in started.stderr
    assert token.strip() not in started.stderr
