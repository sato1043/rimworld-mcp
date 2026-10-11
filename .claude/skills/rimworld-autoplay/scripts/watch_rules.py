"""The rules of the watcher that wakes a play cycle, free of the game and of the network.

The watcher reads the bridge every second or two and hands each reading to `step`, which
decides whether to pause the game and which signal line to write. The usage limit has its
own rules in usage_rules.py. Nothing here reads a clock, a file or a socket: the caller
passes the time and the readings in, so the tests can drive every state.

The watcher is in one of four modes while it watches, and in a fifth, ended, after:

- running: the game is going. An urgent item pauses it and wakes a cycle at once; items
  that can wait are gathered for a few seconds first; a quiet day wakes a patrol. While
  the game rates a danger, a cycle is woken again every FOLLOW_UP_TICKS to follow the fight,
  and once when the danger is gone, to see to what the fight left.
- waiting: the watcher paused the game and no cycle has opened yet. What arrives is held
  until the game is resumed, and is then handled as if it had just arrived.
- cycle: the parent keeps the cycle's mark while a cycle is at work. A cycle pauses and
  resumes the game as it fights, so the speed says nothing about its end: nothing is
  paused and no cycle is woken. What arrives is held, and each reading that brings
  something writes a progress line for the player to see. When the mark is gone, a
  running game handles what was held, and so does a game that paused itself on a letter
  held meanwhile; a game the cycle left paused waits for the player.
- user_paused: the game stopped without the watcher pausing it. Nothing wakes a cycle
  until the player resumes.

- ended: an ended game writes one line and stops the watcher, whatever the mode it came
  from. An ended watcher takes no readings.
"""

from __future__ import annotations

import enum
import unicodedata
from dataclasses import dataclass, replace
from typing import assert_never

from cycle_agent import CYCLE_AGENT

# RimWorld.GenDate.TicksPerDay in RimWorld 1.6.
TICKS_PER_DAY = 60000
PATROL_TICKS = TICKS_PER_DAY
# About 46 seconds on a colony measured at 13 ticks a second, so that a fight goes
# unwatched for less than a minute between cycles (a game hour, 2500, was three minutes).
FOLLOW_UP_TICKS = 600
BATCH_SECONDS = 5.0
# A bridge that fails this long is not a passing failure, so the watcher stops on it. The
# first failure is heard at once; a failure this long is the watcher's last line.
GIVE_UP_SECONDS = 60.0

# The longest a label, type or detail runs on a signal line.
TEXT_LIMIT = 200

PAUSED = "Paused"
# The danger rating of /threats when the game sees no threat. The count of hostiles is not
# used: it counts downed enemies and dormant mechanoids too, so it stays above zero long
# after a raid is over.
NO_DANGER = "None"


class LetterClass(enum.Enum):
    THREAT = "threat"
    CHOICE = "choice"
    NOTICE = "notice"
    END = "end"


# Every LetterDef of Core, by name. A letter of a type not listed here (one a mod adds)
# wakes a cycle at once and is marked unclassified.
LETTER_CLASSES: dict[str, LetterClass] = {
    "ThreatBig": LetterClass.THREAT,
    "ThreatSmall": LetterClass.THREAT,
    "NegativeEvent": LetterClass.THREAT,
    "Death": LetterClass.THREAT,
    "NewQuest_ThreatBig": LetterClass.THREAT,
    "RansomDemand": LetterClass.CHOICE,
    "ChoosePawn": LetterClass.CHOICE,
    "AcceptVisitors": LetterClass.CHOICE,
    "AcceptJoiner": LetterClass.CHOICE,
    "BetrayVisitors": LetterClass.CHOICE,
    "NewQuest": LetterClass.NOTICE,
    "NeutralEvent": LetterClass.NOTICE,
    "PositiveEvent": LetterClass.NOTICE,
    "RitualOutcomePositive": LetterClass.NOTICE,
    "RitualOutcomeNegative": LetterClass.NOTICE,
    "BundleLetter": LetterClass.NOTICE,
    "GameEnded": LetterClass.END,
}


