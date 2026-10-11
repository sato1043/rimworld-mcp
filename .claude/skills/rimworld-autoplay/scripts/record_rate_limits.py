"""Keep a record of the plan limits the Claude Code status line is given.

The status line command receives a JSON object on standard input, and for Pro and Max
subscribers it carries rate_limits: the 5-hour and the 7-day window, each with
used_percentage (0 to 100) and resets_at (Unix seconds). Nothing else in the CLI tells an
agent how much of its plan it has used, so this script is set as the status line command
of the main checkout (the statusLine of .claude/settings.local.json) and appends what it
is given to a record:

    python <path>/record_rate_limits.py --record <record path> -- <the user's command>

A status line set for the project stands in place of the user's own, so what follows --
is the user's status line command, as a program and its arguments: after recording, it is
run on the same input, and what it prints is what the status line shows. A script is
named with the program that runs it (bash ~/.claude/statusline.sh). Without --, the
script prints nothing and the status line is empty.

The status line runs when a response arrives; set "refreshInterval": 60 in the statusLine
setting so that it also runs while the session waits, which keeps the record fresh.

It uses the standard library and usage_rules.py beside it, so any Python 3.11 or later
runs it without the MCP server's environment. It appends one JSON line when the windows
differ from the last line, or when the last line is five minutes old (--heartbeat): a
record that stops growing then means the status line has stopped, not that the usage
stands still. Input it cannot read becomes an error line rather than nothing; a 7-day
window that does not read is only left out, since no check reads it. Input without
rate_limits writes nothing: it comes before the first response of a session and for plans
without these limits.

Exit status: that of the user's command when one is given, whether or not the record was
written, since a status line command that fails is shown as nothing. Without a command,
0, or what went wrong in recording: 2 for arguments that do not read and 1 otherwise.
What goes wrong here is told on standard error, since standard output is the status line's.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys

# What a window's values must be is the reader's rule too, so the record holds nothing the
# reader would pass over.
from usage_rules import is_percent, is_unix_seconds

# The window the check reads, and the one kept beside it for a person to read.
JUDGED, BESIDE = "five_hour", "seven_day"
WINDOWS = (JUDGED, BESIDE)
# The check takes a last line older than usage_rules.RECORD_MAX_AGE for a record that has
# stopped, so unchanged windows are written again well within that age.
HEARTBEAT = datetime.timedelta(minutes=5)
# The last line is read from this much of the end of the record; a line is far shorter.
TAIL_BYTES = 4096
# The endings Windows runs a program by, where PATHEXT does not say.
PATHEXT = ".COM;.EXE;.BAT;.CMD"


def window_of(limits: dict, name: str) -> dict | None:
    """One window as the record holds it, or None when the input has none of the name."""
    window = limits.get(name)
    if window is None:
        return None
    if not isinstance(window, dict):
        raise ValueError(f"rate_limits.{name} is not an object")
    percent, resets = window.get("used_percentage"), window.get("resets_at")
    if not is_percent(percent):
        raise ValueError(f"rate_limits.{name}.used_percentage is not a percent")
    if not is_unix_seconds(resets):
        raise ValueError(f"rate_limits.{name}.resets_at is not Unix seconds")
    return {"used_percentage": percent, "resets_at": resets}


def windows_of(body: object) -> dict | None:
    """The windows to record, or None when the input carries no rate_limits.

    A window the input lacks is kept as None: the status line drops a window once its
    reset time passes, and the record should show that it went. The 7-day window is kept
    as None too when it does not read: no check reads it, and the 5-hour window beside it
    is not lost for it.
    """
    if not isinstance(body, dict):
        raise ValueError("the input is not a JSON object")
    limits = body.get("rate_limits")
    if limits is None:
        return None
    if not isinstance(limits, dict):
        raise ValueError("rate_limits is not an object")
    try:
        beside = window_of(limits, BESIDE)
    except ValueError:
        beside = None
    return {JUDGED: window_of(limits, JUDGED), BESIDE: beside}


def read_tail(record: pathlib.Path, size: int = TAIL_BYTES) -> bytes:
    try:
        with record.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - size))
            return f.read()
    except FileNotFoundError:
        return b""


def last_entry(tail: bytes) -> dict | None:
    """The last line of the record, or None when there is none to compare with.

    A line the status line cut short does not read as JSON, so it compares as none.
    """
    lines = tail.splitlines()
    if not lines:
        return None
    try:
        entry = json.loads(lines[-1])
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


def is_due(last: dict | None, windows: dict, now: datetime.datetime, heartbeat: datetime.timedelta) -> bool:
    if last is None or "error" in last:
        return True
    if any(last.get(name) != windows[name] for name in WINDOWS):
        return True
    try:
        # A time without a zone cannot be compared with now; the line is then no guide.
        return now - datetime.datetime.fromisoformat(last["time"]) >= heartbeat
    except (KeyError, TypeError, ValueError):
        return True


def append_line(record: pathlib.Path, tail: bytes, entry: dict) -> None:
    # The status line cancels a script still running when the next update comes, so the
    # last write may have stopped partway; start on a line of its own.
    lead = "\n" if tail and not tail.endswith(b"\n") else ""
    with record.open("a", encoding="utf-8", newline="") as f:
        f.write(lead + json.dumps(entry, ensure_ascii=False) + "\n")


def record_input(record: pathlib.Path, text: str, now: datetime.datetime,
                 heartbeat: datetime.timedelta = HEARTBEAT) -> None:
    stamp = now.isoformat()
    try:
        body = json.loads(text)
        windows = windows_of(body)
    except ValueError as e:
        append_line(record, read_tail(record), {"time": stamp, "error": str(e)})
        return
    if windows is None:
        return
    tail = read_tail(record)
    if not is_due(last_entry(tail), windows, now, heartbeat):
        return
    session = body.get("session_id")
    append_line(record, tail, {"time": stamp, "session_id": session if isinstance(session, str) else None}
                | windows)


def on_path(name: str) -> str | None:
    """Where the shell finds a program: along PATH, or at the path the name itself gives.

    On Windows shutil.which looks in the current directory before PATH, as cmd does and
    the shell a status line is written for does not; a file of the program's name lying
    in the checkout would be found in its place. What keeps shutil.which from looking
    there differs from one Python to the next, so there PATH is walked here: the name is
    tried with each ending of PATHEXT, and first as it stands when it has one of them. A
    PATH that names the current directory is the user's own, and says where it comes.
    """
    if os.path.dirname(name) or sys.platform != "win32":
        return shutil.which(name)
    endings = [ending for ending in (os.environ.get("PATHEXT") or PATHEXT).split(os.pathsep) if ending]
    names = [name + ending for ending in endings]
    if any(name.upper().endswith(ending.upper()) for ending in endings):
        names.insert(0, name)
    for directory in os.environ.get("PATH", os.defpath).split(os.pathsep):
        for candidate in names if directory else ():
            found = os.path.join(directory, candidate)
            if os.path.isfile(found):
                return found
    return None


def pass_on(command: list[str], raw: bytes) -> int:
    """Run the user's status line command on the input this script was given.

    Its output is not taken: it goes where this script's would, to the status line. The
    program is looked up along PATH as the shell would, since Windows itself looks in its
    system directory first and finds another bash there.
    """
    program = on_path(command[0])
    if program is None:
        print(f"record_rate_limits: cannot find {command[0]} to run; name the program that runs a "
              f"script (bash <script>)", file=sys.stderr)
        return 127
    try:
        return subprocess.run([program, *command[1:]], input=raw).returncode
    except OSError as e:
        print(f"record_rate_limits: cannot run {command[0]}: {e}", file=sys.stderr)
        return 126


def own_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", required=True, type=pathlib.Path,
                        help="the file the record is appended to")
    parser.add_argument("--heartbeat", type=float, default=HEARTBEAT.total_seconds(),
                        help="the seconds after which unchanged windows are written again; 0 writes on every run")
    return parser.parse_args(arguments)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # What follows -- is the user's command, whose own options argparse must not read.
    cut = argv.index("--") if "--" in argv else len(argv)
    users_command = argv[cut + 1:]
    code, args = 0, None
    try:
        args = own_arguments(argv[:cut])
    except SystemExit as e:
        # argparse has said its own: what is wrong with the arguments, or the help.
        code = e.code if isinstance(e.code, int) else 1
        if not users_command:
            # Nothing is to be shown, so the input is not waited for: at a terminal it has no end.
            return code
    raw = sys.stdin.buffer.read()
    if args is not None:
        # Whatever goes wrong in recording, the user's status line is still to be shown, so
        # nothing is let past here. The record cannot hold what kept it from being read or
        # written, and standard output is the status line's, so it is told on standard error.
        try:
            record_input(args.record, raw.decode("utf-8", errors="replace"),
                         datetime.datetime.now(datetime.timezone.utc), datetime.timedelta(seconds=args.heartbeat))
        except Exception as e:
            print(f"record_rate_limits: cannot keep the record: {type(e).__name__}: {e}", file=sys.stderr)
            code = 1
    if users_command:
        # Claude Code shows nothing for a status line command that fails, so with a command
        # to show, the exit status is that command's alone.
        return pass_on(users_command, raw)
    return code


if __name__ == "__main__":
    sys.exit(main())
