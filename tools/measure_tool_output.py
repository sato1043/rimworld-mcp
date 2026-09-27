"""Measure what the MCP server's tools send to the client, before and after a change.

Two copies of the server (`main.py`) are loaded side by side and run in memory, the
way an MCP client would call them. Every `get_*` tool without a required argument is
called on each. The first copy reads the running game's bridge and records every
answer, by tool; the second is given the recorded answers back. Both therefore see the
same bridge bodies, however far the game moves on between the two runs.

For each tool it reports the text sent (characters, UTF-8 bytes, content blocks) on
both sides, and whether the two outputs read as the same JSON value, types included
(`1`, `1.0` and `true` differ). Each side is read by how its own tool function answered
(see `value`), never by the other side's output. It also compares the tool
definitions the two servers list (name, description, input and output schema,
annotations), which needs no game.

It sends GET requests only, and refuses any other request a tool makes: `get_*` tools
read the game and change nothing. Each copy reads the bridge address and shared secret
from the environment, as the server does; the instrument keeps neither.

Both copies run in one interpreter. Each imports its own neighbouring modules
(`shaping` and any other file beside it), but they share the installed libraries, so a
copy that patches a library changes the other copy's run as well.

Prepare the tree before the change as its own checkout, then run with the MCP server's
environment (one command per line; they read the same in bash and PowerShell):

    git worktree add ../before <revision before the change>
    uv run --project mcp_server python tools/measure_tool_output.py --help
    uv run --project mcp_server python tools/measure_tool_output.py --before ../before/mcp_server/main.py --after mcp_server/main.py --calibrate
    uv run --project mcp_server python tools/measure_tool_output.py --before ../before/mcp_server/main.py --after mcp_server/main.py --json out.json
    git worktree remove ../before

`--json` writes the sizes and judgements per tool, and the SHA-256 of both `main.py`
files with the `mcp` version they ran on. It does not keep the texts sent.

Exit status: 0 when every tool answered the same value on both sides and the two
definitions lists match; 1 when a tool failed on either side, answered a different
value, or sent structured content on one side only, or the definitions differ (the
report says which); 2 when the instrument cannot be trusted - the calibration missed,
the two copies did not make the same requests, or a tool asked for more than a GET.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import sys
from pathlib import Path

import httpx
from mcp.shared.memory import create_connected_server_and_client_session


# ── Loading two copies of the server ──────────────────────────────────────────

def load_server(path: Path, label: str):
    """Import `main.py` at `path` as its own module, with its own neighbours."""
    folder = path.resolve().parent
    # Each copy imports the modules beside it, not the ones the other copy cached.
    local = ({p.stem for p in folder.glob("*.py")}
             | {p.name for p in folder.iterdir() if (p / "__init__.py").is_file()})
    for name in local:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(folder))
    try:
        spec = importlib.util.spec_from_file_location(f"server_{label}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(folder))
        # The loaded module keeps its own references; the next copy must not find them.
        for name in local:
            sys.modules.pop(name, None)
    return module


def use_transport(module, transport: httpx.AsyncBaseTransport) -> None:
    """Put `transport` under every client the server builds, as the tests do."""
    real = module._new_client
    module._new_client = lambda: real(transport=transport)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Recording and replaying the bridge ────────────────────────────────────────

# A kept answer: the response, or the transport error the request ended in.
Answer = tuple[int, str, bytes] | httpx.TransportError
Key = tuple[str, str, str]  # tool, method, URL


class Bridge(httpx.AsyncBaseTransport):
    """What both sides share: the tool being called, and the refusal of all but GET."""

    def __init__(self):
        self.tool = ""
        self.refused: list[str] = []

    def key(self, request: httpx.Request) -> Key:
        return (self.tool, request.method, str(request.url))

    def refuse(self, request: httpx.Request) -> httpx.Response | None:
        if request.method == "GET":
            return None
        self.refused.append(f"{self.tool}: {request.method} {request.url}")
        return httpx.Response(405, json={"error": "refused by the instrument"}, request=request)


class Recording(Bridge):
    """Pass GET requests on to `inner` and keep every answer, in order, by tool, method
    and URL.

    Several tools read the same path (the overview reads what eight others do), and the
    game moves on between them. Keying by tool hands each tool its own bodies back on
    replay, and a request that one side makes for a different tool shows up as missing.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport):
        super().__init__()
        self.inner = inner
        self.answers: dict[Key, list[Answer]] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (refused := self.refuse(request)) is not None:
            return refused
        queue = self.answers.setdefault(self.key(request), [])
        try:
            response = await self.inner.handle_async_request(request)
            body = await response.aread()
        except httpx.TransportError as error:
            # Kept, so that the other side fails the same way instead of stopping the run.
            queue.append(error)
            raise
        kind = response.headers.get("content-type", "")
        queue.append((response.status_code, kind, body))
        return httpx.Response(response.status_code, headers={"content-type": kind},
                              content=body, request=request)