class Urgency(enum.Enum):
    """How soon an item wakes a cycle once the game is running."""

    NOW = "now"
    GATHER = "gather"
    PATROL = "patrol"


class Reason(enum.Enum):
    URGENT = "urgent"
    BATCH = "batch"
    # A fight goes on; nothing new arrived, but the last cycle returned FOLLOW_UP_TICKS ago.
    FOLLOW_UP = "follow_up"
    # The fight is over. The end of a raid brings no letter, so without this no cycle would
    # see to the downed, the drafted and the wounded until the next patrol.
    ALL_CLEAR = "all_clear"
    PATROL = "patrol"
    ENDED = "ended"
    ERROR = "error"
    # Shown to the player while a cycle is at work; it wakes nothing.
    PROGRESS = "progress"


def wakes_cycle(reason: Reason) -> bool:
    """Whether a signal of this reason wakes a cycle."""
    match reason:
        case Reason.URGENT | Reason.BATCH | Reason.FOLLOW_UP | Reason.ALL_CLEAR | Reason.PATROL:
            return True
        case Reason.ENDED | Reason.ERROR | Reason.PROGRESS:
            return False
        case _:
            assert_never(reason)


class Mode(enum.Enum):
    RUNNING = "running"
    WAITING = "waiting"
    CYCLE = "cycle"
    USER_PAUSED = "user_paused"
    ENDED = "ended"


class Note(enum.Enum):
    """What a signal or one of its items notes beside the reason it wakes for."""

    # The events skipped some entries, or the save was loaded again since the last read.
    GAP = "gap"
    RELOADED = "reloaded"
    # A letter of a type the table does not list, or an entry that is not a letter.
    UNCLASSIFIED = "unclassified"
    # A letter that asks the player to choose, which no tool can answer.
    CHOICE = "choice"
    ENDED = "ended"
    # The watcher could not pause the game before writing the signal.
    PAUSE_FAILED = "pause_failed"
    # The game's alerts could not be read since the last wake: a new alert may have gone
    # unseen, though the letters were still read.
    ALERTS_UNREADABLE = "alerts_unreadable"


def printable(text: str | None, limit: int | None = TEXT_LIMIT) -> str | None:
    """Text the game or a mod made, fit to stand on a signal line.

    Labels and names come from the game, from mods and from saves that others share, and
    the parent reads the line. Control and format characters (line breaks, bidirectional
    overrides) are taken out, and the text is cut to limit; None keeps its length, for text
    the watcher writes around what it quotes.
    """
    if text is None:
        return None
    kept = "".join(ch for ch in text
                   if not unicodedata.category(ch).startswith("C") and unicodedata.category(ch) not in ("Zl", "Zp"))
    return kept if limit is None or len(kept) <= limit else kept[:limit] + "..."


@dataclass(frozen=True)
class Event:
    """One entry of the bridge's /events."""

    kind: str
    type: str | None
    label: str | None
    tick: int


@dataclass(frozen=True)
class Alert:
    """One entry of the bridge's /alerts/active."""

    type: str
    # Both None for an alert that could not describe itself, such as a broken mod's.
    label: str | None
    priority: str | None



@dataclass(frozen=True)
class Reading:
    """What one poll of the bridge saw."""

    now: float
    tick: int
    speed: str
    events: tuple[Event, ...] = ()
    # None when the alerts could not be read; the letters are taken all the same.
    alerts: tuple[Alert, ...] | None = ()
    gap: bool = False
    reloaded: bool = False
    # Whether the parent's mark of a cycle at work was there.
    cycle_open: bool = False
    # The danger rating of /threats: None, or how great a threat the game sees.
    danger: str = NO_DANGER


@dataclass(frozen=True)
class Item:
    """Something a signal reports: a letter or an alert."""

    source: str
    type: str | None
    label: str | None
    urgency: Urgency
    notes: tuple[Note, ...] = ()
    # The game's priority of an alert; a letter has none.
    priority: str | None = None
    # The tick a letter arrived on; an alert has none.
    tick: int | None = None

    def summary(self) -> dict[str, object]:
        entry: dict[str, object] = {"source": self.source, "type": printable(self.type),
                                    "label": printable(self.label)}
        if self.priority is not None:
            entry["priority"] = self.priority
        if self.notes:
            entry["notes"] = [note.value for note in self.notes]
        return entry


