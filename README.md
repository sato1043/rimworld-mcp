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

## What Claude can do

### Read game state

| Tool | What it returns |
|---|---|
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
| `get_animals` | All animals — id, race, position, health, faction |
| `get_animal_training` | Tamed animals — training steps and bonds |
| `get_enemies` | All hostile pawns |
| `get_threats` | Danger rating, fires, downed/mental-break colonists |
| `get_alerts` | Quick health check — food, power, fires, bleeding |
| `get_weather` | Temperature, wind, season |
| `get_fertile_cells` | Top-100 fertile map cells |
| `get_things` | Haulable items grouped by type |
| `get_buildings` | Powered/damaged buildings, building summary |
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
  pyproject.toml            uv dependencies
```

## Development

After editing C# source, rebuild and restart RimWorld — the symlink means no copying is needed:

```powershell
dotnet build MCP\Source\MCP\MCP.csproj
```

After editing `main.py`, restart the MCP server process (or re-run `mcp dev main.py`).