class Replay(Bridge):
    """Answer with what a Recording kept, in the order it was kept.

    A request with nothing left for it, and an answer nobody asked for, both mean the
    two runs did not make the same requests.
    """

    def __init__(self, answers: dict[Key, list[Answer]]):
        super().__init__()
        self.answers = {key: list(queue) for key, queue in answers.items()}
        self.missed: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (refused := self.refuse(request)) is not None:
            return refused
        queue = self.answers.get(self.key(request))
        if not queue:
            self.missed.append(f"{self.tool}: {request.method} {request.url}")
            return httpx.Response(599, json={"error": "not recorded"}, request=request)
        answer = queue.pop(0)
        if isinstance(answer, httpx.TransportError):
            raise answer
        status, kind, body = answer
        return httpx.Response(status, headers={"content-type": kind}, content=body,
                              request=request)

    def unused(self) -> list[str]:
        return [f"{tool}: {method} {url} x{len(queue)}"
                for (tool, method, url), queue in self.answers.items() if queue]


# ── Calling the tools ─────────────────────────────────────────────────────────

def definition(tool) -> dict:
    annotations = tool.annotations.model_dump(exclude_none=True) if tool.annotations else None
    return {"description": tool.description, "inputSchema": tool.inputSchema,
            "outputSchema": tool.outputSchema, "annotations": annotations}


async def list_definitions(server) -> dict[str, dict]:
    async with create_connected_server_and_client_session(server) as session:
        tools = (await session.list_tools()).tools
    return {t.name: definition(t) for t in tools}


def argument_free_reads(definitions: dict[str, dict]) -> list[str]:
    """The tools that read the game and can be called without arguments."""
    return sorted(name for name, d in definitions.items()
                  if name.startswith("get_") and not d["inputSchema"].get("required"))


def note_returns(server) -> dict[str, type]:
    """Have every registered tool function note the type of what it returns.

    FastMCP writes a list a function returns as one block per item, and anything else
    as one block. The type says how to read that side's blocks back.
    """
    kinds: dict[str, type] = {}
    for tool in server._tool_manager.list_tools():
        fn, name = tool.fn, tool.name
        if tool.is_async:
            async def noting(*args, _fn=fn, _name=name, **kwargs):
                result = await _fn(*args, **kwargs)
                kinds[_name] = type(result)
                return result
        else:
            def noting(*args, _fn=fn, _name=name, **kwargs):
                result = _fn(*args, **kwargs)
                kinds[_name] = type(result)
                return result
        tool.fn = noting
    return kinds


async def call_tools(server, names: list[str], bridge: Bridge) -> dict[str, dict]:
    kinds = note_returns(server)
    outputs = {}
    async with create_connected_server_and_client_session(server) as session:
        for name in names:
            bridge.tool = name
            result = await session.call_tool(name, {})
            texts = [block.text for block in result.content]
            outputs[name] = {"error": result.isError, "texts": texts,
                             "structured": result.structuredContent is not None,
                             "returned_list": issubclass(kinds.get(name, object), list | tuple)}
    return outputs


def value(output: dict):
    """The JSON value a client reads from one side's blocks: one block per item when the
    tool function returned a list, otherwise the one block. An item that is not JSON is
    taken as the plain string it was sent as.

    A list of lists was flattened into blocks when written, so it cannot be read back
    and shows up as a different value.
    """
    def read(text):
        try:
            return json.loads(text)
        except ValueError:
            return text
    texts = output["texts"]
    if output["returned_list"]:
        return [read(t) for t in texts]
    return read(texts[0]) if len(texts) == 1 else texts


def canonical(v) -> str:
    """JSON text that tells `1`, `1.0` and `true` apart, as Python's == does not."""
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def size(output: dict) -> dict:
    texts = output["texts"]
    return {"chars": sum(len(t) for t in texts),
            "bytes": sum(len(t.encode("utf-8")) for t in texts),
            "blocks": len(texts)}


