"""
RimWorld MCP Server
-------------------
Bridges an LLM to a running RimWorld game via the MCP mod's HTTP bridge.

Start the game first (mod auto-starts the bridge on port 8080), then run:
    uv run mcp dev main.py
or install into Claude Desktop:
    uv run mcp install main.py --name "RimWorld"
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

RIMWORLD_URL = "http://127.0.0.1:8080"

TOKEN_ENV = "RIMWORLD_MCP_TOKEN"
TOKEN_HEADER = "X-MCP-Token"

# Read once, here, rather than each time a client is built. The game reads its own
# copy once at startup, so a value changed after that takes effect on neither side;
# reading it per call would have made the two resources below disagree with every
# tool about which secret this process is using.
TOKEN = os.environ.get(TOKEN_ENV)

# The bridge gives the game thread 15 seconds and then answers 503 saying so. Waiting
# longer than that here is what lets that answer arrive: matching it would have both
# sides give up at the same moment, and the caller would see a bare read timeout
# instead of being told the game is not advancing.
REQUEST_TIMEOUT = 20.0


async def _raise_with_reason(response: httpx.Response) -> None:
    """Raise with the bridge's own reason rather than a bare status line.

    The bridge answers a refused request with 403 and a JSON body naming the
    check that refused it. httpx builds its raise_for_status() message from the
    status and the URL alone, so that reason would reach nobody: a mistyped
    secret would look exactly like a game that is not running. Raising here,
    before the response reaches the caller, covers every call site at once,
    including the two resources below, which check no status of their own.

    The raise_for_status() calls at the call sites stay. They no longer fire,
    since this runs first, but removing all of them would turn a security fix
    into a sweep across the whole file.
    """
    if response.is_success:
        return

    await response.aread()
    reason = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        reason = str(payload.get("error") or "")
    if not reason:
        reason = response.text.strip()[:200]

    detail = f": {reason}" if reason else ""
    raise httpx.HTTPStatusError(
        f"the RimWorld bridge answered {response.status_code}{detail}",
        request=response.request,
        response=response,
    )


def _new_client() -> httpx.AsyncClient:
    """A client configured to reach the bridge.

    The bridge refuses anything that looks like it came from a browser and, when
    the player set a shared secret, anything that does not carry it. Every client
    is built here so that a new call site cannot forget the secret and fail with
    a 403 that looks like the game is not running.
    """
    return httpx.AsyncClient(
        base_url=RIMWORLD_URL,
        timeout=REQUEST_TIMEOUT,
        headers={TOKEN_HEADER: TOKEN} if TOKEN else {},
        event_hooks={"response": [_raise_with_reason]},
    )


# ── Lifespan: keep a single shared httpx client ───────────────────────────────

@dataclass
class AppState:
    http: httpx.AsyncClient


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[AppState]:
    async with _new_client() as client:
        yield AppState(http=client)


mcp = FastMCP("RimWorldMCP", lifespan=lifespan, json_response=True)


# ── Helper ────────────────────────────────────────────────────────────────────

def _client(ctx: Context) -> httpx.AsyncClient:
    return ctx.request_context.lifespan_context.http


# ── Resources (application-driven, read-only snapshots) ──────────────────────

@mcp.resource("rimworld://state")
async def resource_state() -> str:
    """Current game world summary (tick, season, biome, pawn/animal/enemy counts)."""
    async with _new_client() as c:
        return (await c.get("/state")).text


@mcp.resource("rimworld://pawns")
async def resource_pawns() -> str:
    """All colonist pawns with position, health, job, and skills."""
    async with _new_client() as c:
        return (await c.get("/pawns")).text


# ── Tools: World / map overview ───────────────────────────────────────────────

@mcp.tool()
async def get_game_state(ctx: Context[ServerSession, AppState]) -> dict:
    """
    High-level summary of the current RimWorld session:
    tick, speed, season, biome, map size, colonist/animal/hostile counts, colony wealth.
    Call this first to orient yourself before issuing any commands.
    """
    r = await _client(ctx).get("/state")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_weather(ctx: Context[ServerSession, AppState]) -> dict:
    """
    Current weather, outdoor temperature (Celsius), wind speed, season, and day of year.
    """
    r = await _client(ctx).get("/weather")
    r.raise_for_status()
    return r.json()


# ── Tools: Colonists ──────────────────────────────────────────────────────────

@mcp.tool()
async def get_pawns(ctx: Context[ServerSession, AppState]) -> list:
    """
    List every colonist with: id, name, position, health (0-1), drafted state,
    current job + target, and all skill levels.
    Use pawn 'id' (ThingID) when issuing commands.
    """
    r = await _client(ctx).get("/pawns")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_status(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Overview of a single colonist: position, health, drafted state, job, and all skills.
    pawn_id can be the pawn's name or ThingID.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_health(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Detailed health report for a colonist.
    Returns all hediffs (injuries, diseases, implants, addictions) with severity,
    affected body part, bleeding status, and tendability.
    Pregnancy is flagged with gestationProgress (0-1) for animals,
    or isPregnancy=true for Biotech human pregnancy.
    Also includes overall health%, bleed rate, and pain level.
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/health")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_needs(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    All need levels for a colonist (food, rest, joy, social, beauty, comfort, etc.),
    each as a 0-1 float, plus current mood level and mental state.
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/needs")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_mood(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Mood breakdown for a colonist: current mood level (0-1), mental break thresholds
    (minor/major/extreme), current mental state if any, and every active mood thought
    with its mood offset. Use this to identify what is making a colonist unhappy.
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/mood")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_inventory(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Inventory for a colonist: equipped weapon (with ranged/melee flag and HP),
    all worn apparel with HP and layer, and items carried in their inventory.
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/inventory")
    r.raise_for_status()
    return r.json()


# ── Tools: Creatures on map ───────────────────────────────────────────────────

@mcp.tool()
async def get_animals(ctx: Context[ServerSession, AppState]) -> list:
    """
    All animals on the map: id, name, race, position, health, faction (wild/tame),
    and current activity. Use ThingID from this list for hunt_animal.
    """
    r = await _client(ctx).get("/animals")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_enemies(ctx: Context[ServerSession, AppState]) -> list:
    """
    All hostile pawns on the map: id, name, race, faction, position, health,
    equipped weapon, and current activity. Use ThingID for attack_target.
    """
    r = await _client(ctx).get("/enemies")
    r.raise_for_status()
    return r.json()


# ── Tools: Map resources ──────────────────────────────────────────────────────

@mcp.tool()
async def get_fertile_cells(ctx: Context[ServerSession, AppState]) -> list:
    """
    Top 100 most fertile map cells (fertility > 0.5), sorted descending.
    Each entry has x/z coordinates, fertility value, and terrain label.
    Use to find ideal spots before placing growing zones.
    """
    r = await _client(ctx).get("/fertility")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_things(ctx: Context[ServerSession, AppState]) -> list:
    """
    All haulable items on the map grouped by type, showing total stack counts.
    Use to check available resources: steel, wood, food, medicine, components, etc.
    Returns top 60 item types by count.
    """
    r = await _client(ctx).get("/things")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_buildings(ctx: Context[ServerSession, AppState]) -> dict:
    """
    Colony building status in three sections:
    - powered: all buildings with power components showing on/off and power output
    - damaged: buildings with HP below max
    - summary: count and damage tally grouped by building type
    Use to find unpowered buildings, damage needing repair, or to audit the base.
    """
    r = await _client(ctx).get("/buildings")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_designations(ctx: Context[ServerSession, AppState]) -> list:
    """
    All active map designations: Hunt, Mine, CutPlant, etc.
    Each entry shows designation type, target label, and map position.
    """
    r = await _client(ctx).get("/designations")
    r.raise_for_status()
    return r.json()


# ── Tools: Research ───────────────────────────────────────────────────────────

@mcp.tool()
async def get_research(ctx: Context[ServerSession, AppState]) -> dict:
    """
    Research status: current active project with progress (0-1), and all available
    projects (prerequisites met, not yet completed) sorted by tech level.
    Also returns how many total projects are completed.
    Use set_research to switch the active project.
    """
    r = await _client(ctx).get("/research")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def set_research(
    project_def: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Switch the colony's active research project.
    project_def: the defName from get_research (e.g. MicroelectronicsBasics,
    CarpetMaking, ShieldBelt, PowerArmor, ResearchBasics).
    The project must not already be completed and its prerequisites must be met.
    """
    r = await _client(ctx).post("/command/research", json={"project_def": project_def})
    r.raise_for_status()
    return r.json()


