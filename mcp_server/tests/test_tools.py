"""The tools as an MCP client calls them, against a stand-in for the game's bridge.

Each test runs the real server in memory and swaps only the HTTP transport, so the
tool arguments, the output schema and the client's error handling are all exercised.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

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


def call_result(tool: str, arguments: dict | None = None):
    async def run():
        async with create_connected_server_and_client_session(main.mcp) as session:
            return await session.call_tool(tool, arguments or {})
    return asyncio.run(run())


def call(tool: str, arguments: dict | None = None):
    result = call_result(tool, arguments)
    assert not result.isError, result.content
    # The tools send text only: FastMCP writes a dict as one JSON block, and a list
    # as one block per item. (A one-item list is read back as its item.)
    assert result.structuredContent is None, tool
    items = [json.loads(block.text) for block in result.content]
    return items[0] if len(items) == 1 else items


def list_tools():
    async def run():
        async with create_connected_server_and_client_session(main.mcp) as session:
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


# ── Tool surface ──────────────────────────────────────────────────────────────

def test_get_animals_defaults_to_counts_and_takes_race_and_detail(use_bridge):
    transport, _ = bridge()
    use_bridge(transport)
    counts = {"colony": [], "others": [{"race": "Deer", "faction": "wild", "count": 2}]}
    assert call("get_animals") == counts
    assert call("get_animals", {"race": ""}) == counts
    assert [a["id"] for a in call("get_animals", {"race": "Deer"})] == ["Deer1", "Deer2"]
    assert call("get_animals", {"detail": True}) == BRIDGE["/animals"]
    # One block per animal, as the bridge's list would give.
    assert len(call_result("get_animals", {"detail": True}).content) == len(DEER)
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
    assert call("get_animal_training")["pending"] == ["guard"]
    assert call("get_animal_training", {"detail": True}) == TRAINING[0]


def test_new_arguments_are_optional_in_the_schemas():
    tools = list_tools()
    for name, args in (("get_animals", {"race", "detail"}), ("get_buildings", {"detail"}),
                       ("get_animal_training", {"detail"})):
        schema = tools[name].inputSchema
        assert args <= set(schema["properties"]), name
        assert not args & set(schema.get("required", [])), name
    # Text like the other tools' optional arguments, not text-or-null.
    assert tools["get_animals"].inputSchema["properties"]["race"]["type"] == "string"


def test_overview_is_marked_read_only():
    assert list_tools()["get_colony_overview"].annotations.readOnlyHint is True


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