def compare(before: dict, after: dict) -> dict:
    row = {"before": size(before), "after": size(after),
           "error": before["error"] or after["error"],
           "structured_before": before["structured"],
           "structured_after": after["structured"]}
    if row["error"]:
        row["same_value"] = before["texts"] == after["texts"]
        return row
    row["same_value"] = canonical(value(before)) == canonical(value(after))
    return row


# ── One run ───────────────────────────────────────────────────────────────────

async def run(before_path: Path, after_path: Path, bridge: httpx.AsyncBaseTransport,
              only: list[str] | None = None) -> tuple[dict, list[str]]:
    before = load_server(before_path, "before")
    after = load_server(after_path, "after")

    defs_before = await list_definitions(before.mcp)
    defs_after = await list_definitions(after.mcp)
    changed = sorted(n for n in defs_before.keys() | defs_after.keys()
                     if defs_before.get(n) != defs_after.get(n))

    names = only or argument_free_reads(defs_before)
    recording = Recording(bridge)
    use_transport(before, recording)
    outputs_before = await call_tools(before.mcp, names, recording)
    replay = Replay(recording.answers)
    use_transport(after, replay)
    outputs_after = await call_tools(after.mcp, names, replay)

    rows = {n: compare(outputs_before[n], outputs_after[n]) for n in names}
    report = {"inputs": {"before_sha256": sha256(before_path),
                         "after_sha256": sha256(after_path),
                         "mcp": importlib.metadata.version("mcp")},
              "tools_listed": {"before": len(defs_before), "after": len(defs_after)},
              "definitions_changed": changed, "called": len(names), "rows": rows}
    problems = ([f"refused: {r}" for r in recording.refused + replay.refused]
                + [f"not recorded: {m}" for m in replay.missed]
                + [f"recorded but not asked for: {u}" for u in replay.unused()])
    return report, problems


def findings(report: dict) -> dict[str, list[str]]:
    """What makes the two sides differ, by kind."""
    rows = report["rows"]
    return {
        "failed on either side": [n for n, r in rows.items() if r["error"]],
        "different value": [n for n, r in rows.items() if not r["same_value"]],
        "structured content on one side only": [
            n for n, r in rows.items() if r["structured_before"] != r["structured_after"]],
        "definitions changed": report["definitions_changed"],
    }


def totals(rows: dict, side: str) -> dict:
    keys = ("chars", "bytes", "blocks")
    ok = [r for r in rows.values() if not r["error"]]
    return {k: sum(r[side][k] for r in ok) for k in keys}


def percent(before: int, after: int) -> str:
    return f"{(after - before) / before * 100:+.1f}%" if before else "n/a"


def names_or_none(names: list[str]) -> str:
    return ", ".join(f"`{n}`" for n in names) or "none"


