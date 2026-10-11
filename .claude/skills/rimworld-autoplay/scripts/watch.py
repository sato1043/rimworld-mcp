"""Watch a RimWorld game through the bridge and write one line when a cycle should wake.

Every line on standard output is one JSON object, so that a Monitor turns each into one
notification. The rules for when to wake are in watch_rules.py; this script reads the
bridge, pauses the game when the rules say so, writes the lines and keeps its place in
.claude/play/<colony>/watch.json so that a restart continues where it stopped. While
.claude/play/<colony>/cycle.json is there, a cycle is at work (check_plan.py keeps it);
the parent restarts this script whenever its Monitor runs out, so it may start then too.
A mark that keeps no time, or one kept longer ago than a cycle takes (MARK_STALE_SECONDS),
is left by a cycle that did not return: the watcher pauses the game and stops on it.

Each poll reads the tick and speed (/state), the letters (/events), the game's alerts
(/alerts/active) and the game's rating of the danger on the map (/threats). While a danger
has been seen and no all-clear has woken a cycle yet, watch.json keeps it as `fighting`,
so a restart still wakes the all-clear.

Run it from the main checkout:

    uv run --project mcp_server python .claude/skills/rimworld-autoplay/scripts/watch.py --colony <name>

Before watching, it checks that the bridge answers, that it runs from the main checkout,
that the colony's plan file exists and that the bridge has the game's alerts (a Mod
built without them answers 404); that no other watcher of the colony holds watch.lock; on
starting, that the last run did not end with
the game (an ended watcher takes no readings). A failed check, or arguments it cannot
take, writes one error line and exits 2. A failure it cannot recover from while watching
- a stale mark, or a bridge that fails for GIVE_UP_SECONDS - writes one error line and
exits 1. An ended game writes its line and exits 0. The last line the watcher writes
carries "stopping": true, so that the parent tells it from a Monitor that ran out.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import subprocess
import sys
import time
import traceback
import urllib.parse
from dataclasses import replace
from typing import BinaryIO, Callable, NoReturn

import httpx

from play_files import (CYCLE_MARK, PLAN, PLAY_ROOT, REPO_ROOT, MarkUnreadable, colony_name_problem,
                        events_place, mark_time, replace_file)
from watch_rules import (
    GIVE_UP_SECONDS,
    PATROL_TICKS,
    Alert,
    Event,
    Item,
    Mode,
    Note,
    Reading,
    Reason,
    Signal,
    State,
    Urgency,
    bridge_failed,
    step,
)

# The same address and shared secret as mcp_server/main.py (RIMWORLD_URL, TOKEN_ENV,
# TOKEN_HEADER); a change to one is a change to both.
BRIDGE_URL = "http://127.0.0.1:8080"
TOKEN_ENV = "RIMWORLD_MCP_TOKEN"
TOKEN_HEADER = "X-MCP-Token"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
# The bridge waits up to 15 seconds for the game's frame; a little more lets its own
# answer arrive.
TIMEOUT_SECONDS = 20.0
EVENTS_LIMIT = 200
POLL_SECONDS = 1.5
PING_RETRY_SECONDS = 3.0
# A mark older than this is left by a cycle that did not return: while it stands, the
# watcher would let the game run through anything. The 28 cycles run to 2026-09-29 took
# 9.1 minutes at the longest and about one at the median.
MARK_STALE_SECONDS = 30 * 60
# A mark that keeps a time further ahead of the clock than this was not kept by the parent.
MARK_AHEAD_SECONDS = 60
# The lock that keeps a second watcher of the colony from starting, next to watch.json.
WATCH_LOCK = "watch.lock"
LOCK_WAIT_SECONDS = 10.0
LOCK_RETRY_SECONDS = 1.0


class BridgeError(Exception):
    """The bridge did not answer, or answered with something this script cannot read."""


class StartRefused(Exception):
    """What the watcher kept says it must not go on watching."""


def stale_mark(mark: pathlib.Path, now: float) -> str | None:
    """Why the mark cannot stand for a cycle at work, or None when it can."""
    try:
        age = now - mark_time(mark)
    except MarkUnreadable as e:
        return str(e)
    if age > MARK_STALE_SECONDS:
        return f"{CYCLE_MARK} was kept {age / 60:.0f} minutes ago, longer than a cycle takes"
    if age < -MARK_AHEAD_SECONDS:
        return f"{CYCLE_MARK} keeps a time {-age:.0f} seconds ahead of the clock"
    return None


class Bridge:
    """The reads and the one command the watcher sends to the bridge."""

    def __init__(self, client: httpx.Client):
        self._client = client

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as ex:
            raise BridgeError(f"GET {path}: {type(ex).__name__}: {_short(str(ex))}") from ex
        return _body(f"GET {path}", response)

    def ping(self) -> None:
        self._get("/ping")

    def state(self) -> tuple[int, str]:
        body = self._get("/state")
        tick, speed = body.get("tick"), body.get("speed")
        if not isinstance(tick, int) or not isinstance(speed, str):
            raise BridgeError(f"GET /state: unexpected answer {_short(body)}")
        return tick, speed

    def events(self, since: str | None) -> tuple[list[Event], str, bool, bool]:
        """Every event after since, following the bridge's limit until nothing is left."""
        events: list[Event] = []
        gap = reloaded = False
        while True:
            params = {"limit": str(EVENTS_LIMIT)}
            if since:
                params["since"] = since
            body = self._get("/events", params)
            try:
                events += [Event(e["kind"], e.get("type"), e.get("label"), int(e["tick"]))
                           for e in body["events"]]
                after, more = body["next"], bool(body["more"])
                gap |= bool(body["gap"])
                reloaded |= bool(body["reloaded"])
            except (KeyError, TypeError, ValueError) as ex:
                raise BridgeError(f"GET /events: unexpected answer {_short(body)}") from ex
            if not more:
                return events, after, gap, reloaded
            # The bridge moves on every page; one that says there is more but does not
            # move would keep this loop reading the same page for ever.
            if after == since:
                raise BridgeError(f"GET /events: says there is more after {after} but does not move")
            since = after

    def alerts(self) -> list[Alert]:
        body = self._get("/alerts/active")
        try:
            return [Alert(a["type"], a["label"], a["priority"]) for a in body["alerts"]]
        except (KeyError, TypeError) as ex:
            raise BridgeError(f"GET /alerts/active: unexpected answer {_short(body)}") from ex

    def danger(self) -> str:
        """The game's own rating of the threat on the map, as /threats gives it."""
        body = self._get("/threats")
        rating = body.get("dangerRating")
        if not isinstance(rating, str):
            raise BridgeError(f"GET /threats: unexpected answer {_short(body)}")
        return rating

    def pause(self) -> None:
        try:
            response = self._client.post("/command/pause", json={"paused": True})
        except httpx.HTTPError as ex:
            raise BridgeError(f"POST /command/pause: {type(ex).__name__}: {ex}") from ex
        body = _body("POST /command/pause", response)
        if body.get("paused") is not True:
            raise BridgeError(f"POST /command/pause: the game did not pause {_short(body)}")


