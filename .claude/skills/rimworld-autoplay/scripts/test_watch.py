"""Tests of the watcher's reading, pausing, writing and keeping its place, against a
stand-in for the bridge. Run them with:

    uv run --project mcp_server pytest .claude/skills/rimworld-autoplay/scripts
"""

from __future__ import annotations

import errno
import json
import os
import time
from dataclasses import fields

import httpx
import pytest

import watch
from watch import Bridge, Watcher, main_checkout_problem, startup_problem
from watch_rules import Item, Mode, Note, State, Urgency


class FakeBridge:
    """Answers the bridge's paths from what a test sets, and records what was asked."""

    def __init__(self):
        self.tick = 1000
        self.speed = "Normal"
        self.pages: list[dict] = []
        self.alerts: list[dict] = []
        self.danger = "None"
        self.overrides: dict[str, httpx.Response] = {}
        self.refuse = False
        self.asked: list[tuple[str, str, dict]] = []

    def events_page(self, events=(), next_="g.1", more=False, gap=False, reloaded=False):
        self.pages.append({"events": list(events), "next": next_, "more": more, "gap": gap,
                           "reloaded": reloaded})

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.asked.append((request.method, path, dict(request.url.params)))
        if self.refuse:
            raise httpx.ConnectError("refused", request=request)
        if path in self.overrides:
            return self.overrides[path]
        if path == "/ping":
            return httpx.Response(200, json={"status": "pong"})
        if path == "/state":
            return httpx.Response(200, json={"tick": self.tick, "speed": self.speed})
        if path == "/events":
            page = self.pages.pop(0) if self.pages else {"events": [], "next": "g.1", "more": False,
                                                         "gap": False, "reloaded": False}
            return httpx.Response(200, json=page)
        if path == "/alerts/active":
            return httpx.Response(200, json={"alerts": self.alerts})
        if path == "/threats":
            return httpx.Response(200, json={"dangerRating": self.danger, "hostileCount": 0})
        if path == "/command/pause":
            self.speed = "Paused"
            return httpx.Response(200, json={"paused": True, "speed": "Paused"})
        return httpx.Response(404, json={"error": "Not found"})

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://bridge", transport=httpx.MockTransport(self.handle))


def raid(tick=1000):
    return {"tick": tick, "kind": "letter", "type": "ThreatBig", "label": "Raid"}


@pytest.fixture
def fake():
    return FakeBridge()


@pytest.fixture
def lines():
    return []


@pytest.fixture
def watcher(fake, lines, tmp_path):
    w = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    w.start()
    return w


def paths(fake, method="GET"):
    return [p for m, p, _ in fake.asked if m == method]


def open_mark(directory, started_at=None):
    """Keep the mark of a cycle as check_plan.py --start does."""
    started_at = time.time() if started_at is None else started_at
    (directory / watch.CYCLE_MARK).write_text(json.dumps({"started_at": started_at}) + "\n",
                                              encoding="utf-8", newline="\n")


# ── Checks before watching ─────────────────────────────────────────────────────

def git_answering(first: str, toplevel: str):
    def git(*args):
        if args[:2] == ("worktree", "list"):
            return f"worktree {first}\nHEAD abc\nbranch refs/heads/develop\n\nworktree /w/other\n"
        return toplevel + "\n"
    return git


def plan_root(tmp_path, colony="Base"):
    (tmp_path / colony).mkdir()
    (tmp_path / colony / "plan.md").write_text("plan\n", encoding="utf-8", newline="\n")
    return tmp_path


def test_all_checks_pass_in_the_main_checkout_with_a_plan(fake, tmp_path):
    problem = startup_problem(Bridge(fake.client()), "Base", plan_root(tmp_path),
                              git=git_answering("C:/repo", "C:/repo"), sleep=lambda s: None)
    assert problem is None


class Clock:
    """Time that passes only when slept, or when a test moves it on."""

    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def startup(fake, tmp_path, clock, restart=False):
    return startup_problem(Bridge(fake.client()), "Base", plan_root(tmp_path), git=git_answering("C:/repo", "C:/repo"),
                           sleep=clock.sleep, restart=restart, clock=clock)