# ── Tools: Pawn orders ────────────────────────────────────────────────────────

@mcp.tool()
async def draft_pawn(
    pawn_id: str,
    drafted: bool,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Draft or undraft a colonist.
    drafted=true  -> arms the pawn for manual combat orders (move/attack).
    drafted=false -> returns the pawn to autonomous AI work.
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).post(
        "/command/draft",
        json={"pawn_id": pawn_id, "drafted": drafted},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def move_pawn(
    pawn_id: str,
    x: int,
    z: int,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Order a colonist to walk to map cell (x, z).
    Draft the pawn first for combat repositioning.
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).post(
        "/command/move",
        json={"pawn_id": pawn_id, "x": x, "z": z},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def attack_target(
    pawn_id: str,
    target_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Order a colonist to attack an enemy pawn.
    Uses ranged attack if the pawn has a ranged weapon, otherwise melee.
    Draft the pawn first for reliable targeting.
    pawn_id: colonist name or ThingID (from get_pawns).
    target_id: enemy ThingID (from get_enemies).
    """
    r = await _client(ctx).post(
        "/command/attack",
        json={"pawn_id": pawn_id, "target_id": target_id},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def assign_job(
    pawn_id: str,
    job: str,
    ctx: Context[ServerSession, AppState],
    target_id: str = "",
) -> dict:
    """
    Force a colonist to perform a specific RimWorld job immediately.
    Common JobDef defNames: HaulToCell, CleanFilth, Research, Sow, HarvestPlant,
      Warden_Chat, SocialRelax, TendPatient, Repair, Mine, CutPlant
    pawn_id: colonist name or ThingID.
    job: exact JobDef defName (case-sensitive).
    target_id: optional ThingID of the object to act on.
    """
    r = await _client(ctx).post(
        "/command/job",
        json={"pawn_id": pawn_id, "job": job, "target_id": target_id},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def rescue_pawn(
    pawn_id: str,
    target_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Order a colonist to rescue a downed pawn and carry them to a bed.
    pawn_id: the rescuer (colonist name or ThingID).
    target_id: the downed pawn to rescue (name or ThingID) — must be downed on the map.
    """
    r = await _client(ctx).post(
        "/command/rescue",
        json={"pawn_id": pawn_id, "target_id": target_id},
    )
    r.raise_for_status()
    return r.json()


# ── Tools: Map designations ───────────────────────────────────────────────────

@mcp.tool()
async def hunt_animal(
    target_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Designate an animal for hunting. Colonists with the Hunting work type will
    seek and kill it when they have time.
    target_id: ThingID of the animal (from get_animals).
    """
    r = await _client(ctx).post("/command/hunt", json={"target_id": target_id})
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def mine_cell(
    x: int,
    z: int,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Designate the mineable resource (rock, ore vein) at map cell (x, z) for mining.
    Colonists with the Mining work type will excavate it.
    """
    r = await _client(ctx).post("/command/mine", json={"x": x, "z": z})
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def cut_plant(
    ctx: Context[ServerSession, AppState],
    target_id: str = "",
    x: int = 0,
    z: int = 0,
) -> dict:
    """
    Designate a plant for cutting. Provide either target_id (plant ThingID)
    or map coordinates (x, z) where the plant stands.
    """
    r = await _client(ctx).post(
        "/command/cut",
        json={"target_id": target_id, "x": x, "z": z},
    )
    r.raise_for_status()
    return r.json()


# ── Tools: Construction ───────────────────────────────────────────────────────

@mcp.tool()
async def place_blueprint(
    def_name: str,
    x: int,
    z: int,
    ctx: Context[ServerSession, AppState],
    rotation: str = "North",
    stuff_def: str = "",
) -> dict:
    """
    Place a construction blueprint at map cell (x, z). Colonists will gather
    materials and build it automatically.
    def_name: ThingDef defName of the buildable structure.
      Examples: Wall, Door, Bed, SleepingSpot, DiningChair, TableMealSimple,
      Cooler, Heater, SolarGenerator, WindTurbine, Sandbags, TurretGun, StockpileLarge.
    rotation: North / South / East / West (default North).
    stuff_def: optional material (WoodLog, Steel, Granite, Plasteel).
      Defaults to cheapest available if omitted.
    """
    r = await _client(ctx).post(
        "/command/build",
        json={
            "def_name": def_name,
            "x": x,
            "z": z,
            "rotation": rotation,
            "stuff_def": stuff_def,
        },
    )
    r.raise_for_status()
    return r.json()


# ── Tools: Item management ────────────────────────────────────────────────────

@mcp.tool()
async def forbid_thing(
    thing_id: str,
    ctx: Context[ServerSession, AppState],
    forbidden: bool = True,
) -> dict:
    """
    Forbid or unforbid an item on the map.
    Forbidden items are ignored by colonists for hauling and use.
    thing_id: ThingID of the item.
    forbidden: true to forbid (default), false to allow again.
    """
    r = await _client(ctx).post(
        "/command/forbid",
        json={"thing_id": thing_id, "forbidden": forbidden},
    )
    r.raise_for_status()
    return r.json()


# ── Tools: Ping / game control ───────────────────────────────────────────────

@mcp.tool()
async def ping(ctx: Context[ServerSession, AppState]) -> dict:
    """Connectivity test. Returns status=pong if the bridge is reachable."""
    r = await _client(ctx).get("/ping")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def set_pause(
    paused: bool,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Pause or unpause the game.
    paused=true to pause, paused=false to resume at normal speed.
    """
    r = await _client(ctx).post("/command/pause", json={"paused": paused})
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def set_time_speed(
    speed: int,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Set RimWorld's time speed.
    speed: 0=paused, 1=normal, 2=fast, 3=superfast, 4=ultrafast.
    """
    r = await _client(ctx).post("/command/speed", json={"speed": speed})
    r.raise_for_status()
    return r.json()


# ── Tools: Deeper pawn understanding ─────────────────────────────────────────

@mcp.tool()
async def get_pawn_traits(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Character traits for a colonist (e.g. Industrious, Neurotic, Brawler).
    Each trait has its defName, display label, and degree.
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/traits")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_relations(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Social relations for a colonist: direct bonds (spouse, sibling, etc.)
    and opinion scores toward/from every other colonist (-100 to 100).
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/relations")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_work(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Work type priorities for a colonist: each work type, its priority (0=disabled,
    1=highest, 4=lowest), whether it's active, and whether the pawn is incapable of it.
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/work")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_schedule(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    24-hour timetable for a colonist showing Work / Sleep / Joy / Anything for each hour.
    pawn_id: colonist name or ThingID.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/schedule")
    r.raise_for_status()
    return r.json()


# ── Tools: Colony infrastructure ─────────────────────────────────────────────

@mcp.tool()
async def get_power(ctx: Context[ServerSession, AppState]) -> dict:
    """
    Power grid summary: total generation (W), total consumption (W), net per second,
    stored energy and battery %, and estimated hours until drained (if in deficit).
    Use to decide when to build more generators or batteries.
    """
    r = await _client(ctx).get("/power")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_rooms(ctx: Context[ServerSession, AppState]) -> list:
    """
    All indoor rooms in the colony: role (bedroom/dining/etc.), cell count,
    temperature, cleanliness, and impressiveness.
    Use to spot cold rooms, dirty rooms, or low-quality bedrooms affecting mood.
    """
    r = await _client(ctx).get("/rooms")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_zones(ctx: Context[ServerSession, AppState]) -> dict:
    """
    All map zones in two sections:
    - growing: each growing zone with plant type, cell count, plant count, average growth (0-1)
    - stockpiles: each stockpile zone with label, size, and priority
    """
    r = await _client(ctx).get("/zones")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_prisoners(ctx: Context[ServerSession, AppState]) -> list:
    """
    All prisoners in the colony: name, race, faction, health, mood, guest status,
    resistance (to recruitment), and will (ideology resistance).
    """
    r = await _client(ctx).get("/prisoners")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_colony(ctx: Context[ServerSession, AppState]) -> dict:
    """
    Aggregate colony overview:
    - colonist count and total/item/building wealth
    - estimated days of food remaining
    - skill summary: best colonist and level for each skill
    Use this for a quick colony health check.
    """
    r = await _client(ctx).get("/colony")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_threats(ctx: Context[ServerSession, AppState]) -> dict:
    """
    Current threat snapshot:
    - danger rating (None/Some/High)
    - hostile pawn count and positions
    - active fires
    - downed colonists
    - colonists in mental breaks
    Call this whenever something seems wrong or before issuing combat orders.
    """
    r = await _client(ctx).get("/threats")
    r.raise_for_status()
    return r.json()


# ── Tools: Map cells ─────────────────────────────────────────────────────────

@mcp.tool()
async def get_cell_info(
    x: int,
    z: int,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Inspect one map cell: terrain type, roofed status, temperature, fertility,
    zone, and all things present (with their ThingIDs).
    Use before placing buildings to check what's already there.
    """
    r = await _client(ctx).get(f"/cell/{x}/{z}")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_cells_info(
    x1: int,
    z1: int,
    x2: int,
    z2: int,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Inspect every cell in the rectangle (x1,z1)-(x2,z2), up to 1024 cells.
    Returns terrain, roof, zone, designations, and things for each cell.
    Useful for scouting build areas or checking a region of the map.
    """
    r = await _client(ctx).get(f"/cells/{x1}/{z1}/{x2}/{z2}")
    r.raise_for_status()
    return r.json()


# ── Tools: Areas / zones ──────────────────────────────────────────────────────

@mcp.tool()
async def list_areas(ctx: Context[ServerSession, AppState]) -> list:
    """
    All map areas: home area, allowed areas, roof areas, etc.
    Each entry has id, label, type, cell count, and whether it is mutable.
    """
    r = await _client(ctx).get("/areas")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def list_zones(ctx: Context[ServerSession, AppState]) -> dict:
    """
    All map zones: growing zones (with plant/growth info) and stockpile zones.
    Same as get_zones — use this for zone management workflows.
    """
    r = await _client(ctx).get("/zones")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def create_allowed_area(
    label: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Create a new empty allowed area with the given label.
    Returns the new area's id so you can reference it in other commands.
    """
    r = await _client(ctx).post("/command/create_area", json={"label": label})
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def clear_area(
    area_id: int,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Remove all cells from a mutable allowed area (resets it to empty).
    area_id: the numeric id from list_areas.
    """
    r = await _client(ctx).post("/command/clear_area", json={"area_id": area_id})
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def delete_area(
    area_id: int,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Permanently delete a mutable allowed area.
    area_id: the numeric id from list_areas.
    """
    r = await _client(ctx).post("/command/delete_area", json={"area_id": area_id})
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def delete_zone(
    zone_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Permanently delete a zone by its numeric ID or label.
    zone_id: the zone's ID or label string (from list_zones).
    """
    r = await _client(ctx).post("/command/delete_zone", json={"zone_id": zone_id})
    r.raise_for_status()
    return r.json()


# ── Tools: Animals ────────────────────────────────────────────────────────────

@mcp.tool()
async def get_animal_training(ctx: Context[ServerSession, AppState]) -> list:
    """
    All tamed animals with their training step status (learned/wanted),
    bond relationships to colonists, position, and health.
    """
    r = await _client(ctx).get("/animals/training")
    r.raise_for_status()
    return r.json()


# ── Tools: World map ──────────────────────────────────────────────────────────

@mcp.tool()
async def get_caravans(ctx: Context[ServerSession, AppState]) -> list:
    """
    All player-controlled caravans on the world map: name, current tile,
    whether moving, and a list of members (colonists and animals).
    """
    r = await _client(ctx).get("/caravans")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_world_factions(ctx: Context[ServerSession, AppState]) -> list:
    """
    All known factions with current goodwill (-100 to 100), relation type
    (Ally/Neutral/Hostile), and whether currently hostile.
    Sorted by goodwill descending.
    """
    r = await _client(ctx).get("/world/factions")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_world_sites(ctx: Context[ServerSession, AppState]) -> list:
    """
    All faction settlements and world sites: name, owning faction,
    world tile, and whether currently hostile to the player.
    """
    r = await _client(ctx).get("/world/sites")
    r.raise_for_status()
    return r.json()


# ── Tools: Events / status ────────────────────────────────────────────────────

@mcp.tool()
async def get_messages(ctx: Context[ServerSession, AppState]) -> list:
    """
    Recent game letters (up to 30): label and type.
    Use to review what events have occurred recently.
    """
    r = await _client(ctx).get("/messages")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_alerts(ctx: Context[ServerSession, AppState]) -> dict:
    """
    Computed alert snapshot: low food, power deficit, active fires, hostile count,
    bleeding/downed/mental-break colonists, and colonists near a mental break.
    Call this for a quick colony health check before making decisions.
    """
    r = await _client(ctx).get("/alerts")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_medical(ctx: Context[ServerSession, AppState]) -> list:
    """
    All pawns (colonists, prisoners, visitors) with tendable hediffs.
    Each entry shows who needs treatment, which hediffs need tending,
    and whether they are bleeding.
    """
    r = await _client(ctx).get("/medical")
    r.raise_for_status()
    return r.json()


# ── Tools: Production ─────────────────────────────────────────────────────────

@mcp.tool()
async def get_production(ctx: Context[ServerSession, AppState]) -> list:
    """
    All workbenches that have active bills, with each bill's label, recipe,
    and suspended status. Use get_production first to get bench_id and bill_id
    before calling add_bill or remove_bill.
    """
    r = await _client(ctx).get("/production")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def add_bill(
    bench_id: str,
    recipe_def: str,
    ctx: Context[ServerSession, AppState],
    count: int = 1,
) -> dict:
    """
    Add a production bill to a workbench.
    bench_id: ThingID of the workbench (from get_production or get_buildings).
    recipe_def: the RecipeDef defName (e.g. MakeSimpleMeal, SmeltWeapon, ButcherCorpse).
    count: number of times to repeat (default 1).
    """
    r = await _client(ctx).post(
        "/command/add_bill",
        json={"bench_id": bench_id, "recipe_def": recipe_def, "count": count},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def remove_bill(
    bench_id: str,
    bill_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Remove a bill from a workbench.
    bench_id: ThingID of the workbench.
    bill_id: the bill's unique load ID (from get_production).
    """
    r = await _client(ctx).post(
        "/command/remove_bill",
        json={"bench_id": bench_id, "bill_id": bill_id},
    )
    r.raise_for_status()
    return r.json()


# ── Tools: Colonist management ────────────────────────────────────────────────

@mcp.tool()
async def equip_item(
    pawn_id: str,
    item_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Equip a weapon from the map onto a colonist.
    The colonist's current weapon is moved to their inventory.
    pawn_id: colonist name or ThingID.
    item_id: ThingID of the weapon on the map (from get_things).
    """
    r = await _client(ctx).post(
        "/command/equip",
        json={"pawn_id": pawn_id, "item_id": item_id},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def recruit_prisoner(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Force-recruit a prisoner into the colony immediately, bypassing
    the normal resistance/recruitment roll.
    pawn_id: the prisoner's name or ThingID (from get_prisoners).
    """
    r = await _client(ctx).post("/command/recruit", json={"pawn_id": pawn_id})
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def assign_bed(
    pawn_id: str,
    bed_id: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Assign a colonist to a specific bed.
    pawn_id: colonist name or ThingID.
    bed_id: ThingID of the bed (from get_buildings or get_cell_info).
    """
    r = await _client(ctx).post(
        "/command/assign_bed",
        json={"pawn_id": pawn_id, "bed_id": bed_id},
    )
    r.raise_for_status()
    return r.json()


# ── Tools: Pawn depth (DLC-aware) ────────────────────────────────────────────

@mcp.tool()
async def get_pawn_backstory(pawn_id: str, ctx: Context[ServerSession, AppState]) -> dict:
    """Childhood and adulthood backstory for a colonist, including title and description."""
    r = await _client(ctx).get(f"/pawn/{pawn_id}/backstory")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_capacities(pawn_id: str, ctx: Context[ServerSession, AppState]) -> dict:
    """
    All body capacity levels for a colonist (manipulation, sight, moving, talking, etc.)
    each as a 0-1 float, plus an 'impaired' flag when below 1.0.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/capacities")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_psycasts(pawn_id: str, ctx: Context[ServerSession, AppState]) -> dict:
    """
    Psychic status for a colonist (requires Royalty DLC): psyfocus, neural heat,
    and all psycast abilities with cooldown status.
    Returns an error if the pawn is not a psycaster.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/psycasts")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_genes(pawn_id: str, ctx: Context[ServerSession, AppState]) -> dict:
    """
    Xenotype and gene list for a colonist (requires Biotech DLC): xenotype name,
    endogenes (inherited), and xenogenes (applied), each with active status.
    """
    r = await _client(ctx).get(f"/pawn/{pawn_id}/genes")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_pawn_area(pawn_id: str, ctx: Context[ServerSession, AppState]) -> dict:
    """Current allowed-area assignment for a colonist (unrestricted or a specific area id/label)."""
    r = await _client(ctx).get(f"/pawn/{pawn_id}/area")
    r.raise_for_status()
    return r.json()


# ── Tools: Map resources ──────────────────────────────────────────────────────

@mcp.tool()
async def get_stockpile_contents(ctx: Context[ServerSession, AppState]) -> list:
    """
    All stockpile zones with their current contents (grouped by item type),
    priority, cell count, and the top 30 allowed item defs in their filter.
    """
    r = await _client(ctx).get("/stockpiles")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_corpses(ctx: Context[ServerSession, AppState]) -> list:
    """
    All corpses on the map: pawn name, race, faction, position, rot progress, and
    whether fully desiccated. Useful for detecting mood-debuff causes.
    """
    r = await _client(ctx).get("/corpses")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_drug_policies(ctx: Context[ServerSession, AppState]) -> dict:
    """
    All defined drug policies and which policy each colonist is currently assigned to.
    """
    r = await _client(ctx).get("/drug_policies")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_room_assignments(ctx: Context[ServerSession, AppState]) -> list:
    """
    All beds that have assigned colonists: bed id, label, position, whether it is a
    prisoner bed, and the list of assigned pawn names.
    """
    r = await _client(ctx).get("/room_assignments")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_mechs(ctx: Context[ServerSession, AppState]) -> list:
    """
    Mechanitor colonists and their controlled mechs (requires Biotech DLC).
    Shows bandwidth usage and each mech's health, position, and current job.
    """
    r = await _client(ctx).get("/mechs")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_incidents(ctx: Context[ServerSession, AppState]) -> list:
    """Recent archived game letters (up to 30): label and type. Use to review past events."""
    r = await _client(ctx).get("/incidents")
    r.raise_for_status()
    return r.json()


# ── Tools: Colonist management commands ──────────────────────────────────────

@mcp.tool()
async def set_allowed_area(
    pawn_id: str,
    ctx: Context[ServerSession, AppState],
    area_id: int = -1,
) -> dict:
    """
    Set or clear a colonist's allowed movement area.
    area_id: numeric id from list_areas. Pass -1 (default) to remove restriction.
    """
    r = await _client(ctx).post("/command/set_area", json={"pawn_id": pawn_id, "area_id": area_id})
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def set_schedule_hour(
    pawn_id: str,
    hour: int,
    assignment: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Change one hour of a colonist's 24-hour timetable.
    hour: 0-23.
    assignment: Work, Sleep, Joy, or Anything.
    """
    r = await _client(ctx).post(
        "/command/set_schedule",
        json={"pawn_id": pawn_id, "hour": hour, "assignment": assignment},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def set_passion(
    pawn_id: str,
    skill_def: str,
    passion: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Set a colonist's passion level for a skill.
    skill_def: SkillDef defName (e.g. Shooting, Cooking, Crafting, Medicine).
    passion: None, Minor, or Major.
    """
    r = await _client(ctx).post(
        "/command/set_passion",
        json={"pawn_id": pawn_id, "skill_def": skill_def, "passion": passion},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def queue_medical_operation(
    pawn_id: str,
    recipe_def: str,
    ctx: Context[ServerSession, AppState],
    part_def: str = "",
) -> dict:
    """
    Queue a medical/surgical operation on any pawn (colonist, prisoner, visitor).
    recipe_def: RecipeDef defName (e.g. RemoveBodyPart, InstallProstheticLeg, TendWound).
    part_def: optional BodyPartDef defName to target a specific body part.
    """
    r = await _client(ctx).post(
        "/command/medical_op",
        json={"pawn_id": pawn_id, "recipe_def": recipe_def, "part_def": part_def},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def deconstruct(thing_id: str, ctx: Context[ServerSession, AppState]) -> dict:
    """
    Designate a player-built structure for deconstruction.
    thing_id: ThingID of the building (from get_buildings or get_cell_info).
    """
    r = await _client(ctx).post("/command/deconstruct", json={"thing_id": thing_id})
    r.raise_for_status()
    return r.json()


# ── Tools: Zone/area management commands ──────────────────────────────────────

@mcp.tool()
async def area_paint(
    area_id: int,
    x1: int, z1: int,
    x2: int, z2: int,
    ctx: Context[ServerSession, AppState],
    include: bool = True,
) -> dict:
    """
    Add or remove a rectangle of cells from a mutable allowed area.
    area_id: numeric id from list_areas (must be an allowed area, not home/roof).
    include: true to add cells, false to remove them (default true).
    """
    r = await _client(ctx).post(
        "/command/area_paint",
        json={"area_id": area_id, "x1": x1, "z1": z1, "x2": x2, "z2": z2, "include": include},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def set_zone_plant(
    zone_id: str,
    plant_def: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Change what a growing zone should grow.
    zone_id: zone label or numeric ID (from list_zones).
    plant_def: ThingDef defName of a sowable plant (e.g. Plant_Potato, Plant_Rice, Plant_Healroot).
    """
    r = await _client(ctx).post(
        "/command/set_zone_plant",
        json={"zone_id": zone_id, "plant_def": plant_def},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def set_stockpile_priority(
    zone_id: str,
    priority: str,
    ctx: Context[ServerSession, AppState],
) -> dict:
    """
    Change the priority of a stockpile zone.
    zone_id: zone label or numeric ID.
    priority: Unstored, Low, Normal, Preferred, Important, or Critical.
    """
    r = await _client(ctx).post(
        "/command/set_stockpile_priority",
        json={"zone_id": zone_id, "priority": priority},
    )
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def set_stockpile_filter(
    zone_id: str,
    action: str,
    ctx: Context[ServerSession, AppState],
    def_name: str = "",
    def_type: str = "thing",
) -> dict:
    """
    Modify what a stockpile zone accepts.
    zone_id: zone label or numeric ID.
    action: allow, disallow, or clear (removes all allowed items).
    def_name: ThingDef or ThingCategoryDef defName (e.g. MealSimple, FoodRaw, WoodLog).
    def_type: thing (default) or category.
    """
    r = await _client(ctx).post(
        "/command/set_stockpile_filter",
        json={"zone_id": zone_id, "action": action, "def_name": def_name, "def_type": def_type},
    )
    r.raise_for_status()
    return r.json()


# ── Tools: Colony social ─────────────────────────────────────────────────────

@mcp.tool()
async def get_colony_social(ctx: Context[ServerSession, AppState]) -> dict:
    """
    Colony-wide social snapshot:
    - romanticPairs: all lover/spouse/fiancee pairs among colonists
    - familyRelations: family bonds between colonists
    - notableOpinions: opinions >= +50 (close friends) or <= -20 (rivals)
    Use this to understand colony relationships at a glance.
    """
    r = await _client(ctx).get("/social")
    r.raise_for_status()
    return r.json()


# ── Tools: Apparel ────────────────────────────────────────────────────────────

@mcp.tool()
async def get_apparel(ctx: Context[ServerSession, AppState]) -> dict:
    """
    Available apparel policies and which policy each colonist is currently using.
    """
    r = await _client(ctx).get("/apparel")
    r.raise_for_status()
    return r.json()


# ── Tools: Trading / quests / ideology ───────────────────────────────────────

@mcp.tool()
async def get_traders(ctx: Context[ServerSession, AppState]) -> dict:
    """
    All available traders in two sections:
    - groundTraders: visiting trader caravans on the current map with their stock (top 20 items)
    - orbitalTraders: trade ships in orbit with trader kind and days until departure
    Use to decide whether to initiate a trade.
    """
    r = await _client(ctx).get("/traders")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_quests(ctx: Context[ServerSession, AppState]) -> dict:
    """
    All quests sorted by display order: id, name, state (Ongoing/EndedSuccess/etc.),
    whether still active, and description.
    Use to check available missions and their current status.
    """
    r = await _client(ctx).get("/quests")
    r.raise_for_status()
    return r.json()


@mcp.tool()
async def get_ideology(ctx: Context[ServerSession, AppState]) -> dict:
    """
    The colony's ideology (requires Ideology DLC): name, memes (core beliefs),
    and all precepts with their impact level.
    Returns an error if the Ideology DLC is not active.
    """
    r = await _client(ctx).get("/ideology")
    r.raise_for_status()
    return r.json()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