def markdown(report: dict) -> str:
    rows = report["rows"]
    found = findings(report)
    differ = sum(len(v) for v in found.values())
    lines = ["verdict: " + ("same on both sides" if not differ else "the two sides differ")]
    lines += [f"{kind} ({len(names)}): {names_or_none(names)}" for kind, names in found.items()]
    lines += [
        "",
        f"tools listed: before {report['tools_listed']['before']}, "
        f"after {report['tools_listed']['after']}; tools called: {report['called']}",
        f"inputs: before {report['inputs']['before_sha256'][:12]}, "
        f"after {report['inputs']['after_sha256'][:12]}, mcp {report['inputs']['mcp']}",
        "",
        "| tool | chars before | chars after | change | bytes before | bytes after "
        "| change | blocks before | blocks after | same value |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in rows.items():
        if r["error"]:
            continue
        b, a = r["before"], r["after"]
        lines.append(f"| `{name}` | {b['chars']:,} | {a['chars']:,} | "
                     f"{percent(b['chars'], a['chars'])} | {b['bytes']:,} | {a['bytes']:,} | "
                     f"{percent(b['bytes'], a['bytes'])} | {b['blocks']} | {a['blocks']} | "
                     f"{'yes' if r['same_value'] else 'NO'} |")
    tb, ta = totals(rows, "before"), totals(rows, "after")
    lines.append(f"| total | {tb['chars']:,} | {ta['chars']:,} | "
                 f"{percent(tb['chars'], ta['chars'])} | {tb['bytes']:,} | {ta['bytes']:,} | "
                 f"{percent(tb['bytes'], ta['bytes'])} | {tb['blocks']} | {ta['blocks']} | |")
    return "\n".join(lines)


# ── Calibration ───────────────────────────────────────────────────────────────

# Bodies with sizes worked out by hand, for the two ways a server writes its answers.
# Indented, FastMCP's own: two-space indentation, one block per list item, nothing for
# an empty list. Compact: no indentation, one block. The weather changes on every read,
# as the game does, while keeping its size: 晴れ and 曇り are 2 characters and 6 bytes
# each. The overview reads /weather after get_weather has, so handing one tool the
# other's body shows up as a different value. A one-item list reads the same as its
# item in the indented form, so it shows whether a side is read by its own answer.
STUB = {"/state": {}, "/alerts": {}, "/threats": {}, "/colony": {}, "/power": {},
        "/messages": [], "/pawns": [{"id": "P1"}, {"id": "P2"}],
        "/caravans": [{"id": "C1"}]}
WEATHERS = ["晴れ", "曇り"]


def sizes(chars: int, nbytes: int, blocks: int) -> dict:
    return {"chars": chars, "bytes": nbytes, "blocks": blocks}


# Tool -> form -> sizes, or None where only the value is checked.
EXPECTED = {
    "get_weather": {"indented": sizes(21, 25, 1), "compact": sizes(16, 20, 1)},
    "get_colony_overview": None,
    "get_messages": {"indented": sizes(0, 0, 0), "compact": sizes(2, 2, 1)},
    "get_pawns": {"indented": sizes(32, 32, 2), "compact": sizes(25, 25, 1)},
    "get_caravans": {"indented": sizes(16, 16, 1), "compact": sizes(13, 13, 1)},
}


def stub() -> httpx.MockTransport:
    reads = {"weather": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/weather":
            weather = WEATHERS[reads["weather"] % len(WEATHERS)]
            reads["weather"] += 1
            return httpx.Response(200, json={"weather": weather})
        return httpx.Response(200, json=STUB[request.url.path])
    return httpx.MockTransport(handle)


async def form(path: Path) -> str:
    """How the server class in `path` writes an answer: indented or compact."""
    probe = type(load_server(path, "probe").mcp)("probe")

    @probe.tool()
    async def sample() -> dict:
        return {"a": [1]}

    async with create_connected_server_and_client_session(probe) as session:
        text = (await session.call_tool("sample", {})).content[0].text
    return "indented" if "\n" in text else "compact"


async def calibrate(before_path: Path, after_path: Path) -> tuple[list[str], bool]:
    forms = {"before": await form(before_path), "after": await form(after_path)}
    report, problems = await run(before_path, after_path, stub(), only=list(EXPECTED))
    lines, passed = [f"forms: before {forms['before']}, after {forms['after']}"], not problems
    lines += problems
    # Not part of passing: it describes the two copies, not the instrument.
    lines.append(f"tools listed: before {report['tools_listed']['before']}, after "
                 f"{report['tools_listed']['after']}; definitions changed: "
                 f"{report['definitions_changed']}")
    for name, by_form in EXPECTED.items():
        row = report["rows"][name]
        ok = row["same_value"] and not row["error"]
        if by_form is not None:
            ok = ok and (row["before"], row["after"]) == (by_form[forms["before"]],
                                                          by_form[forms["after"]])
        passed &= ok
        lines.append(f"{name}: before {row['before']} after {row['after']} "
                     f"same value {row['same_value']} -> {'ok' if ok else 'MISSED'}")
    return lines, passed


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--before", type=Path, required=True, help="main.py before the change")
    parser.add_argument("--after", type=Path, required=True, help="main.py after the change")
    parser.add_argument("--calibrate", action="store_true",
                        help="run both copies against a stub with known sizes, not the game")
    parser.add_argument("--json", type=Path,
                        help="write the sizes and judgements per tool here")
    args = parser.parse_args()
    # The servers log every request at INFO; the report is what this run is for.
    logging.disable(logging.INFO)

    if args.calibrate:
        lines, passed = asyncio.run(calibrate(args.before, args.after))
        print("\n".join(lines))
        print("calibration " + ("passed" if passed else "FAILED"))
        return 0 if passed else 2

    report, problems = asyncio.run(run(args.before, args.after, httpx.AsyncHTTPTransport()))
    if problems:
        print("measurement stopped; the instrument cannot be trusted:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 2
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                             encoding="utf-8", newline="")
    print(markdown(report))
    return 1 if any(findings(report).values()) else 0


if __name__ == "__main__":
    sys.exit(main())