@dataclass(frozen=True)
class State:
    """The watcher's state between readings.

    last_wake_tick has no default: a watcher starts counting the patrol from the tick of
    the game it starts on, which only the caller knows.
    """

    last_wake_tick: int
    mode: Mode = Mode.RUNNING
    pending: tuple[Item, ...] = ()
    notes: frozenset[Note] = frozenset()
    gather_since: float | None = None
    known_alerts: frozenset[str] = frozenset()
    failing_since: float | None = None
    # A danger was seen and the all-clear has not woken a cycle yet.
    fighting: bool = False


@dataclass(frozen=True)
class Signal:
    reason: Reason
    tick: int | None
    items: tuple[Item, ...] = ()
    notes: frozenset[Note] = frozenset()
    detail: str | None = None
    # The watcher's last line: it stops after writing it.
    stopping: bool = False

    def line(self) -> dict:
        """The signal as the one JSON object the watcher writes on a line.

        A signal that wakes a cycle names the definition to wake, so that the parent takes
        it from the line rather than from a rule of its own."""
        body: dict = {"reason": self.reason.value, "tick": self.tick}
        if wakes_cycle(self.reason):
            body["agent"] = CYCLE_AGENT
        body["items"] = [item.summary() for item in self.items]
        if self.notes:
            body["notes"] = sorted(note.value for note in self.notes)
        if self.detail is not None:
            # The watcher's own words (what to run, that it stops) must not be cut; what it
            # quotes from the bridge is cut where it is quoted.
            body["detail"] = printable(self.detail, limit=None)
        if self.stopping:
            body["stopping"] = True
        return body


@dataclass(frozen=True)
class Step:
    """The outcome of one reading: the next state, and what the watcher does now."""

    state: State
    pause: bool = False
    signal: Signal | None = None

    @property
    def stop(self) -> bool:
        return self.signal is not None and self.signal.stopping


def classify_event(event: Event) -> Item | None:
    """The item a letter raises, or None for what no cycle is woken for."""
    if event.kind == "message":
        return None
    if event.kind != "letter":
        return Item(event.kind, event.type, event.label, Urgency.NOW, (Note.UNCLASSIFIED,), tick=event.tick)
    letter_class = LETTER_CLASSES.get(event.type or "")
    if letter_class is None:
        return Item("letter", event.type, event.label, Urgency.NOW, (Note.UNCLASSIFIED,), tick=event.tick)
    match letter_class:
        case LetterClass.THREAT:
            return Item("letter", event.type, event.label, Urgency.NOW, tick=event.tick)
        case LetterClass.CHOICE:
            return Item("letter", event.type, event.label, Urgency.NOW, (Note.CHOICE,), tick=event.tick)
        case LetterClass.NOTICE:
            return Item("letter", event.type, event.label, Urgency.GATHER, tick=event.tick)
        case LetterClass.END:
            return Item("letter", event.type, event.label, Urgency.NOW, (Note.ENDED,), tick=event.tick)
        case _:
            assert_never(letter_class)


def alert_items(known: frozenset[str], alerts: tuple[Alert, ...]) -> tuple[Item, ...]:
    """Items for the alerts of a type not seen since the last wake.

    An alert is known by its type alone: a label can carry a count or a name that changes
    while the same alert stays on screen. The game recalculates its alerts a few at a
    time, so one can drop out and come back while nothing changed; only a wake, which a
    cycle has looked at, sets the known alerts back to those showing then.
    """
    items = []
    for alert in alerts:
        if alert.type in known:
            continue
        urgency = _alert_urgency(alert.priority)
        if urgency is None:
            # Looked at at once, as a letter of an unknown type is: nothing here can tell how
            # much it matters.
            items.append(Item("alert", alert.type, alert.label, Urgency.NOW, (Note.UNCLASSIFIED,),
                              alert.priority))
            continue
        items.append(Item("alert", alert.type, alert.label, urgency, priority=alert.priority))
    return tuple(items)


