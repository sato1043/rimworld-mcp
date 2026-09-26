"""Measure the RimWorld MCP bridge: round-trip time and response size per endpoint.

The bridge serves every request through the game thread, once per frame, so a round
trip mixes three costs: accepting the HTTP request, waiting for the next frame, and
reading and serialising the game state. This script separates them by measuring three
kinds of request in one run:

- a GET the request guard refuses (it carries an Origin header). It is answered with
  403 before it reaches the queue, so it costs the HTTP handling alone. Each one also
  writes a warning to the game's log, which is why only a few are sent.
- GET /ping, which goes through the queue and the frame wait but reads no state.
- every other read-only GET, which adds the endpoint's own cost.

It sends GET requests only. Commands (POST) change the game and are never sent.

Run it with the MCP server's environment:

    uv run --project mcp_server python tools/measure_bridge.py --help
    uv run --project mcp_server python tools/measure_bridge.py --calibrate
    uv run --project mcp_server python tools/measure_bridge.py --json out.json
    uv run --project mcp_server python tools/measure_bridge.py --save-bodies before

Exit status: 0 when the run completed, even if some endpoints answered with an error
(those are listed separately); 1 when the instrument itself cannot be trusted - the
calibration missed, the endpoint list no longer matches the bridge's routes, or the
guard did not refuse the request meant to be refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

DEFAULT_URL = "http://127.0.0.1:8080"
TOKEN_ENV = "RIMWORLD_MCP_TOKEN"
TOKEN_HEADER = "X-MCP-Token"
TIMEOUT = 20.0  # the bridge gives up after 15 s; wait past that to see its 503

ROUTER_SOURCE = Path(__file__).resolve().parent.parent / "MCP/Source/MCP/RequestRouter.cs"

# Listed by hand rather than extracted from RequestRouter.cs: a mistake in extraction
# would shrink what is measured without saying so. The lists are compared with the
# source before measuring instead, and a difference stops the run.
PLAIN_GETS = (
    "/ping", "/state", "/pawns", "/animals", "/enemies", "/fertility", "/things",
    "/buildings", "/research", "/weather", "/designations", "/power", "/rooms",
    "/zones", "/prisoners", "/colony", "/threats", "/traders", "/quests", "/ideology",
    "/animals/training", "/caravans", "/world/factions", "/world/sites", "/messages",
    "/alerts", "/medical", "/production", "/apparel", "/areas", "/social",
    "/stockpiles", "/corpses", "/drug_policies", "/room_assignments", "/mechs",
    "/incidents",
)
PAWN_SUBPATHS = (
    "health", "needs", "mood", "inventory", "backstory", "capacities", "psycasts",
    "genes", "area", "traits", "relations", "work", "schedule",
)

# Claude's tokenizer is not available locally. Four bytes per token is a rough figure
# for English JSON; every output that uses it says it is an estimate.
BYTES_PER_TOKEN = 4

# 30 % of a frame at 60 fps (16.7 ms): fine enough to tell a frame wait apart.
CALIBRATION_TOLERANCE_MS = 5.0
CALIBRATION_DELAYS_MS = (0, 50)


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass
class Series:
    """Every timed request to one path in one mode, warm-up excluded."""
    path: str
    mode: str                      # keep-alive / new-connection / refused
    statuses: list[int] = field(default_factory=list)
    ms: list[float] = field(default_factory=list)
    body_bytes: int | None = None
    failure: str | None = None     # transport error, non-2xx, or an error body
    body: bytes | None = field(default=None, repr=False)  # the last timed response

    @property
    def median(self) -> float | None:
        return statistics.median(self.ms) if self.ms else None

    @property
    def p95(self) -> float | None:
        if not self.ms:
            return None
        ordered = sorted(self.ms)
        return ordered[math.ceil(0.95 * len(ordered)) - 1]  # nearest rank

    def summary(self) -> dict:
        fields = asdict(self)
        del fields["body"]  # bytes: saved as files by --save-bodies, not in the JSON
        return {**fields, "median_ms": self.median, "p95_ms": self.p95}


def error_in_body(body: bytes) -> str | None:
    """The bridge's error message when the body is one, else None.

    RequestRouter wraps GameStateReader.Error(...) in a 200, as {"error": ...} or as a
    list holding only such objects, so the status alone does not tell success.
    """
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    if isinstance(payload, dict) and "error" in payload:
        return str(payload["error"])
    if (isinstance(payload, list) and payload
            and all(isinstance(p, dict) and set(p) == {"error"} for p in payload)):
        return str(payload[0]["error"])
    return None


# ── Timing ────────────────────────────────────────────────────────────────────

def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    token = os.environ.get(TOKEN_ENV)
    headers = {TOKEN_HEADER: token} if token else {}
    headers.update(extra or {})
    return headers


def _timed_get(client: httpx.Client, path: str,
               headers: dict[str, str]) -> tuple[float, httpx.Response]:
    start = time.perf_counter_ns()
    response = client.get(path, headers=headers)
    elapsed_ms = (time.perf_counter_ns() - start) / 1e6
    return elapsed_ms, response


def measure(base_url: str, path: str, samples: int, mode: str,
            shared: httpx.Client | None = None,
            expect_status: int = 200,
            extra_headers: dict[str, str] | None = None) -> Series:
    """Time `samples` GETs to `path`, after one untimed warm-up request.

    keep-alive and refused reuse `shared`. new-connection builds a client per request
    and times only the request, so the client's construction is not counted but the
    TCP connection it opens is.
    """
    series = Series(path=path, mode=mode)
    headers = _headers(extra_headers)
    for i in range(samples + 1):
        try:
            if mode == "new-connection":
                with httpx.Client(base_url=base_url, timeout=TIMEOUT) as client:
                    elapsed, response = _timed_get(client, path, headers)
            else:
                assert shared is not None
                elapsed, response = _timed_get(shared, path, headers)
        except httpx.HTTPError as e:
            series.failure = f"{type(e).__name__}: {e}"
            break
        if i == 0:
            continue  # warm-up: connection set-up and first-call costs
        series.statuses.append(response.status_code)
        series.ms.append(elapsed)
        series.body_bytes = len(response.content)
        series.body = response.content
        if response.status_code != expect_status:
            series.failure = f"HTTP {response.status_code}: {response.text[:120]}"
            break
        if expect_status == 200 and (reason := error_in_body(response.content)):
            series.failure = f"error body: {reason}"
            break
    return series


# ── Endpoint list against the source ─────────────────────────────────────────

def route_differences(source: Path) -> list[str]:
    """How the hand-written lists differ from the GET routes in RequestRouter.cs."""
    text = source.read_text(encoding="utf-8")
    get_section = text[text.index("HandleGet("):text.index("HandleCellsRectPath(")]
    routes = set(re.findall(r'^\s+"(/[a-z_/]+)"\s+=>', get_section, re.MULTILINE))
    subpaths = set(re.findall(r'^\s+"([a-z]+)"\s+=> Ok\(GameStateReader\.GetPawn',
                              text, re.MULTILINE))
    problems = []
    for label, listed, found in (("GET route", set(PLAIN_GETS), routes),
                                 ("pawn sub-path", set(PAWN_SUBPATHS), subpaths)):
        problems += [f"{label} in source but not measured: {p}"
                     for p in sorted(found - listed)]
        problems += [f"{label} measured but not in source: {p}"
                     for p in sorted(listed - found)]
    return problems


# ── A run against the game ────────────────────────────────────────────────────

def _state_snapshot(client: httpx.Client) -> dict | str:
    try:
        response = client.get("/state", headers=_headers())
        return response.json()
    except (httpx.HTTPError, ValueError) as e:
        return f"unavailable: {type(e).__name__}: {e}"


def body_file_name(path: str) -> str:
    """File name for one endpoint's saved body: /animals/training -> animals__training.json.
    The pawn id is left as the literal {id}, so bodies from two saves line up by name."""
    return path.strip("/").replace("{id}", "id").replace("/", "__") + ".json"


def save_bodies(series: list[Series], directory: Path) -> int:
    """Write the last keep-alive body of each endpoint, error bodies included, since
    comparing them across a fix is the point. Returns how many files were written."""
    directory.mkdir(parents=True, exist_ok=True)
    written = 0
    for s in series:
        if s.mode == "keep-alive" and s.body is not None:
            (directory / body_file_name(s.path)).write_bytes(s.body)
            written += 1
    return written


def run(base_url: str, samples: int, refused_samples: int,
        bodies_dir: Path | None = None) -> tuple[dict, list[str]]:
    problems = route_differences(ROUTER_SOURCE)
    if problems:
        return {}, problems

    series: list[Series] = []
    with httpx.Client(base_url=base_url, timeout=TIMEOUT) as client:
        before = _state_snapshot(client)

        refused = measure(base_url, "/ping", refused_samples, "refused", client,
                          expect_status=403,
                          extra_headers={"Origin": "http://measure-bridge.invalid"})
        series.append(refused)
        if refused.failure and not refused.statuses:
            problems.append(f"the bridge did not answer at {base_url}; is the game "
                            f"running with the mod enabled? {refused.failure}")
            return {}, problems
        if refused.failure:
            problems.append("the guard did not refuse the Origin request, so the HTTP "
                            f"cost cannot be separated: {refused.failure}")
            return {}, problems

        for path in PLAIN_GETS:
            series.append(measure(base_url, path, samples, "keep-alive", client))

        pawn_id = None
        try:
            pawns = client.get("/pawns", headers=_headers()).json()
            if isinstance(pawns, list) and pawns and "id" in pawns[0]:
                pawn_id = str(pawns[0]["id"])
        except (httpx.HTTPError, ValueError):
            pass  # reported below as the pawn rows not being measured
        for sub in ("",) + PAWN_SUBPATHS:
            path = "/pawn/{id}" + (f"/{sub}" if sub else "")
            if pawn_id is None:
                series.append(Series(path=path, mode="keep-alive",
                                     failure="not measured: no colonist id from /pawns"))
                continue
            measured = measure(base_url, path.replace("{id}", pawn_id), samples,
                               "keep-alive", client)
            measured.path = path
            series.append(measured)

        for path in ("/ping", "/state"):
            series.append(measure(base_url, path, samples, "new-connection"))

        after = _state_snapshot(client)

    script = Path(__file__).read_bytes()
    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": base_url,
        "samples_per_series": samples,
        "refused_samples": refused_samples,
        "bytes_per_token_estimate": BYTES_PER_TOKEN,
        "script_sha256": hashlib.sha256(script).hexdigest()[:12],
        "pawn_id": pawn_id,
        "state_before": before,
        "state_after": after,
        "series": [s.summary() for s in series],
    }
    if bodies_dir is not None:
        report["bodies_saved"] = save_bodies(series, bodies_dir)
    return report, problems


def markdown(report: dict) -> str:
    def cell(value: float | None) -> str:
        return "-" if value is None else f"{value:.1f}"

    lines = [
        f"measured {report['measured_at']}, {report['samples_per_series']} samples per "
        f"series after one warm-up, script {report['script_sha256']}",
        "",
        "| path | mode | n | median ms | p95 ms | bytes | ~tokens (bytes/4) | failure |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in report["series"]:
        size = s["body_bytes"]
        tokens = "-" if size is None else str(round(size / BYTES_PER_TOKEN))
        failure = (s["failure"] or "").replace("|", "/")  # a bar would split the row
        lines.append(
            f"| `{s['path']}` | {s['mode']} | {len(s['ms'])} | {cell(s['median_ms'])} "
            f"| {cell(s['p95_ms'])} | {'-' if size is None else size} | {tokens} "
            f"| {failure} |")
    failed = [s for s in report["series"] if s["failure"]]
    lines += ["", f"series: {len(report['series'])}, with a failure: {len(failed)}"]
    return "\n".join(lines)


# ── Calibration against a stub with a known delay ─────────────────────────────

class _DelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, as the bridge's HttpListener does
    extra_delay_ms = 0.0

    def do_GET(self) -> None:
        delay_ms = float(self.path.rsplit("/", 1)[-1]) + self.extra_delay_ms
        time.sleep(delay_ms / 1000)
        body = b'{"status":"pong"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass  # keep the calibration output to the results


def calibrate(samples: int, extra_delay_ms: float = 0.0) -> tuple[list[str], bool]:
    """Measure a stub whose delay is known. `extra_delay_ms` exists to break it on
    purpose: a stub slower than its path says must make the calibration fail."""
    handler = type("Handler", (_DelayHandler,), {"extra_delay_ms": extra_delay_ms})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    lines, passed = [], True
    try:
        with httpx.Client(base_url=base_url, timeout=TIMEOUT) as client:
            for delay in CALIBRATION_DELAYS_MS:
                s = measure(base_url, f"/delay/{delay}", samples, "keep-alive", client)
                if s.failure or s.median is None:
                    lines.append(f"delay {delay} ms: FAILED {s.failure}")
                    passed = False
                    continue
                error = s.median - delay
                ok = abs(error) <= CALIBRATION_TOLERANCE_MS
                passed &= ok
                lines.append(f"delay {delay} ms: median {s.median:.2f} ms, "
                             f"p95 {s.p95:.2f} ms, error {error:+.2f} ms "
                             f"(tolerance {CALIBRATION_TOLERANCE_MS} ms) "
                             f"{'ok' if ok else 'OUT OF TOLERANCE'}")
    finally:
        server.shutdown()
        server.server_close()
    return lines, passed


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--samples", type=int, default=20,
                        help="timed requests per series, after one warm-up")
    parser.add_argument("--refused-samples", type=int, default=5,
                        help="refused requests; each writes a warning to the game's log")
    parser.add_argument("--calibrate", action="store_true",
                        help="measure a local stub with a known delay instead of the game")
    parser.add_argument("--json", type=Path, help="write the raw results here")
    parser.add_argument("--save-bodies", type=Path, metavar="DIR",
                        help="write each endpoint's last response body into DIR, "
                             "to compare two runs with a directory diff")
    args = parser.parse_args()

    if args.calibrate:
        lines, passed = calibrate(args.samples)
        print("\n".join(lines))
        print("calibration " + ("passed" if passed else "FAILED"))
        return 0 if passed else 1

    report, problems = run(args.url, args.samples, args.refused_samples,
                           args.save_bodies)
    if problems:
        print("measurement stopped; the instrument cannot be trusted:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                             encoding="utf-8", newline="")
    print(markdown(report))
    if args.save_bodies:
        print(f"bodies saved: {report['bodies_saved']} files in {args.save_bodies}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
