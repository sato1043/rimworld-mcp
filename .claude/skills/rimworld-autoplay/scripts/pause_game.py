"""Pause the game through the bridge, for the parent that stops a run at the player's word.

A cycle resumes the game before it returns, so stopping the watcher alone leaves the game
running with nobody to answer what happens in it. The parent does not call the game's
tools, so it pauses the game with this script once the cycle is back.

Run it from the main checkout:

    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/pause_game.py

It writes one line. Exit status: 0 when the game is paused; 1 when it could not be
paused (the bridge did not answer, or the game did not pause), so the player is asked to
pause it on screen.
"""

from __future__ import annotations

import argparse
import sys

from watch import BRIDGE_URL, Bridge, BridgeError, bridge_url, make_client


def run(bridge: Bridge) -> tuple[int, str]:
    try:
        bridge.pause()
    except BridgeError as ex:
        return 1, f"NOT PAUSED: {ex}. Pause the game on screen"
    return 0, "paused: the game is paused"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bridge", type=bridge_url, default=BRIDGE_URL,
                        help=f"the bridge's address on this machine (default {BRIDGE_URL})")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    with make_client(args.bridge) as client:
        code, line = run(Bridge(client))
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