def test_a_bridge_that_does_not_answer_is_tried_twice_then_reported(fake, tmp_path):
    fake.refuse = True
    clock = Clock()
    assert startup(fake, tmp_path, clock).startswith("the bridge does not answer")
    assert paths(fake) == ["/ping", "/ping"]
    assert clock.slept == [watch.PING_RETRY_SECONDS]


def test_a_restart_gives_the_bridge_as_long_as_a_running_watcher_does(fake, tmp_path):
    fake.refuse = True
    clock = Clock()
    assert startup(fake, tmp_path, clock, restart=True).startswith("the bridge does not answer")
    assert sum(clock.slept) == 60.0
    assert paths(fake).count("/ping") == len(clock.slept) + 1


def test_pings_that_hang_until_their_timeout_use_up_a_restarts_time(fake, tmp_path, monkeypatch):
    clock = Clock()

    def hang():
        clock.now += watch.TIMEOUT_SECONDS
        raise watch.BridgeError("GET /ping: ReadTimeout: timed out")
    monkeypatch.setattr(Bridge, "ping", lambda self: hang())
    assert startup(fake, tmp_path, clock, restart=True).startswith("the bridge does not answer")
    # A running watcher stops after a minute of failures, timeouts included.
    assert watch.GIVE_UP_SECONDS <= clock.now < watch.GIVE_UP_SECONDS + watch.TIMEOUT_SECONDS + watch.PING_RETRY_SECONDS


def test_a_restart_goes_on_once_the_bridge_answers_again(fake, tmp_path):
    fake.refuse = True
    clock = Clock()

    def wait(seconds):
        clock.sleep(seconds)
        if len(fake.asked) == 5:
            fake.refuse = False
    problem = startup_problem(Bridge(fake.client()), "Base", plan_root(tmp_path),
                              git=git_answering("C:/repo", "C:/repo"), sleep=wait, restart=True, clock=clock)
    assert problem is None


def test_a_start_with_a_kept_place_is_taken_for_a_restart(fake, monkeypatch, capsys, tmp_path):
    root = plan_root(tmp_path)
    (root / "Base" / "watch.json").write_text("{}", encoding="utf-8", newline="")
    fake.refuse = True
    clock = Clock()
    monkeypatch.setattr(watch, "PLAY_ROOT", root)
    monkeypatch.setattr(watch, "make_client", lambda url: fake.client())
    monkeypatch.setattr(watch.time, "sleep", clock.sleep)
    monkeypatch.setattr(watch.time, "monotonic", clock)
    assert watch.main(["--colony", "Base"]) == 2
    assert sum(clock.slept) == 60.0


def test_a_mod_built_without_the_games_alerts_is_named(fake, tmp_path):
    fake.overrides["/alerts/active"] = httpx.Response(404, json={"error": "Not found"})
    problem = startup_problem(Bridge(fake.client()), "Base", plan_root(tmp_path),
                              git=git_answering("C:/repo", "C:/repo"), sleep=lambda s: None)
    assert problem.startswith("the bridge has no /alerts/active")


def test_alerts_that_do_not_read_at_the_start_do_not_stop_it(fake, tmp_path):
    # Each poll notes such a failure and watches on, so a restart that meets it goes on too.
    fake.overrides["/alerts/active"] = httpx.Response(500, json={"error": "boom"})
    problem = startup_problem(Bridge(fake.client()), "Base", plan_root(tmp_path),
                              git=git_answering("C:/repo", "C:/repo"), sleep=lambda s: None)
    assert problem is None


def test_a_worktree_is_not_the_main_checkout():
    problem = main_checkout_problem(git_answering("C:/repo", "C:/worktrees/x"))
    assert problem.startswith("not the main checkout")


@pytest.mark.skipif(os.name != "nt", reason="case and separators are the same path only on Windows")
def test_the_same_checkout_written_differently_on_windows_is_the_main_one():
    assert main_checkout_problem(git_answering("C:\\Repo\\", "c:/repo")) is None


def test_the_same_checkout_written_differently_is_the_main_one():
    assert main_checkout_problem(git_answering("/home/u/repo/", "/home/u/other/../repo")) is None


def test_a_missing_plan_file_is_reported(fake, tmp_path):
    problem = startup_problem(Bridge(fake.client()), "Nowhere", tmp_path,
                              git=git_answering("C:/repo", "C:/repo"), sleep=lambda s: None)
    assert problem.startswith("no plan file")