def _alert_urgency(priority: str | None) -> Urgency | None:
    """How soon an alert wakes a cycle, by the priorities of RimWorld.AlertPriority in
    RimWorld 1.6; None for a priority the game does not have.

    A High alert, such as a colonist who needs tending, is one a player answers soon, and
    the patrol can be over an hour away; it is gathered with what comes along with it.
    """
    match priority:
        case "Critical":
            return Urgency.NOW
        case "High":
            return Urgency.GATHER
        case "Medium":
            return Urgency.PATROL
        case _:
            return None


def _rank(urgency: Urgency) -> int:
    """The order of the urgencies, most urgent first. Written as a match so that a new
    urgency is placed here rather than falling to some default."""
    match urgency:
        case Urgency.NOW:
            return 0
        case Urgency.GATHER:
            return 1
        case Urgency.PATROL:
            return 2
        case _:
            assert_never(urgency)


def _most_urgent(items: tuple[Item, ...]) -> Urgency | None:
    return min((item.urgency for item in items), key=_rank, default=None)


def _wakes_early(urgency: Urgency) -> bool:
    """Whether an item of this urgency wakes a cycle before the patrol does."""
    match urgency:
        case Urgency.NOW | Urgency.GATHER:
            return True
        case Urgency.PATROL:
            return False
        case _:
            assert_never(urgency)


def _pauses_game(item: Item) -> bool:
    """Whether the game can have paused itself on this item: only letters pause it, and only
    the kinds a player chooses to pause on, which are among those that wake a cycle early."""
    return item.source == "letter" and _wakes_early(item.urgency)


def _game_paused(reading: Reading, arrived: tuple[Item, ...], pending: tuple[Item, ...]) -> bool:
    """Whether a paused reading is the game's own pause rather than the player's or a cycle's.

    Ticks stand still while paused, so the letter the game paused on either arrives in the
    same reading or arrived on the tick the game stands on. The second is needed because
    a reading takes the state before the events: a letter can arrive between the two and
    pause the game, and only the next reading sees the pause.
    """
    if reading.speed != PAUSED:
        return False
    return (any(_pauses_game(item) for item in arrived)
            or any(_pauses_game(item) and item.tick == reading.tick for item in pending))


def _ended(items: tuple[Item, ...]) -> bool:
    return any(Note.ENDED in item.notes for item in items)


def _wake(state: State, reason: Reason, tick: int, showing: frozenset[str]) -> Step:
    signal = Signal(reason, tick, state.pending, state.notes)
    woken = replace(state, mode=Mode.WAITING, last_wake_tick=tick, pending=(),
                    notes=frozenset(), gather_since=None, known_alerts=showing)
    return Step(woken, pause=True, signal=signal)