def _body(what: str, response: httpx.Response) -> dict:
    if response.status_code != 200:
        raise BridgeError(f"{what}: HTTP {response.status_code} {_short(response.text)}")
    try:
        body = response.json()
    except ValueError as ex:
        raise BridgeError(f"{what}: not JSON {_short(response.text)}") from ex
    if not isinstance(body, dict):
        raise BridgeError(f"{what}: unexpected answer {_short(body)}")
    if "error" in body:
        raise BridgeError(f"{what}: {_short(body['error'])}")
    return body


def _short(value, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


# ── Checks before watching ────────────────────────────────────────────────────

def run_git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def main_checkout_problem(git: Callable[..., str] | None = None) -> str | None:
    """Why this is not the main checkout, or None when it is.

    The first worktree git lists is the main one; the play notes live only there.
    """
    git = git or run_git
    try:
        listing = git("worktree", "list", "--porcelain")
        toplevel = git("rev-parse", "--show-toplevel").strip()
    except (OSError, subprocess.CalledProcessError) as ex:
        return f"git could not tell the checkout: {ex}"
    first = next((line[len("worktree "):] for line in listing.splitlines()
                  if line.startswith("worktree ")), None)
    if first is None:
        return "git listed no worktree"
    if os.path.normcase(os.path.normpath(first)) != os.path.normcase(os.path.normpath(toplevel)):
        return f"not the main checkout: this is {toplevel}, the main one is {first}"
    return None


def startup_problem(bridge: Bridge, colony: str, play_root: pathlib.Path,
                    git: Callable[..., str] | None = None,
                    sleep: Callable[[float], None] | None = None, restart: bool = False,
                    clock: Callable[[], float] | None = None) -> str | None:
    """The first check that fails before watching, or None when all pass.

    A restart (the parent starts the watcher again whenever its Monitor runs out) gives
    the bridge as long as a running watcher does before stopping on it, counted on the
    clock as a running watcher counts it, so that pings that hang until their timeout use
    up the time too; a first start tries it twice, as the player is there to see to it.

    The alerts are checked only for whether the bridge has them: a failure to read them is
    noted at each poll and does not stop a running watcher, so it does not stop a start.
    """
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    problem = colony_name_problem(colony)
    if problem:
        return problem
    given = GIVE_UP_SECONDS if restart else PING_RETRY_SECONDS
    began = clock()
    while True:
        try:
            bridge.ping()
            break
        except BridgeError as ex:
            if clock() - began >= given:
                return f"the bridge does not answer: {ex}"
            sleep(PING_RETRY_SECONDS)
    problem = main_checkout_problem(git)
    if problem:
        return problem
    plan = play_root / colony / "plan.md"
    if not plan.is_file():
        return f"no plan file at {plan}"
    try:
        bridge.alerts()
    except BridgeError as ex:
        if "HTTP 404" in str(ex):
            return ("the bridge has no /alerts/active: build and install the Mod with the game's "
                    "alerts (task/TASK0018-active-alerts)")
        # Any other failure is the one each poll notes as alerts_unreadable and watches on.
    return None


# ── One watcher for a colony ──────────────────────────────────────────────────

def _try_lock(handle: BinaryIO) -> bool:
    """Lock the first byte of the open file without waiting. The operating system lets the
    lock go when the process ends, however it ends, so a watcher killed with its Monitor
    leaves nothing behind.

    Only the refusal a held lock gives is taken for another watcher (Windows refuses with
    EACCES, flock with EWOULDBLOCK); any other failure, such as a file system without
    locks, is raised, so that it is not reported as a watcher that is not there."""
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except PermissionError:
            return False
    else:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


def release_lock(handle: BinaryIO) -> None:
    """Let the lock go and close the file. Windows asks for a locked region to be unlocked
    before its file is closed; closing alone may keep it for a while."""
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def hold_lock(path: pathlib.Path, wait_seconds: float = LOCK_WAIT_SECONDS,
              sleep: Callable[[float], None] | None = None) -> BinaryIO | None:
    """The open lock file of the colony, or None when another watcher holds it.

    Two watchers of one colony would write one watch.json and wake a cycle twice for one
    event. A Monitor that ran out may take a moment to end the old watcher, so the lock is
    tried for wait_seconds before giving up."""
    sleep = sleep or time.sleep
    handle = path.open("ab")
    tries = 1 + math.ceil(wait_seconds / LOCK_RETRY_SECONDS)
    try:
        for attempt in range(tries):
            if _try_lock(handle):
                return handle
            if attempt < tries - 1:
                sleep(LOCK_RETRY_SECONDS)
    except BaseException:
        handle.close()
        raise
    handle.close()
    return None


# ── Keeping the place ─────────────────────────────────────────────────────────

def dump_state(state: State, cursor: str | None) -> dict:
    """What watch.json keeps. Times are the process's own clock and are not kept."""
    return {
        "cursor": cursor,
        "mode": state.mode.value,
        "last_wake_tick": state.last_wake_tick,
        "pending": [{"source": i.source, "type": i.type, "label": i.label, "urgency": i.urgency.value,
                     "notes": [n.value for n in i.notes], "priority": i.priority, "tick": i.tick}
                    for i in state.pending],
        "notes": sorted(n.value for n in state.notes),
        "known_alerts": sorted(state.known_alerts),
        "fighting": state.fighting,
    }


def upgraded(data: dict) -> dict:
    """watch.json in the form load_state reads.

    The form with `marks` kept an alert's priority among the notes, where it cannot be told
    from them for certain, so such a file is read only when it notes nothing.
    """
    if "marks" not in data:
        return data
    if data["marks"] or any(item["marks"] for item in data["pending"]):
        raise ValueError("it keeps marks of an older watcher, which this one cannot read")
    rest = {key: value for key, value in data.items() if key != "marks"}
    pending = [{**item, "notes": [], "priority": None} for item in data["pending"]]
    return {**rest, "notes": [], "pending": pending}


def load_state(data: dict) -> tuple[State, str | None]:
    state = State(
        last_wake_tick=int(data["last_wake_tick"]),
        mode=Mode(data["mode"]),
        pending=tuple(Item(i["source"], i["type"], i["label"], Urgency(i["urgency"]),
                           tuple(Note(n) for n in i["notes"]), i["priority"],
                           # Kept before the tick was kept: such an item only lacks the
                           # tick that tells the game's own pause a reading late.
                           i.get("tick"))
                      for i in data["pending"]),
        notes=frozenset(Note(n) for n in data["notes"]),
        known_alerts=frozenset(data["known_alerts"]),
        # A watch.json kept before the fight was kept has none: no fight is taken to be on.
        fighting=bool(data.get("fighting", False)),
    )
    return state, data["cursor"]


def save(path: pathlib.Path, data: dict) -> None:
    replace_file(path, json.dumps(data, ensure_ascii=False, indent=1))


# ── Watching ──────────────────────────────────────────────────────────────────

class Watcher:
    """One poll at a time: read the bridge, apply the rules, act, keep the place."""

    def __init__(self, bridge: Bridge, store: pathlib.Path, write: Callable[[dict], None],
                 patrol_ticks: int = PATROL_TICKS, clock: Callable[[], float] = time.time):
        self.bridge = bridge
        self.store = store
        self.mark = store.with_name(CYCLE_MARK)
        # The wall clock the mark's time is kept on; the polls' own time is monotonic.
        self.clock = clock
        self.write = write
        self.patrol_ticks = patrol_ticks
        self.state: State | None = None
        self.cursor: str | None = None
        self._saved: dict | None = None
        # Set when the watcher stopped for a failure rather than for the end of the game.
        self.failed = False

    def start(self) -> None:
        """Continue from watch.json, or start from the game as it is now.

        A first start skips the events already in the game: they happened before the
        watcher was asked to look.
        """
        if self.store.is_file():
            kept = f".claude/play/{self.store.parent.name}/{self.store.name}"
            try:
                data = upgraded(json.loads(self.store.read_text(encoding="utf-8")))
                self.state, self.cursor = load_state(data)
            except (ValueError, KeyError, TypeError) as ex:
                raise StartRefused(f"{kept} cannot be read ({type(ex).__name__}: {ex}). Remove "
                                   f"{kept} to watch afresh") from ex
            if self.state.mode is Mode.ENDED:
                # An ended watcher takes no readings, so going on would stop without a word.
                raise StartRefused(f"the last run ended with the game ({kept} keeps it). If this "
                                   f"game goes on, remove {kept} to watch it afresh")
            self._saved = dump_state(self.state, self.cursor)
            return
        tick, _ = self.bridge.state()
        _, self.cursor, _, _ = self.bridge.events(None)
        self.state = State(last_wake_tick=tick)
        self._keep()

    def poll(self, now: float) -> bool:
        """One poll. False once the watcher should stop."""
        assert self.state is not None
        try:
            tick, speed = self.bridge.state()
            events, cursor, gap, reloaded = self.bridge.events(self.cursor)
            danger = self.bridge.danger()
        except BridgeError as ex:
            result = bridge_failed(self.state, now, str(ex))
            self.state = result.state
            if result.signal:
                self.write(result.signal.line())
            self.failed = result.stop
            return not result.stop
        # The alerts are read apart: a failure of theirs alone (one broken alert of a mod)
        # must not keep a raid's letter from waking a cycle.
        try:
            alerts: tuple[Alert, ...] | None = tuple(self.bridge.alerts())
        except BridgeError:
            alerts = None

        # Read after the game: the parent keeps the mark before a cycle can resume the game,
        # so a running game is never taken for the end of a cycle that has only just begun.
        cycle_open = self.mark.exists()
        problem = stale_mark(self.mark, self.clock()) if cycle_open else None
        if problem and not self.mark.exists():
            # Closed between the two reads: the cycle has just returned.
            cycle_open, problem = False, None
        if problem:
            return self._stop_for_mark(problem)
        if self.state.mode is Mode.CYCLE and not cycle_open and self.state.pending:
            self.state = replace(self.state, pending=self._unseen_by_the_cycle(self.state.pending))
        result = step(self.state, Reading(now, tick, speed, tuple(events), alerts, gap, reloaded,
                                          cycle_open, danger), patrol_ticks=self.patrol_ticks)
        self.state, self.cursor = result.state, cursor
        signal = result.signal
        if result.pause:
            try:
                self.bridge.pause()
            except BridgeError as ex:
                # The cycle pauses the game itself first, so the wake still goes out.
                signal = replace(signal, notes=signal.notes | {Note.PAUSE_FAILED}, detail=str(ex))
        # The line goes out before the place is kept: if keeping fails, a restart reads the
        # same events again and wakes twice, rather than never.
        if signal:
            self.write(signal.line())
        self._keep()
        return not result.stop

    def _unseen_by_the_cycle(self, held: tuple[Item, ...]) -> tuple[Item, ...]:
        """What was held while a cycle was at work, less the events the cycle has read.

        A cycle reads the events itself and keeps in the plan where it read up to. An event
        held from before that place has been seen to, and would only wake another cycle for
        the same thing. An alert is kept: nothing tells which alerts the cycle looked at.
        Whatever cannot be read (the plan, its place, the events after it) keeps everything:
        a cycle too many costs less than an event no cycle saw.
        """
        try:
            place = events_place(self.store.with_name(PLAN).read_text(encoding="utf-8-sig"))
            if place is None:
                return held
            unread, _, gap, reloaded = self.bridge.events(place)
        except (OSError, UnicodeDecodeError, BridgeError):
            return held
        if gap or reloaded:
            return held
        after = {(e.kind, e.type, e.label, e.tick) for e in unread}
        return tuple(item for item in held
                     if item.tick is None or (item.source, item.type, item.label, item.tick) in after)

    def _stop_for_mark(self, problem: str) -> bool:
        """Pause the game and stop, rather than watch on as if a cycle were at work.

        The events of this poll are left unread, so a restart after the mark is closed
        reads them again."""
        detail = (f"cycle mark: {problem}. The watcher paused the game and stops. See to the "
                  f"game, then run check_plan.py --colony {self.store.parent.name} once to close "
                  f"the mark")
        try:
            self.bridge.pause()
        except BridgeError as ex:
            detail += f" (the game could not be paused: {ex})"
        self.write(last_error_line(detail))
        self.failed = True
        return False

    def _keep(self) -> None:
        data = dump_state(self.state, self.cursor)
        if data != self._saved:
            save(self.store, data)
            self._saved = data


def write_line(body: dict) -> None:
    print(json.dumps(body, ensure_ascii=False), flush=True)


def last_error_line(detail: str) -> dict:
    """The error line the watcher writes before it stops."""
    return Signal(Reason.ERROR, None, detail=detail, stopping=True).line()


class LineParser(argparse.ArgumentParser):
    """Refuses its arguments with an error line on standard output, as the watcher's other
    failures do: the parent's Monitor hears standard output only."""

    def error(self, message: str) -> NoReturn:
        write_line(last_error_line(f"startup: {message}"))
        sys.exit(2)


def bridge_url(text: str) -> str:
    """A --bridge address, held to this machine: the shared secret goes with every request."""
    host = urllib.parse.urlsplit(text).hostname
    if host not in LOOPBACK_HOSTS:
        raise argparse.ArgumentTypeError(f"the bridge must be on this machine ({', '.join(LOOPBACK_HOSTS)}), "
                                         f"not {host!r}")
    return text


def make_client(url: str) -> httpx.Client:
    token = os.environ.get(TOKEN_ENV)
    headers = {TOKEN_HEADER: token} if token else {}
    return httpx.Client(base_url=url, headers=headers, timeout=TIMEOUT_SECONDS)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = LineParser(description=__doc__.splitlines()[0])
    parser.add_argument("--colony", required=True, help="the directory name under .claude/play/")
    parser.add_argument("--patrol-ticks", type=int, default=PATROL_TICKS,
                        help=f"game ticks between patrols (default {PATROL_TICKS}, one day)")
    parser.add_argument("--bridge", type=bridge_url, default=BRIDGE_URL,
                        help=f"the bridge's address on this machine (default {BRIDGE_URL})")
    args = parser.parse_args(argv)

    play_root = PLAY_ROOT
    with make_client(args.bridge) as client:
        bridge = Bridge(client)
        restart = (play_root / args.colony / "watch.json").is_file()
        problem = startup_problem(bridge, args.colony, play_root, restart=restart)
        if problem:
            write_line(last_error_line(f"startup: {problem}"))
            return 2
        try:
            lock = hold_lock(play_root / args.colony / WATCH_LOCK)
        except OSError as ex:
            write_line(last_error_line(f"startup: cannot lock {WATCH_LOCK}: {ex}"))
            return 2
        if lock is None:
            write_line(last_error_line(f"startup: another watcher of {args.colony} is running "
                                       f"({WATCH_LOCK} is held). Stop it before starting this one"))
            return 2
        watcher = Watcher(bridge, play_root / args.colony / "watch.json", write_line, args.patrol_ticks)
        try:
            watcher.start()
            while watcher.poll(time.monotonic()):
                time.sleep(POLL_SECONDS)
        except (BridgeError, StartRefused) as ex:
            write_line(last_error_line(f"startup: {ex}"))
            return 2
        except Exception:
            # Written as a line so the parent hears of it; the stack goes to standard error.
            traceback.print_exc()
            write_line(last_error_line(f"the watcher failed: {traceback.format_exc(limit=1).strip()}"))
            return 1
        finally:
            release_lock(lock)
    return 1 if watcher.failed else 0


if __name__ == "__main__":
    sys.exit(main())