@pytest.mark.parametrize("name", ["", "a/b", "..", ".hidden", "trailing "])
def test_a_colony_name_that_cannot_be_a_directory_is_refused(fake, tmp_path, name):
    problem = startup_problem(Bridge(fake.client()), name, tmp_path, git=git_answering("C:/r", "C:/r"),
                              sleep=lambda s: None)
    assert problem.startswith("not a usable colony name")
    assert fake.asked == []


def test_a_failed_check_writes_one_line_and_exits_2(fake, monkeypatch, capsys):
    fake.refuse = True
    monkeypatch.setattr(watch, "make_client", lambda url: fake.client())
    monkeypatch.setattr(watch.time, "sleep", lambda s: None)
    assert watch.main(["--colony", "Base"]) == 2
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    line = json.loads(out[0])
    assert line["reason"] == "error"
    assert line["detail"].startswith("startup: the bridge does not answer")
    assert line["stopping"] is True


def test_arguments_it_cannot_take_write_one_line_and_exit_2(capsys):
    with pytest.raises(SystemExit) as exited:
        watch.main(["--patrol-ticks", "soon"])
    assert exited.value.code == 2
    [out] = capsys.readouterr().out.splitlines()
    line = json.loads(out)
    assert (line["reason"], line["stopping"]) == ("error", True)
    assert line["detail"].startswith("startup: ")


@pytest.mark.parametrize("url", ["http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"])
def test_a_bridge_on_this_machine_is_taken(url):
    assert watch.bridge_url(url) == url


@pytest.mark.parametrize("url", ["http://example.com:8765", "http://192.168.0.2:8765", "http://127.0.0.1.example.com"])
def test_a_bridge_elsewhere_is_refused_before_the_token_goes(capsys, monkeypatch, url):
    monkeypatch.setattr(watch, "make_client", lambda url: pytest.fail(f"a client with the token for {url}"))
    with pytest.raises(SystemExit) as exited:
        watch.main(["--colony", "c", "--bridge", url])
    assert exited.value.code == 2
    [out] = capsys.readouterr().out.splitlines()
    line = json.loads(out)
    assert (line["reason"], line["stopping"]) == ("error", True)
    assert "the bridge must be on this machine" in line["detail"]


# ── One watcher for a colony ───────────────────────────────────────────────────

def platform_lock_call(monkeypatch, replacement):
    """Stand the given function in for the operating system's lock call."""
    if os.name == "nt":
        import msvcrt
        monkeypatch.setattr(msvcrt, "locking", replacement)
    else:
        import fcntl
        monkeypatch.setattr(fcntl, "flock", replacement)


def test_a_lock_refused_for_another_reason_than_a_holder_is_raised(tmp_path, monkeypatch):
    def no_locks(*args):
        raise OSError(errno.ENOLCK, "No locks available")
    platform_lock_call(monkeypatch, no_locks)
    with pytest.raises(OSError) as raised:
        watch.hold_lock(tmp_path / "watch.lock", wait_seconds=0, sleep=lambda s: None)
    assert raised.value.errno == errno.ENOLCK


