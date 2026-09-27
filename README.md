# mcp-rimworld

Let an LLM control a live RimWorld game via the [Model Context Protocol](https://modelcontextprotocol.io/).

## Demo

https://github.com/user-attachments/assets/13fe8288-89c6-4997-b60b-abb8ed5c82c2

## How it works

```
mcp_server/main.py   (Python, FastMCP)
      |
      | HTTP  127.0.0.1:8080
      v
MCP/ C# mod          (runs inside RimWorld)
      |
      | main-thread queue
      v
RimWorld game APIs
```

The C# mod starts an HTTP bridge when RimWorld loads. The Python MCP server wraps every endpoint as an MCP tool so Claude (or any MCP client) can read game state and issue commands. All RimWorld API calls are routed through the main game thread — HTTP requests block on a `ManualResetEventSlim` until the next Unity frame processes them.

The bridge listens on loopback only, and it refuses any request that carries a browser's `Origin` or `Sec-Fetch-Site` header, or a `Host` other than `127.0.0.1` — `localhost` included, so address the bridge by IP. Loopback alone is not a boundary: a page open in the player's browser can reach `127.0.0.1` too, and those headers are the ones page script cannot remove. Optionally the bridge can also require a shared secret — see [Require a shared secret](#4-optional-require-a-shared-secret).

## Prerequisites

- RimWorld 1.6 (GOG or Steam)
- [.NET SDK](https://dotnet.microsoft.com/) (for building the mod)
- Python 3.14+ and [uv](https://docs.astral.sh/uv/)
- Claude Desktop or another MCP client

## Setup

### 1. Build the mod

```powershell
dotnet build MCP\Source\MCP\MCP.csproj
```

Output: `MCP\1.6\Assemblies\MCP.dll`

If RimWorld is not installed at `C:\GOG Games\RimWorld\`, point the build at your own
installation with `RimWorldDir`:

```powershell
dotnet build MCP\Source\MCP\MCP.csproj -p:RimWorldDir="C:\Program Files (x86)\Steam\steamapps\common\RimWorld"
```

Setting a `RimWorldDir` environment variable has the same effect and lets you build
without the flag. If the RimWorld assemblies are not found, the build stops with a
message naming the directory it looked in.

### 2. Symlink the mod into RimWorld (run as Administrator)

```powershell
New-Item -ItemType SymbolicLink `
  -Path "C:\GOG Games\RimWorld\Mods\MCP" `
  -Target "C:\path\to\mcp-rimworld\MCP"
```

Enable **MCP** in the RimWorld mod manager, then start a game. The HTTP bridge starts automatically on port 8080.

Requests are served only while a save is loaded, and only while the game keeps
updating. RimWorld stops updating when its window loses focus unless **Run in
background** (Options → General) is on — and an MCP client always runs in another
window. With the option off, a request sent while the game window is out of focus
waits 15 seconds and fails with `503 Game thread timeout`.

### 3. Connect the MCP server

**Dev / inspect mode:**
```powershell
cd mcp_server
uv run mcp dev main.py
```

**Install into Claude Desktop:**
```powershell
cd mcp_server
uv run mcp install main.py --name "RimWorld"
```

Verify the bridge is reachable: `curl http://127.0.0.1:8080/ping` should return `{"status":"pong"}`.

### 4. (Optional) Require a shared secret

The header checks above stop a browser, but any other program on the machine can still reach the bridge. To require a secret as well, set `RIMWORLD_MCP_TOKEN` to the same value for **both** sides — the game and the MCP server — before starting either.

**Choosing a value.** The bridge compares the whole string, so length is what makes a secret hard to guess, and any characters a header can carry will do. This prints one, run from the repository root:

```powershell
uv run --project mcp_server python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**What a secret does and does not protect.** It travels in an environment variable, which any program running as you can read — the same programs it is meant to keep out. It stops one that merely found the port open; it does not stop one that goes looking for the value. Changing it means restarting both the game and the MCP server, since each reads it once at startup. The `Origin`, `Sec-Fetch-Site` and content type checks are separate: they hold whether or not a secret is set, and setting one neither strengthens nor replaces them.

The catch is that neither side is normally started from a terminal, and a variable set in one only reaches what that terminal launches.

**For the game.** RimWorld reads the variable once at startup, and a game started from the Steam or GOG launcher inherits the launcher's environment, not your shell's. Set the variable and start the executable from that same shell:

```powershell
$env:RIMWORLD_MCP_TOKEN = "choose-your-own-value"
& "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\RimWorldWin64.exe"
```

The install folder ships a `steam_appid.txt`, so this does not bounce back through Steam. Leave Steam itself running.

**Check that it arrived**, because a game that did not get the secret does not complain — it answers every request normally, and you would be running unprotected while believing otherwise. The bridge says which mode it is in when it starts:

```powershell
Select-String -Path "$env:USERPROFILE\AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\Player.log" -Pattern "\[MCP\]"
```

Look for `Requests must carry the shared secret in X-MCP-Token.` If you see `No shared secret configured.` instead, the variable did not reach the game.

**For the MCP server.** Claude Desktop launches it, so set the variable for your user account and restart Claude Desktop; a value exported in a shell will not reach it. The Python server sends the secret as `X-MCP-Token` whenever the variable is set.

**Re-check connectivity with the secret.** The check in step 3 carries no header, so repeat it with one:

```powershell
curl.exe -i -H "X-MCP-Token: choose-your-own-value" http://127.0.0.1:8080/ping
```

A refused request answers `403` with the reason in the body, for example `{"error":"Missing or wrong X-MCP-Token"}`.

### Upgrading from an earlier version

Three behaviours changed, and none of them is announced at runtime. If you built anything against the bridge before this change, check for them:

- Responses no longer carry `Access-Control-Allow-Origin`, and the bridge refuses any request that carries `Origin` or `Sec-Fetch-Site`. A client running inside a browser can no longer reach it at all — that is the point of the change.
- A `POST` now has to say its body is JSON. Without `Content-Type: application/json` it answers `415` and nothing reaches the game. This is what keeps a page from reaching the commands even in a browser that sends neither header above: a form cannot send that media type, and asking for it from script forces a preflight, which arrives with `Origin` and is refused. The MCP server already sends the header; a hand-written `curl --data` does not, so add `-H "Content-Type: application/json"`.
- `OPTIONS` no longer answers `204`. It falls through to `405`, like any other unsupported method.

Three tools also return less by default, to save tokens. A prompt or program that read their earlier output should pass `detail=True`, which returns the bridge's answer unchanged:

- `get_animals` lists colony animals one by one without position, and every other animal as a count per race and faction. `race` lists one race's animals with ThingIDs; it takes the race label shown in that output, in the game's display language, and a race that matches nothing fails naming the races on the map.
- `get_buildings` returns `powered` as one line per kind (`count`, `poweredOn`, `powerOutput`) instead of one entry per building. `summary` and `damaged` are unchanged.
- `get_animal_training` returns, per animal, the labels of the steps `learned` and `pending` (set to be trained, not learned yet) and `bondedTo`. Position, health and each step's `defName` and flags need `detail=True`.

`get_colony_overview` is new: it returns what eight status tools return, read together.

Every tool now replies with one block of JSON text without indentation, which takes the model fewer tokens to read. A tool that returns a list used to send one content block per item, and no block at all for an empty list; it now sends the whole list as one JSON array, `[]` when empty. Nothing is sent as structured content, as before. A program that read the blocks one by one should parse the single block as JSON instead. To read a reply yourself, pass it through a JSON formatter such as `jq .`.

## What Claude can do

### Read game state

| Tool | What it returns |
|---|---|
| `get_colony_overview` | State, alerts, threats, colony totals, weather, power, recent letters and each colonist's condition, read in one round trip |
| `get_game_state` | Tick, speed, season, biome, wealth, pawn/animal/enemy counts |
| `get_pawns` | All colonists with position, health, job, skills, passions |
| `get_pawn_status` | Single colonist overview |
| `get_pawn_health` | All hediffs — injuries, diseases, implants, addictions |
| `get_pawn_needs` | Food, rest, joy, mood level, mental state |
| `get_pawn_mood` | Mood thoughts and break thresholds |
| `get_pawn_inventory` | Weapon, apparel, carried items |
| `get_pawn_backstory` | Childhood and adulthood backstories |
| `get_pawn_capacities` | Body capacity levels (sight, moving, manipulation, etc.) |
| `get_pawn_traits` | Character traits |
| `get_pawn_relations` | Social bonds and opinion scores |
| `get_pawn_work` | Work type priorities |
| `get_pawn_schedule` | 24-hour timetable |
| `get_pawn_area` | Allowed-area restriction |
| `get_pawn_psycasts` | Psyfocus, neural heat, abilities (Royalty DLC) |
| `get_pawn_genes` | Xenotype and gene list (Biotech DLC) |
| `get_animals` | Colony animals one by one, other animals counted per race; `race` lists one race with ids, `detail=True` lists all |
| `get_animal_training` | Tamed animals — learned and pending training steps, bonds; `detail=True` adds position, health and step flags |
| `get_enemies` | All hostile pawns |
| `get_threats` | Danger rating, fires, downed/mental-break colonists |
| `get_alerts` | Quick health check — food, power, fires, bleeding |
| `get_weather` | Temperature, wind, season |
| `get_fertile_cells` | Top-100 fertile map cells |
| `get_things` | Haulable items grouped by type |
| `get_buildings` | Building summary, damaged buildings, powered buildings per kind; `detail=True` lists powered buildings one by one |
| `get_designations` | Active Hunt/Mine/CutPlant designations |
| `get_power` | Generation, consumption, battery level |
| `get_rooms` | Indoor rooms — role, temp, cleanliness, impressiveness |
| `get_zones` / `list_zones` | Growing zones and stockpiles |
| `get_stockpile_contents` | Stockpile zones with contents and filters |
| `get_cell_info` | Single cell — terrain, roof, zone, things |
| `get_cells_info` | Rectangle of cells (up to 1024) |
| `list_areas` | All map areas — home, allowed, roof |
| `get_colony` | Aggregate wealth, food days, skill leaders |
| `get_colony_social` | Romantic pairs, family bonds, notable opinions |
| `get_prisoners` | Prisoners — health, mood, resistance, will |
| `get_research` | Current project and all available projects |
| `get_production` | Workbenches and their active bills |
| `get_medical` | Pawns with tendable hediffs |
| `get_traders` | Ground traders and orbital trade ships |
| `get_quests` | All quests with state and description |
| `get_ideology` | Colony ideology, memes, precepts (Ideology DLC) |
| `get_mechs` | Mechanitor bandwidth and controlled mechs (Biotech DLC) |
| `get_room_assignments` | Beds and their assigned colonists |
| `get_drug_policies` | Drug policies and colonist assignments |
| `get_apparel` | Apparel policies and colonist assignments |
| `get_corpses` | Corpses — rot progress, position |
| `get_incidents` / `get_messages` | Recent game letters |
| `get_caravans` | Player caravans on world map |
| `get_world_factions` | All factions with goodwill |
| `get_world_sites` | Faction settlements and world sites |
| `ping` | Health check |

### Issue commands

| Tool | What it does |
|---|---|
| `draft_pawn` | Draft or undraft a colonist |
| `move_pawn` | Walk to map cell (x, z) |
| `attack_target` | Attack an enemy |
| `assign_job` | Force a specific job immediately |
| `rescue_pawn` | Rescue a downed pawn to a bed |
| `equip_item` | Equip a weapon from the map |
| `assign_bed` | Assign a colonist to a bed |
| `recruit_prisoner` | Force-recruit a prisoner |
| `set_allowed_area` | Set or clear a colonist's movement area |
| `set_schedule_hour` | Change one hour of a timetable |
| `set_passion` | Set passion for a skill |
| `hunt_animal` | Designate an animal for hunting |
| `mine_cell` | Designate a cell for mining |
| `cut_plant` | Designate a plant for cutting |
| `place_blueprint` | Place a construction blueprint |
| `deconstruct` | Designate a building for deconstruction |
| `forbid_thing` | Forbid or unforbid an item |
| `add_bill` | Add a production bill to a workbench |
| `remove_bill` | Remove a bill from a workbench |
| `set_research` | Switch the active research project |
| `queue_medical_operation` | Queue a surgery on any pawn |
| `create_allowed_area` | Create a new allowed area |
| `clear_area` | Empty an allowed area |
| `delete_area` | Delete a mutable allowed area |
| `delete_zone` | Delete a growing zone or stockpile |
| `area_paint` | Add or remove cells from an allowed area |
| `set_zone_plant` | Change what a growing zone grows |
| `set_stockpile_priority` | Change stockpile priority |
| `set_stockpile_filter` | Modify what a stockpile accepts |
| `set_pause` | Pause or unpause the game |
| `set_time_speed` | Set time speed (0=paused … 4=ultrafast) |

## Project structure

```
MCP/                        C# mod (symlinked into RimWorld/Mods/)
  About/About.xml           Mod metadata
  Source/MCP/
    MCPMod.cs               Mod entry — applies Harmony, starts HTTP server
    MCPHttpServer.cs        Background HTTP listener + request queue
    PendingRequest.cs       Cross-thread DTO (ManualResetEventSlim)
    MCPGameComponent.cs     Main-thread consumer — drains queue each frame
    RequestRouter.cs        Routes paths to reader or executor
    GameStateReader.cs      All read-only queries
    CommandExecutor.cs      All mutating commands
  1.6/Assemblies/MCP.dll    Built output

mcp_server/
  main.py                   FastMCP server — all tools and resources
  shaping.py                Trims bridge answers into the tools' default output
  tests/                    pytest suite (no game needed)
  pyproject.toml            uv dependencies
```

## Development

After editing C# source, rebuild and restart RimWorld — the symlink means no copying is needed:

```powershell
dotnet build MCP\Source\MCP\MCP.csproj
```

After editing `main.py` or `shaping.py`, restart the MCP server process (or re-run `mcp dev main.py`).

The MCP server's tests run without the game, against a stand-in for the bridge. From the repository root:

```powershell
uv run --project mcp_server pytest mcp_server
```