def step(state: State, reading: Reading, patrol_ticks: int = PATROL_TICKS,
         batch_seconds: float = BATCH_SECONDS, follow_up_ticks: int = FOLLOW_UP_TICKS) -> Step:
    """Take one reading of the bridge into the state.

    A danger seen in any mode, a cycle at work among them, is kept until the all-clear has
    woken a cycle: whether a cycle saw the danger end cannot be told from here. The
    all-clear is woken even when an urgent item woke a cycle in between, for the same
    reason.
    """
    if state.mode is Mode.ENDED:
        return Step(state)

    arrived = tuple(item for item in map(classify_event, reading.events) if item is not None)
    notes = set(state.notes)
    if reading.alerts is None:
        # What was known stays known, so that alerts already seen are not taken for new
        # ones once they read again.
        notes.add(Note.ALERTS_UNREADABLE)
        showing = state.known_alerts
    else:
        arrived += alert_items(state.known_alerts, reading.alerts)
        showing = frozenset(a.type for a in reading.alerts)
    if reading.gap:
        notes.add(Note.GAP)
    if reading.reloaded:
        notes.add(Note.RELOADED)
    # A save loaded from earlier moves the tick back; the patrol counts from there.
    last_wake = min(state.last_wake_tick, reading.tick)
    danger = reading.danger != NO_DANGER
    state = replace(state, pending=state.pending + arrived, notes=frozenset(notes),
                    last_wake_tick=last_wake,
                    known_alerts=state.known_alerts | showing,
                    failing_since=None,
                    fighting=state.fighting or danger)

    if _ended(state.pending):
        signal = Signal(Reason.ENDED, reading.tick, state.pending, state.notes, stopping=True)
        return Step(replace(state, mode=Mode.ENDED, pending=(), notes=frozenset()), signal=signal)

    if reading.cycle_open:
        state = replace(state, mode=Mode.CYCLE, gather_since=None)
        return Step(state, signal=Signal(Reason.PROGRESS, reading.tick, arrived) if arrived else None)

    paused = reading.speed == PAUSED
    # The game pauses itself when a letter arrives whose kind the player chose to pause
    # on. Nothing more arrives while it stays paused, so such a letter wakes at once
    # rather than being gathered.
    game_paused = _game_paused(reading, arrived, state.pending)
    match state.mode:
        case Mode.CYCLE:
            # The cycle has looked at the game up to now, so the patrol counts from here.
            state = replace(state, last_wake_tick=reading.tick)
            # A game still standing on the tick of a letter held meanwhile has paused itself
            # on it. A cycle that saw the letter and left the pause looks the same and is
            # woken once more: that costs a cycle, and waiting would leave a raid to no one.
            if paused and not game_paused:
                return Step(replace(state, mode=Mode.WAITING))
            state = replace(state, mode=Mode.RUNNING, gather_since=None)
        case Mode.WAITING | Mode.USER_PAUSED:
            if paused:
                return Step(state)
            state = replace(state, mode=Mode.RUNNING, gather_since=None)
        case Mode.RUNNING:
            if paused and not game_paused:
                return Step(replace(state, mode=Mode.USER_PAUSED, gather_since=None))
        case Mode.ENDED:
            raise AssertionError("an ended watcher takes no readings")
        case _:
            assert_never(state.mode)

    most_urgent = _most_urgent(state.pending)
    match most_urgent:
        case Urgency.NOW:
            return _wake(state, Reason.URGENT, reading.tick, showing)
        case Urgency.GATHER:
            since = state.gather_since if state.gather_since is not None else reading.now
            if game_paused or reading.now - since >= batch_seconds:
                return _wake(state, Reason.BATCH, reading.tick, showing)
            state = replace(state, gather_since=since)
        case Urgency.PATROL | None:
            pass
        case _:
            assert_never(most_urgent)
    if state.fighting and not danger:
        return _wake(replace(state, fighting=False), Reason.ALL_CLEAR, reading.tick, showing)
    if danger and reading.tick - state.last_wake_tick >= follow_up_ticks:
        return _wake(state, Reason.FOLLOW_UP, reading.tick, showing)
    if reading.tick - state.last_wake_tick >= patrol_ticks:
        return _wake(state, Reason.PATROL, reading.tick, showing)
    return Step(state)


def bridge_failed(state: State, now: float, detail: str,
                  give_up_seconds: float = GIVE_UP_SECONDS) -> Step:
    """Take a poll that did not reach the bridge, or got an answer it could not read.

    The first failure writes a line for the player to see. A failure that has gone on for
    give_up_seconds writes the last line, and the watcher stops: a bridge that does not
    come back in that time needs someone to look at the game.
    """
    if state.mode is Mode.ENDED:
        return Step(state)
    if state.failing_since is None:
        signal = Signal(Reason.ERROR, None, detail=f"{detail} (failing for 0s)")
        return Step(replace(state, failing_since=now), signal=signal)
    failing = now - state.failing_since
    if failing < give_up_seconds:
        return Step(state)
    signal = Signal(Reason.ERROR, None, detail=f"{detail} (failing for {failing:.0f}s); the watcher stops",
                    stopping=True)
    return Step(state, signal=signal)