def test_letting_the_lock_go_unlocks_it_before_closing(tmp_path, monkeypatch):
    held = watch.hold_lock(tmp_path / "watch.lock", wait_seconds=0)
    calls = []

    def unlock(fileno, *args):
        calls.append((held.closed, args))
    platform_lock_call(monkeypatch, unlock)
    watch.release_lock(held)
    if os.name == "nt":
        import msvcrt
        expected: tuple = (msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        expected = (fcntl.LOCK_UN,)
    assert calls == [(False, expected)]
    assert held.closed


def test_a_second_watcher_cannot_hold_the_lock_until_the_first_lets_it_go(tmp_path):
    first = watch.hold_lock(tmp_path / "watch.lock", wait_seconds=0)
    assert first is not None
    slept = []
    assert watch.hold_lock(tmp_path / "watch.lock", wait_seconds=3, sleep=slept.append) is None
    assert slept == [1.0, 1.0, 1.0]
    watch.release_lock(first)
    assert first.closed
    again = watch.hold_lock(tmp_path / "watch.lock", wait_seconds=0)
    assert again is not None
    watch.release_lock(again)


def test_a_lock_that_cannot_be_taken_for_another_reason_is_not_reported_as_a_watcher(fake, monkeypatch,
                                                                                        capsys, tmp_path):
    def unsupported(handle):
        raise OSError(38, "Function not implemented")
    root = plan_root(tmp_path)
    monkeypatch.setattr(watch, "_try_lock", unsupported)
    monkeypatch.setattr(watch, "PLAY_ROOT", root)
    monkeypatch.setattr(watch, "make_client", lambda url: fake.client())
    monkeypatch.setattr(watch, "startup_problem", lambda *args, **kwargs: None)
    assert watch.main(["--colony", "Base"]) == 2
    [out] = capsys.readouterr().out.splitlines()
    detail = json.loads(out)["detail"]
    assert detail.startswith("startup: cannot lock watch.lock: ")
    assert "another watcher" not in detail


def test_a_watcher_lets_its_lock_go_when_it_ends(fake, monkeypatch, capsys, tmp_path):
    root = plan_root(tmp_path)
    released = []
    real = watch.release_lock
    monkeypatch.setattr(watch, "release_lock", lambda handle: (released.append(handle), real(handle)))
    monkeypatch.setattr(watch, "PLAY_ROOT", root)
    monkeypatch.setattr(watch, "make_client", lambda url: fake.client())
    monkeypatch.setattr(watch, "startup_problem", lambda *args, **kwargs: None)
    monkeypatch.setattr(watch.Watcher, "poll", lambda self, now: False)
    assert watch.main(["--colony", "Base"]) == 0
    assert len(released) == 1 and released[0].closed


def test_a_watcher_of_a_colony_already_watched_writes_one_line_and_exits_2(fake, monkeypatch, capsys,
                                                                           tmp_path):
    root = plan_root(tmp_path)
    held = watch.hold_lock(root / "Base" / "watch.lock", wait_seconds=0)
    monkeypatch.setattr(watch, "PLAY_ROOT", root)
    monkeypatch.setattr(watch, "make_client", lambda url: fake.client())
    monkeypatch.setattr(watch, "startup_problem", lambda *args, **kwargs: None)
    monkeypatch.setattr(watch.time, "sleep", lambda s: None)
    # A watcher that got past the lock ends at its first poll rather than watch for ever.
    monkeypatch.setattr(watch.Watcher, "poll", lambda self, now: False)
    try:
        assert watch.main(["--colony", "Base"]) == 2
    finally:
        watch.release_lock(held)
    [out] = capsys.readouterr().out.splitlines()
    line = json.loads(out)
    assert line["detail"].startswith("startup: another watcher of Base is running")
    assert line["stopping"] is True
    assert not (root / "Base" / "watch.json").exists()


# ── Starting and keeping the place ─────────────────────────────────────────────

def test_a_first_start_skips_what_already_happened(fake, lines, tmp_path):
    fake.tick = 5000
    fake.events_page([raid()], next_="g.9")
    w = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    w.start()
    assert (w.cursor, w.state.last_wake_tick) == ("g.9", 5000)
    assert json.loads((tmp_path / "watch.json").read_text(encoding="utf-8"))["cursor"] == "g.9"
    assert lines == []


def test_a_restart_continues_from_the_kept_place(fake, lines, tmp_path, watcher):
    fake.events_page([raid()], next_="g.2")
    watcher.poll(0.0)
    again = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    again.start()
    again.poll(1.0)
    assert [asked[1:] for asked in fake.asked if asked[1] == "/events"][-1] == (
        "/events", {"limit": "200", "since": "g.2"})
    assert again.state.mode is watch.Mode.WAITING


# ── Watching ───────────────────────────────────────────────────────────────────

def test_a_raid_pauses_the_game_then_writes_the_line(fake, lines, watcher):
    fake.events_page([raid()], next_="g.2")
    assert watcher.poll(0.0)
    assert paths(fake, "POST") == ["/command/pause"]
    assert [line["reason"] for line in lines] == ["urgent"]
    kept = json.loads(watcher.store.read_text(encoding="utf-8"))
    assert (kept["cursor"], kept["mode"]) == ("g.2", "waiting")


def test_the_parents_mark_keeps_a_fighting_cycle_from_being_paused(fake, lines, watcher):
    fake.events_page([raid()], next_="g.2")
    watcher.poll(0.0)
    open_mark(watcher.store.parent)
    fake.speed = "Superfast"
    fake.events_page([raid(tick=1200)], next_="g.3")
    watcher.poll(1.0)
    assert paths(fake, "POST") == ["/command/pause"]
    assert [line["reason"] for line in lines] == ["urgent", "progress"]
    assert json.loads(watcher.store.read_text(encoding="utf-8"))["mode"] == "cycle"
    (watcher.store.parent / watch.CYCLE_MARK).unlink()
    watcher.poll(2.0)
    assert paths(fake, "POST") == ["/command/pause", "/command/pause"]
    assert [line["reason"] for line in lines] == ["urgent", "progress", "urgent"]


def hold_a_raid_during_a_cycle(fake, watcher, place="g.5", head="# Base\n\n"):
    """Open a cycle, hold a raid and an alert while it works, and close the mark with the
    plan keeping the place the cycle read up to (none when place is None)."""
    open_mark(watcher.store.parent)
    fake.speed = "Superfast"
    fake.events_page([raid(tick=1200)], next_="g.3")
    fake.alerts = [{"type": "RimWorld.Alert_ColonistsIdle", "label": "1 colonist idle", "priority": "Medium"}]
    watcher.poll(0.0)
    plan = head + "## 出来事の位置\n\n" + ("- next:\n" if place is None else f"- next: {place}\n- 読んだ tick: 1300\n")
    (watcher.store.parent / "plan.md").write_text(plan, encoding="utf-8", newline="\n")
    (watcher.store.parent / watch.CYCLE_MARK).unlink()
    fake.events_page([], next_="g.4")


def test_what_the_cycle_has_read_wakes_nothing_once_its_mark_closes(fake, lines, watcher):
    hold_a_raid_during_a_cycle(fake, watcher)
    fake.events_page([], next_="g.6")
    watcher.poll(1.0)
    assert [line["reason"] for line in lines] == ["progress"]
    assert [p for m, p, params in fake.asked if params.get("since") == "g.5"] == ["/events"]
    # The alert is kept: nothing tells whether the cycle looked at it.
    assert [i.source for i in watcher.state.pending] == ["alert"]


def test_the_place_is_read_from_a_plan_saved_with_a_byte_order_mark(fake, lines, watcher):
    hold_a_raid_during_a_cycle(fake, watcher, head=chr(0xFEFF))
    fake.events_page([], next_="g.6")
    watcher.poll(1.0)
    assert [line["reason"] for line in lines] == ["progress"]


def test_what_arrived_after_the_place_the_cycle_read_wakes_a_cycle(fake, lines, watcher):
    hold_a_raid_during_a_cycle(fake, watcher)
    fake.events_page([raid(tick=1200)], next_="g.6")
    watcher.poll(1.0)
    assert [line["reason"] for line in lines] == ["progress", "urgent"]


@pytest.mark.parametrize("unread", [
    {"events": [], "next": "g.6", "more": False, "gap": True, "reloaded": False},
    {"events": [], "next": "g.6", "more": False, "gap": False, "reloaded": True},
    {"next": "g.6"},
], ids=["gap", "reloaded", "unreadable"])
def test_what_is_held_is_kept_when_the_events_after_the_place_cannot_be_told(fake, lines, watcher, unread):
    hold_a_raid_during_a_cycle(fake, watcher)
    fake.pages.append(unread)
    watcher.poll(1.0)
    assert [line["reason"] for line in lines] == ["progress", "urgent"]


def test_what_is_held_is_kept_when_the_plan_keeps_no_place(fake, lines, watcher):
    hold_a_raid_during_a_cycle(fake, watcher, place=None)
    watcher.poll(1.0)
    assert [line["reason"] for line in lines] == ["progress", "urgent"]


def test_what_is_held_keeps_its_notes_and_priority_across_a_restart(fake, lines, tmp_path):
    open_mark(tmp_path)
    w = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    w.start()
    fake.events_page([{"tick": 1000, "kind": "rumour", "type": "X", "label": "x"}], gap=True)
    fake.alerts = [{"type": "RimWorld.Alert_ColonistsIdle", "label": "1 colonist idle", "priority": "Medium"}]
    assert w.poll(0.0)
    again = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    again.start()
    held = [(i.type, [n.value for n in i.notes], i.priority) for i in again.state.pending]
    assert held == [("X", ["unclassified"], None), ("RimWorld.Alert_ColonistsIdle", [], "Medium")]
    assert [n.value for n in again.state.notes] == ["gap"]


def older_place(pending=(), marks=()) -> dict:
    """watch.json as the watcher kept it while the notes were called marks."""
    return {"cursor": "g.1", "mode": "running", "last_wake_tick": 0, "pending": list(pending),
            "marks": list(marks), "known_alerts": ["RimWorld.Alert_ColonistsIdle"], "fighting": False}


def test_a_place_kept_by_an_older_watcher_that_notes_nothing_is_read(fake, lines, tmp_path):
    raid_item = {"source": "letter", "type": "ThreatBig", "label": "Raid", "urgency": "now", "marks": []}
    (tmp_path / "watch.json").write_text(json.dumps(older_place([raid_item])), encoding="utf-8", newline="")
    w = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    w.start()
    assert [(i.type, i.notes, i.priority) for i in w.state.pending] == [("ThreatBig", (), None)]
    assert w.state.known_alerts == frozenset({"RimWorld.Alert_ColonistsIdle"})


def test_watch_json_keeps_every_field_of_the_state_but_the_times():
    state = State(last_wake_tick=1234, mode=Mode.WAITING,
                  pending=(Item("letter", "PositiveEvent", "Gift", Urgency.GATHER, tick=1003),
                           Item("alert", "X", "x", Urgency.NOW, (Note.UNCLASSIFIED,), "High")),
                  notes=frozenset({Note.GAP, Note.RELOADED}), known_alerts=frozenset({"A", "B"}), fighting=True)
    data = json.loads(json.dumps(watch.dump_state(state, "g.7")))
    # The times are the process's own clock, which a new process does not share.
    assert {f.name for f in fields(State)} - {"gather_since", "failing_since"} == set(data) - {"cursor"}
    assert all(set(item) == {f.name for f in fields(Item)} for item in data["pending"])
    assert watch.load_state(data) == (state, "g.7")


def test_an_item_kept_before_the_tick_was_kept_is_read_without_it():
    state = State(last_wake_tick=0, pending=(Item("letter", "PositiveEvent", "Gift", Urgency.GATHER, tick=3),))
    data = watch.dump_state(state, "g.1")
    del data["pending"][0]["tick"]
    loaded, _ = watch.load_state(data)
    assert loaded.pending == (Item("letter", "PositiveEvent", "Gift", Urgency.GATHER),)


@pytest.mark.parametrize("place", [
    older_place(marks=["gap"]),
    older_place([{"source": "alert", "type": "X", "label": "x", "urgency": "patrol", "marks": ["High"]}]),
], ids=["signal", "item"])
def test_a_place_kept_by_an_older_watcher_with_marks_is_refused(fake, lines, tmp_path, place):
    (tmp_path / "watch.json").write_text(json.dumps(place), encoding="utf-8", newline="")
    w = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    with pytest.raises(watch.StartRefused, match="marks of an older watcher.*Remove"):
        w.start()


@pytest.mark.parametrize("content", ["{not json", json.dumps({"mode": "running"}),
                                     json.dumps({"cursor": "g.1", "mode": "running", "last_wake_tick": 0,
                                                 "pending": [], "notes": ["shiny"], "known_alerts": []})],
                         ids=["not json", "keys missing", "unknown note"])
def test_a_place_that_cannot_be_read_is_refused_with_what_to_do(fake, lines, tmp_path, content):
    (tmp_path / "watch.json").write_text(content, encoding="utf-8", newline="")
    w = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    with pytest.raises(watch.StartRefused, match="cannot be read.*Remove"):
        w.start()


def test_a_restart_during_a_cycle_goes_on_as_a_cycle(fake, lines, tmp_path):
    open_mark(tmp_path)
    w = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    w.start()
    fake.events_page([raid()])
    assert w.poll(0.0)
    assert w.state.mode is watch.Mode.CYCLE
    assert paths(fake, "POST") == []
    assert [line["reason"] for line in lines] == ["progress"]


@pytest.mark.parametrize("content, reason", [
    (lambda: {"started_at": time.time() - watch.MARK_STALE_SECONDS - 60}, "minutes ago"),
    (lambda: {"started_at": time.time() + watch.MARK_AHEAD_SECONDS + 60}, "ahead of the clock"),
    (lambda: {}, "cannot read the time"),
    (lambda: {"started_at": "soon"}, "not a number"),
])
def test_a_mark_that_cannot_stand_for_a_cycle_pauses_the_game_and_stops(fake, lines, watcher, content,
                                                                        reason):
    (watcher.store.parent / watch.CYCLE_MARK).write_text(json.dumps(content()), encoding="utf-8",
                                                          newline="\n")
    fake.speed = "Superfast"
    fake.events_page([raid()], next_="g.2")
    assert not watcher.poll(0.0)
    assert watcher.failed
    assert paths(fake, "POST") == ["/command/pause"]
    [line] = lines
    assert line["reason"] == "error"
    assert "cycle mark:" in line["detail"] and reason in line["detail"]
    # The raid is left unread, so a restart after the mark is closed wakes for it.
    assert json.loads(watcher.store.read_text(encoding="utf-8"))["cursor"] != "g.2"


def test_a_mark_within_a_cycles_time_stands(fake, lines, watcher):
    open_mark(watcher.store.parent, time.time() - watch.MARK_STALE_SECONDS + 60)
    fake.events_page([raid()])
    assert watcher.poll(0.0)
    assert not watcher.failed
    assert [line["reason"] for line in lines] == ["progress"]


def test_a_mark_closed_between_the_two_reads_is_a_cycle_that_returned(fake, lines, watcher, monkeypatch):
    open_mark(watcher.store.parent)

    def closed(mark, now):
        mark.unlink()
        return "cannot read the time kept by --start"
    monkeypatch.setattr(watch, "stale_mark", closed)
    fake.events_page([raid()])
    assert watcher.poll(0.0)
    assert [line["reason"] for line in lines] == ["urgent"]


def test_the_line_goes_out_even_when_keeping_the_place_fails(fake, lines, watcher, monkeypatch):
    def refuse(path, data):
        raise PermissionError("held by another process")
    monkeypatch.setattr(watch, "save", refuse)
    fake.events_page([raid()])
    with pytest.raises(PermissionError):
        watcher.poll(0.0)
    assert [line["reason"] for line in lines] == ["urgent"]


def test_a_fight_is_kept_so_that_a_restart_still_wakes_the_all_clear(fake, lines, tmp_path, watcher):
    fake.danger = "High"
    watcher.poll(0.0)
    assert lines == []
    assert json.loads(watcher.store.read_text(encoding="utf-8"))["fighting"] is True
    again = Watcher(Bridge(fake.client()), tmp_path / "watch.json", lines.append)
    again.start()
    fake.danger = "None"
    again.poll(1.0)
    assert [line["reason"] for line in lines] == ["all_clear"]
    assert paths(fake, "POST") == ["/command/pause"]


def test_the_events_are_read_until_the_bridge_has_no_more(fake, lines, watcher):
    fake.events_page([], next_="g.2", more=True)
    fake.events_page([raid()], next_="g.3", gap=True)
    watcher.poll(0.0)
    assert [params.get("since") for _, path, params in fake.asked if path == "/events"] == [None, "g.1", "g.2"]
    assert watcher.cursor == "g.3"
    assert lines[0]["notes"] == ["gap"]


def test_events_that_say_there_is_more_but_do_not_move_write_an_error_line(fake, lines, watcher):
    fake.events_page([], next_="g.1", more=True)
    assert watcher.poll(0.0)
    assert [line["reason"] for line in lines] == ["error"]
    assert "does not move" in lines[0]["detail"]


def test_a_quiet_poll_writes_nothing(fake, lines, watcher):
    assert watcher.poll(0.0)
    assert lines == []
    assert paths(fake, "POST") == []


def test_a_pause_that_fails_still_wakes_and_says_so(fake, lines, watcher):
    fake.events_page([raid()])
    fake.overrides["/command/pause"] = httpx.Response(200, json={"paused": False})
    watcher.poll(0.0)
    assert lines[0]["reason"] == "urgent"
    assert "pause_failed" in lines[0]["notes"]


@pytest.mark.parametrize("path, response", [
    ("/state", httpx.Response(200, json={"error": "No active map"})),
    ("/threats", httpx.Response(200, json={"hostileCount": 3})),
    ("/events", httpx.Response(200, json={"events": "nope"})),
    ("/state", httpx.Response(200, text="<h1>Bad Request</h1>")),
    ("/state", httpx.Response(200, json={"tick": "soon", "speed": "Normal"})),
])
def test_an_unexpected_answer_writes_an_error_line(fake, lines, watcher, path, response):
    fake.overrides[path] = response
    assert watcher.poll(0.0)
    assert [line["reason"] for line in lines] == ["error"]
    assert path in lines[0]["detail"]


@pytest.mark.parametrize("response", [httpx.Response(500, json={"error": "boom"}),
                                      httpx.Response(200, json={"alerts": "nope"})])
def test_alerts_that_do_not_read_keep_a_raid_from_going_unwoken(fake, lines, watcher, response):
    fake.overrides["/alerts/active"] = response
    fake.events_page([raid()])
    assert watcher.poll(0.0)
    assert [line["reason"] for line in lines] == ["urgent"]
    assert lines[0]["notes"] == ["alerts_unreadable"]


def test_the_error_line_carries_the_bridges_own_reason(fake, lines, watcher):
    fake.overrides["/state"] = httpx.Response(200, json={"error": "No active map"})
    watcher.poll(0.0)
    assert lines[0]["detail"].startswith("GET /state: No active map")


@pytest.mark.parametrize("override", [httpx.Response(200, json={"error": "y" * 500}), None],
                         ids=["the bridge's reason", "the client's error"])
def test_what_the_line_quotes_from_the_bridge_is_cut(fake, lines, watcher, monkeypatch, override):
    if override is None:
        def refuse(self, *args, **kwargs):
            raise httpx.ConnectError("y" * 500)
        monkeypatch.setattr(httpx.Client, "get", refuse)
    else:
        fake.overrides["/state"] = override
    watcher.poll(0.0)
    detail = lines[0]["detail"]
    assert "y" * 200 + "..." in detail and "y" * 201 not in detail


def test_a_bridge_that_stops_answering_writes_an_error_line(fake, lines, watcher):
    fake.refuse = True
    assert watcher.poll(0.0)
    assert [line["reason"] for line in lines] == ["error"]
    assert "stopping" not in lines[0]


def test_a_bridge_that_fails_for_a_minute_ends_the_watch_with_its_last_line(fake, lines, watcher):
    fake.refuse = True
    assert watcher.poll(0.0)
    assert watcher.poll(30.0)
    assert not watcher.poll(60.0)
    assert watcher.failed
    assert [(line["reason"], line.get("stopping")) for line in lines] == [("error", None), ("error", True)]


def test_a_signal_that_wakes_a_cycle_names_the_definition(fake, lines, watcher):
    fake.events_page([raid()])
    watcher.poll(0.0)
    assert lines[0]["agent"] == "rimworld-cycle"


def test_an_ended_game_writes_its_line_and_stops(fake, lines, watcher):
    fake.events_page([{"tick": 1000, "kind": "letter", "type": "GameEnded", "label": "Lost"}])
    assert not watcher.poll(0.0)
    assert [(line["reason"], line["stopping"]) for line in lines] == [("ended", True)]
    assert not watcher.failed
    assert paths(fake, "POST") == []


def test_a_restart_after_an_ended_game_is_refused_with_a_line(fake, monkeypatch, capsys, tmp_path):
    colony = tmp_path / ".claude" / "play" / "Base"
    colony.mkdir(parents=True)
    ended = Watcher(Bridge(fake.client()), colony / "watch.json", lambda line: None)
    ended.start()
    fake.events_page([{"tick": 1000, "kind": "letter", "type": "GameEnded", "label": "Lost"}])
    assert not ended.poll(0.0)
    monkeypatch.setattr(watch, "PLAY_ROOT", tmp_path / ".claude" / "play")
    monkeypatch.setattr(watch, "make_client", lambda url: fake.client())
    monkeypatch.setattr(watch, "startup_problem", lambda *args, **kwargs: None)
    assert watch.main(["--colony", "Base"]) == 2
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    line = json.loads(out[0])
    assert line["reason"] == "error"
    assert line["detail"] == ("startup: the last run ended with the game (.claude/play/Base/watch.json "
                              "keeps it). If this game goes on, remove .claude/play/Base/watch.json to "
                              "watch it afresh")
