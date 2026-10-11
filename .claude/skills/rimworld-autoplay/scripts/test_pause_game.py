"""Tests of the script that pauses the game when the player stops a run. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import httpx
import pytest

import pause_game
from pause_game import main, run
from watch import Bridge


def bridge(handler) -> Bridge:
    return Bridge(httpx.Client(base_url="http://bridge", transport=httpx.MockTransport(handler)))


def test_the_game_is_paused_through_the_bridge():
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={"paused": True, "speed": "Paused"})
    assert run(bridge(handler)) == (0, "paused: the game is paused")
    assert asked == [("POST", "/command/pause", b'{"paused":true}')]


def test_a_game_that_did_not_pause_asks_the_player_to_pause_it():
    code, line = run(bridge(lambda request: httpx.Response(200, json={"paused": False})))
    assert code == 1
    assert line.startswith("NOT PAUSED: POST /command/pause: the game did not pause")
    assert line.endswith("Pause the game on screen")


def test_a_bridge_that_does_not_answer_asks_the_player_to_pause_it():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)
    code, line = run(bridge(refuse))
    assert code == 1
    assert "ConnectError" in line


def test_a_bridge_elsewhere_is_refused(capsys, monkeypatch):
    monkeypatch.setattr(pause_game, "make_client", lambda url: pytest.fail(f"a client with the token for {url}"))
    with pytest.raises(SystemExit) as exited:
        main(["--bridge", "http://example.com:8765"])
    assert exited.value.code == 2
    assert "the bridge must be on this machine" in capsys.readouterr().err
