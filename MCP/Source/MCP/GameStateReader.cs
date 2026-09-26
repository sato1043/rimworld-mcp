using System;
using System.Collections.Generic;
using System.Linq;
using RimWorld;
using Verse;

namespace MCP
{
    internal static class GameStateReader
    {
        // ── World / map overview ──────────────────────────────────────────────

        public static object GetWorldState()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            return new
            {
                tick          = Find.TickManager.TicksGame,
                speed         = Find.TickManager.CurTimeSpeed.ToString(),
                season        = GenLocalDate.Season(map).ToString(),
                biome         = map.Biome.label,
                mapSize       = new { x = map.Size.x, z = map.Size.z },
                colonistCount = map.mapPawns.FreeColonistsSpawned.Count(),
                animalCount   = map.mapPawns.AllPawnsSpawned.Count(p => p.RaceProps.Animal && p.Spawned),
                hostileCount  = map.mapPawns.AllPawnsSpawned.Count(p =>
                    p.Spawned && !p.Dead && p.HostileTo(Faction.OfPlayer)),
                wealth        = map.wealthWatcher.WealthTotal
            };
        }

        // ── Colonist lists ────────────────────────────────────────────────────

        public static List<object> GetColonists()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };
            return map.mapPawns.FreeColonistsSpawned.Select(SerializePawn).ToList();
        }

        public static object GetPawn(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            return pawn == null ? Error($"Pawn '{id}' not found") : SerializePawn(pawn);
        }

        // ── Deep pawn sub-endpoints ───────────────────────────────────────────

        public static object GetPawnHealth(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var hediffs = pawn.health.hediffSet.hediffs
                .Select(h =>
                {
                    var entry = new Dictionary<string, object>
                    {
                        ["label"]    = h.def.label,
                        ["defName"]  = h.def.defName,
                        ["severity"] = (float)Math.Round(h.Severity, 3),
                        ["part"]     = h.Part?.Label ?? "whole body",
                        ["isBad"]    = h.def.isBad,
                        ["bleeding"] = h.Bleeding,
                        ["tendable"] = h.TendableNow()
                    };
                    // Animal pregnancy
                    if (h is Hediff_Pregnant preg)
                        entry["gestationProgress"] = (float)Math.Round(preg.GestationProgress, 3);
                    // Biotech human pregnancy — detected by def name
                    else if (h.def.defName.IndexOf("Pregnan", StringComparison.OrdinalIgnoreCase) >= 0)
                        entry["isPregnancy"] = true;
                    return (object)entry;
                })
                .ToList();

            return new
            {
                pawn      = pawn.Name.ToStringShort,
                health    = (float)Math.Round(pawn.health.summaryHealth.SummaryHealthPercent, 2),
                dead      = pawn.Dead,
                downed    = pawn.Downed,
                bleeding  = pawn.health.hediffSet.BleedRateTotal > 0,
                bleedRate = (float)Math.Round(pawn.health.hediffSet.BleedRateTotal, 3),
                pain      = (float)Math.Round(pawn.health.hediffSet.PainTotal, 3),
                hediffs
            };
        }

        public static object GetPawnNeeds(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var needs = pawn.needs?.AllNeeds?
                .Select(n => (object)new
                {
                    defName = n.def.defName,
                    label   = n.def.label,
                    level   = (float)Math.Round(n.CurLevelPercentage, 3)
                })
                .ToList() ?? new List<object>();

            return new
            {
                pawn          = pawn.Name.ToStringShort,
                needs,
                mood          = (float)Math.Round(pawn.needs?.mood?.CurLevelPercentage ?? 0f, 3),
                mentalState   = pawn.MentalStateDef?.label ?? "none",
                inMentalState = pawn.InMentalState
            };
        }

        public static object GetPawnMood(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var thoughts = pawn.needs?.mood?.thoughts?.memories?.Memories?
                .Select(t => (object)new
                {
                    label  = t.def.label,
                    offset = t.MoodOffset()
                })
                .ToList() ?? new List<object>();

            var breaker = pawn.mindState?.mentalBreaker;
            return new
            {
                pawn           = pawn.Name.ToStringShort,
                moodLevel      = (float)Math.Round(pawn.needs?.mood?.CurLevelPercentage ?? 0f, 3),
                minorBreakAt   = breaker?.BreakThresholdMinor ?? 0f,
                majorBreakAt   = breaker?.BreakThresholdMajor ?? 0f,
                extremeBreakAt = breaker?.BreakThresholdExtreme ?? 0f,
                mentalState    = pawn.MentalStateDef?.label ?? "none",
                inMentalState  = pawn.InMentalState,
                thoughts
            };
        }

        public static object GetPawnInventory(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var carried = pawn.inventory?.innerContainer?
                .Select(t => (object)new { id = t.ThingID, label = t.def.label, count = t.stackCount })
                .ToList() ?? new List<object>();

            var apparel = pawn.apparel?.WornApparel?
                .Select(a => (object)new
                {
                    id    = a.ThingID,
                    label = a.def.label,
                    hp    = a.HitPoints,
                    maxHp = a.MaxHitPoints,
                    layer = a.def.apparel?.LastLayer.ToString() ?? "unknown"
                })
                .ToList() ?? new List<object>();

            var weapon = pawn.equipment?.Primary;
            return new
            {
                pawn      = pawn.Name.ToStringShort,
                weapon    = weapon == null ? null : (object)new
                {
                    id     = weapon.ThingID,
                    label  = weapon.def.label,
                    ranged = weapon.def.IsRangedWeapon,
                    hp     = weapon.HitPoints,
                    maxHp  = weapon.MaxHitPoints
                },
                apparel,
                inventory = carried
            };
        }

        // ── Animals / enemies ─────────────────────────────────────────────────

        public static List<object> GetAnimals()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };
            return map.mapPawns.AllPawnsSpawned
                .Where(p => p.RaceProps.Animal && p.Spawned && !p.Dead)
                .Select(p => (object)new
                {
                    id       = p.ThingID,
                    name     = p.LabelShort,
                    race     = p.def.label,
                    position = Pos(p),
                    health   = (float)Math.Round(p.health.summaryHealth.SummaryHealthPercent, 2),
                    faction  = p.Faction?.Name ?? "wild",
                    tame     = p.Faction == Faction.OfPlayer,
                    job      = JobLabel(p)
                })
                .ToList();
        }

        public static List<object> GetEnemies()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };
            return map.mapPawns.AllPawnsSpawned
                .Where(p => p.Spawned && !p.Dead && p.HostileTo(Faction.OfPlayer))
                .Select(p => (object)new
                {
                    id       = p.ThingID,
                    name     = p.LabelShort,
                    race     = p.def.label,
                    faction  = p.Faction?.Name ?? "unknown",
                    position = Pos(p),
                    health   = (float)Math.Round(p.health.summaryHealth.SummaryHealthPercent, 2),
                    job      = JobLabel(p),
                    weapon   = p.equipment?.Primary?.def.label ?? "none"
                })
                .ToList();
        }

        // ── Map resources ─────────────────────────────────────────────────────

        public static List<object> GetFertilityMap()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.AllCells
                .Select(c => new { cell = c, f = map.fertilityGrid.FertilityAt(c) })
                .Where(x => x.f > 0.5f)
                .OrderByDescending(x => x.f)
                .Take(100)
                .Select(x => (object)new
                {
                    x         = x.cell.x,
                    z         = x.cell.z,
                    fertility = (float)Math.Round(x.f, 2),
                    terrain   = map.terrainGrid.TerrainAt(x.cell)?.label ?? "unknown"
                })
                .ToList();
        }

        public static List<object> GetThings()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.listerThings.ThingsInGroup(ThingRequestGroup.HaulableEver)
                .Where(t => t.Spawned && !t.def.IsCorpse)
                .GroupBy(t => t.def.defName)
                .Select(g => new
                {
                    defName    = g.Key,
                    label      = g.First().def.label,
                    totalCount = g.Sum(t => t.stackCount),
                    stacks     = g.Count()
                })
                .OrderByDescending(x => x.totalCount)
                .Take(60)
                .Select(x => (object)x)
                .ToList();
        }

        public static object GetBuildings()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            var all = map.listerBuildings.allBuildingsColonist;

            var powered = all
                .Select(b => new { b, pt = b.TryGetComp<CompPowerTrader>() })
                .Where(x => x.pt != null)
                .Select(x => (object)new
                {
                    id          = x.b.ThingID,
                    label       = x.b.def.label,
                    defName     = x.b.def.defName,
                    position    = new { x = x.b.Position.x, z = x.b.Position.z },
                    hp          = x.b.HitPoints,
                    maxHp       = x.b.MaxHitPoints,
                    powered     = x.pt.PowerOn,
                    powerOutput = (float)Math.Round(x.pt.PowerOutput, 1)
                })
                .ToList();

            var damaged = all
                .Where(b => b.HitPoints < b.MaxHitPoints)
                .Select(b => (object)new
                {
                    id       = b.ThingID,
                    label    = b.def.label,
                    position = new { x = b.Position.x, z = b.Position.z },
                    hp       = b.HitPoints,
                    maxHp    = b.MaxHitPoints,
                    pct      = (float)Math.Round((float)b.HitPoints / b.MaxHitPoints, 2)
                })
                .ToList();

            var summary = all
                .GroupBy(b => b.def.defName)
                .Select(g => new
                {
                    defName = g.Key,
                    label   = g.First().def.label,
                    count   = g.Count(),
                    damaged = g.Count(b => b.HitPoints < b.MaxHitPoints)
                })
                .OrderByDescending(x => x.count)
                .Select(x => (object)x)
                .ToList();

            return new { powered, damaged, summary };
        }

        public static object GetResearch()
        {
            var mgr     = Find.ResearchManager;
            var current = DefDatabase<ResearchProjectDef>.AllDefsListForReading
                .FirstOrDefault(p => mgr.IsCurrentProject(p));

            var available = DefDatabase<ResearchProjectDef>.AllDefsListForReading
                .Where(p => !p.IsFinished && p.PrerequisitesCompleted)
                .Select(g => new
                {
                    defName   = g.defName,
                    label     = g.label,
                    progress  = (float)Math.Round(mgr.GetProgress(g) / g.baseCost, 3),
                    cost      = g.baseCost,
                    techLevel = g.techLevel.ToString()
                })
                .OrderBy(x => x.techLevel)
                .Select(x => (object)x)
                .ToList();

            var completedCount = DefDatabase<ResearchProjectDef>.AllDefsListForReading
                .Count(p => p.IsFinished);

            return new
            {
                current = current == null ? null : (object)new
                {
                    defName  = current.defName,
                    label    = current.label,
                    progress = (float)Math.Round(mgr.GetProgress(current) / current.baseCost, 3),
                    cost     = current.baseCost
                },
                available,
                completedCount
            };
        }

        public static object GetWeather()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            return new
            {
                weather     = map.weatherManager.curWeather.label,
                outdoorTemp = (float)Math.Round(map.mapTemperature.OutdoorTemp, 1),
                windSpeed   = (float)Math.Round(map.windManager.WindSpeed, 2),
                season      = GenLocalDate.Season(map).ToString(),
                dayOfYear   = GenLocalDate.DayOfYear(map)
            };
        }

        public static List<object> GetDesignations()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.designationManager.AllDesignations
                .Select(d =>
                {
                    int px, pz;
                    string target;
                    if (d.target.HasThing && d.target.Thing != null)
                    {
                        px     = d.target.Thing.Position.x;
                        pz     = d.target.Thing.Position.z;
                        target = d.target.Thing.LabelShort;
                    }
                    else
                    {
                        px     = d.target.Cell.x;
                        pz     = d.target.Cell.z;
                        target = "cell";
                    }
                    return (object)new { type = d.def.defName, target, position = new { x = px, z = pz } };
                })
                .ToList();
        }

        // ── Pawn character ────────────────────────────────────────────────────

        public static object GetPawnTraits(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var traits = pawn.story?.traits?.allTraits?
                .Select(t => (object)new
                {
                    defName = t.def.defName,
                    label   = t.Label,
                    degree  = t.Degree
                })
                .ToList() ?? new List<object>();

            return new { pawn = pawn.Name.ToStringShort, traits };
        }

        public static object GetPawnRelations(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var direct = pawn.relations.DirectRelations
                .Select(r => (object)new
                {
                    type   = r.def.label,
                    with   = r.otherPawn?.Name?.ToStringShort ?? "unknown",
                    withId = r.otherPawn?.ThingID ?? ""
                })
                .ToList();

            var colonists = map.mapPawns.FreeColonistsSpawned;
            var opinions = colonists
                .Where(c => c != pawn)
                .Select(c => (object)new
                {
                    pawn        = c.Name.ToStringShort,
                    myOpinion   = pawn.relations.OpinionOf(c),
                    theirOpinion = c.relations.OpinionOf(pawn)
                })
                .ToList();

            return new { pawn = pawn.Name.ToStringShort, directRelations = direct, colonistOpinions = opinions };
        }

        public static object GetPawnWork(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var work = DefDatabase<WorkTypeDef>.AllDefsListForReading
                .Where(wt => wt.visible)
                .Select(wt =>
                {
                    int priority = pawn.workSettings?.GetPriority(wt) ?? 0;
                    bool incapable = pawn.WorkTypeIsDisabled(wt);
                    return (object)new
                    {
                        defName  = wt.defName,
                        label    = wt.labelShort ?? wt.label,
                        priority,
                        active   = priority > 0,
                        incapable
                    };
                })
                .ToList();

            return new { pawn = pawn.Name.ToStringShort, workTypes = work };
        }

        public static object GetPawnSchedule(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var schedule = Enumerable.Range(0, 24)
                .Select(h => (object)new
                {
                    hour       = h,
                    assignment = pawn.timetable?.GetAssignment(h)?.label ?? "any"
                })
                .ToList();

            return new { pawn = pawn.Name.ToStringShort, schedule };
        }

        // ── Colony infrastructure ─────────────────────────────────────────────

        public static object GetPower()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            float generation  = 0f;
            float consumption = 0f;
            float stored      = 0f;
            float maxStored   = 0f;

            foreach (var b in map.listerBuildings.allBuildingsColonist)
            {
                var trader  = b.TryGetComp<CompPowerTrader>();
                var battery = b.TryGetComp<CompPowerBattery>();

                if (trader != null)
                {
                    if (trader.PowerOutput > 0) generation  += trader.PowerOutput;
                    else                         consumption -= trader.PowerOutput;
                }
                if (battery != null)
                {
                    stored    += battery.StoredEnergy;
                    maxStored += battery.Props.storedEnergyMax;
                }
            }

            float net = generation - consumption;
            float hoursUntilDrained = net < 0 && stored > 0
                ? stored / (-net / 60f)
                : -1f;

            return new
            {
                generation          = (float)Math.Round(generation,  1),
                consumption         = (float)Math.Round(consumption, 1),
                netPerSecond        = (float)Math.Round(net,         1),
                storedEnergy        = (float)Math.Round(stored,      1),
                maxStoredEnergy     = (float)Math.Round(maxStored,   1),
                batteryPct          = maxStored > 0 ? (float)Math.Round(stored / maxStored, 3) : 0f,
                hoursUntilDrained   = net < 0 ? (float)Math.Round(hoursUntilDrained, 1) : -1f,
                surplus             = net >= 0
            };
        }

        public static List<object> GetRooms()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.listerBuildings.allBuildingsColonist
                .Select(b => b.GetRoom())
                .Where(r => r != null && !r.IsHuge && !r.TouchesMapEdge && r.CellCount > 1)
                .Distinct()
                .Select(r => (object)new
                {
                    role          = r.Role?.label ?? "none",
                    cells          = r.CellCount,
                    temperature    = (float)Math.Round(r.Temperature, 1),
                    cleanliness    = TryRoomStat(r, RoomStatDefOf.Cleanliness),
                    impressiveness = TryRoomStat(r, RoomStatDefOf.Impressiveness)
                })
                .ToList();
        }

        public static object GetZones()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            var growing = map.zoneManager.AllZones.OfType<Zone_Growing>()
                .Select(z =>
                {
                    var plantDef = z.GetPlantDefToGrow();
                    var plants   = z.cells
                        .Select(c => c.GetFirstThing<Plant>(map))
                        .Where(p => p != null)
                        .ToList();
                    return (object)new
                    {
                        label      = z.label,
                        cells      = z.cells.Count,
                        plant      = plantDef?.label ?? "none",
                        allowSow   = z.allowSow,
                        plantCount = plants.Count,
                        avgGrowth  = plants.Count > 0
                            ? (float)Math.Round(plants.Average(p => p.Growth), 2)
                            : 0f
                    };
                })
                .ToList();

            var stockpiles = map.zoneManager.AllZones.OfType<Zone_Stockpile>()
                .Select(z => (object)new
                {
                    label    = z.label,
                    cells    = z.cells.Count,
                    priority = z.GetStoreSettings()?.Priority.ToString() ?? "Normal"
                })
                .ToList();

            return new { growing, stockpiles };
        }

        public static List<object> GetPrisoners()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.mapPawns.PrisonersOfColonySpawned
                .Select(p => (object)new
                {
                    id              = p.ThingID,
                    name            = p.Name?.ToStringShort ?? p.LabelShort,
                    race            = p.def.label,
                    faction         = p.Faction?.Name ?? "none",
                    position        = Pos(p),
                    health          = (float)Math.Round(p.health.summaryHealth.SummaryHealthPercent, 2),
                    mood            = (float)Math.Round(p.needs?.mood?.CurLevelPercentage ?? 0f, 3),
                    downed          = p.Downed,
                    guestStatus = p.guest?.GuestStatus.ToString() ?? "unknown",
                    resistance  = (float)Math.Round(p.guest?.Resistance ?? 0f, 1),
                    will        = (float)Math.Round(p.guest?.will ?? 0f, 1)
                })
                .ToList();
        }

        public static object GetColony()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            var colonists = map.mapPawns.FreeColonistsSpawned.ToList();

            // Best colonist per skill
            var skillSummary = DefDatabase<SkillDef>.AllDefsListForReading
                .Select(skill =>
                {
                    var best = colonists
                        .OrderByDescending(p => p.skills?.GetSkill(skill)?.Level ?? 0)
                        .FirstOrDefault();
                    return (object)new
                    {
                        skill     = skill.defName,
                        label     = skill.label,
                        bestPawn  = best?.Name?.ToStringShort ?? "none",
                        bestLevel = best?.skills?.GetSkill(skill)?.Level ?? 0
                    };
                })
                .ToList();

            // Food estimate
            float nutrition = 0f;
            foreach (var t in map.listerThings.ThingsInGroup(ThingRequestGroup.HaulableEver))
            {
                if (t.Spawned && t.def.IsNutritionGivingIngestible)
                {
                    try { nutrition += t.GetStatValue(StatDefOf.Nutrition) * t.stackCount; }
                    catch { /* skip things without nutrition stat */ }
                }
            }
            float dailyUse   = colonists.Count * 1.6f;
            float foodDays   = dailyUse > 0 ? nutrition / dailyUse : 0f;

            var wealth = map.wealthWatcher;
            return new
            {
                colonistCount    = colonists.Count,
                wealthTotal      = (float)Math.Round(wealth.WealthTotal,     0),
                wealthItems      = (float)Math.Round(wealth.WealthItems,     0),
                wealthBuildings  = (float)Math.Round(wealth.WealthBuildings, 0),
                estimatedFoodDays = (float)Math.Round(foodDays, 1),
                skillSummary
            };
        }

        public static object GetThreats()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            var hostiles = map.mapPawns.AllPawnsSpawned
                .Where(p => p.Spawned && !p.Dead && p.HostileTo(Faction.OfPlayer))
                .ToList();

            var fires = map.listerThings.ThingsOfDef(ThingDefOf.Fire)
                .Count(f => f.Spawned);

            var downed = map.mapPawns.FreeColonistsSpawned
                .Where(p => p.Downed)
                .Select(p => (object)new { name = p.Name.ToStringShort, id = p.ThingID })
                .ToList();

            var mentalBreaks = map.mapPawns.FreeColonistsSpawned
                .Where(p => p.InMentalState)
                .Select(p => (object)new
                {
                    name  = p.Name.ToStringShort,
                    state = p.MentalStateDef?.label ?? "unknown"
                })
                .ToList();

            return new
            {
                dangerRating     = map.dangerWatcher.DangerRating.ToString(),
                hostileCount     = hostiles.Count,
                activeFires      = fires,
                downedColonists  = downed,
                mentalBreaks,
                hostiles         = hostiles.Take(15).Select(p => (object)new
                {
                    id       = p.ThingID,
                    name     = p.LabelShort,
                    faction  = p.Faction?.Name ?? "unknown",
                    position = Pos(p),
                    health   = (float)Math.Round(p.health.summaryHealth.SummaryHealthPercent, 2),
                    weapon   = p.equipment?.Primary?.def.label ?? "none"
                }).ToList()
            };
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private static object SerializePawn(Pawn p) => new
        {
            id        = p.ThingID,
            name      = p.Name.ToStringShort,
            position  = Pos(p),
            health    = (float)Math.Round(p.health.summaryHealth.SummaryHealthPercent, 2),
            drafted   = p.Drafted,
            downed    = p.Downed,
            job       = JobLabel(p),
            jobTarget = JobTarget(p),
            skills    = p.skills?.skills?
                .ToDictionary(s => s.def.defName, s => s.Level)
                ?? new Dictionary<string, int>(),
            passions  = p.skills?.skills?
                .Where(s => s.passion != Passion.None)
                .ToDictionary(s => s.def.defName, s => s.passion.ToString())
                ?? new Dictionary<string, string>()
        };

        private static object Pos(Pawn p) =>
            new { x = p.Position.x, z = p.Position.z };

        private static string JobLabel(Pawn p) =>
            p.CurJobDef?.reportString ?? "idle";

        private static string JobTarget(Pawn p)
        {
            var job = p.jobs?.curJob;
            if (job == null) return "none";
            if (job.targetA.HasThing)  return job.targetA.Thing?.LabelShort ?? "none";
            if (job.targetA.Cell.IsValid) return job.targetA.Cell.ToString();
            return "none";
        }

        internal static Pawn? FindColonist(string id) =>
            Find.CurrentMap?.mapPawns.FreeColonistsSpawned.FirstOrDefault(p =>
                p.ThingID == id ||
                p.Name.ToStringShort.Equals(id, StringComparison.OrdinalIgnoreCase));

        // ── Pawn character depth ─────────────────────────────────────────────

        public static object GetPawnBackstory(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var child = pawn.story?.Childhood;
            var adult = pawn.story?.Adulthood;
            return new
            {
                pawn      = pawn.Name.ToStringShort,
                childhood = child == null ? null : (object)new { title = child.title, desc = child.baseDesc },
                adulthood = adult == null ? null : (object)new { title = adult.title, desc = adult.baseDesc }
            };
        }

        public static object GetPawnCapacities(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var caps = DefDatabase<PawnCapacityDef>.AllDefsListForReading
                .Select(cap => new
                {
                    defName  = cap.defName,
                    label    = cap.label,
                    level    = (float)Math.Round(pawn.health.capacities.GetLevel(cap), 3),
                    impaired = pawn.health.capacities.GetLevel(cap) < 1f - 0.001f
                })
                .OrderBy(c => c.label)
                .Select(c => (object)c)
                .ToList();

            return new { pawn = pawn.Name.ToStringShort, capacities = caps };
        }

        public static object GetPawnPsycasts(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            // The entropy tracker exists without Royalty, but the stats it reads do not:
            // StatDefOf.PsychicEntropyMax is null then, and MaxEntropy throws.
            if (!ModsConfig.RoyaltyActive) return Error("Royalty DLC is not active");

            var ent = pawn.psychicEntropy;
            if (ent == null) return Error("Pawn is not a psycaster (Royalty DLC may not be active)");

            var abilities = pawn.abilities?.abilities?
                .Where(a => a.def.IsPsycast)
                .Select(a => (object)new
                {
                    defName   = a.def.defName,
                    label     = a.def.label,
                    level     = a.def.level,
                    onCooldown = a.CooldownTicksRemaining > 0,
                    cooldownTicks = a.CooldownTicksRemaining
                })
                .ToList() ?? new List<object>();

            return new
            {
                pawn         = pawn.Name.ToStringShort,
                psyfocus     = (float)Math.Round(ent.CurrentPsyfocus, 3),
                neuralHeat   = TryGetFloat(ent, "Entropy"),
                maxNeuralHeat = (float)Math.Round(ent.MaxEntropy, 1),
                abilities
            };
        }

        public static object GetPawnGenes(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var g = pawn.genes;
            if (g == null) return Error("Pawn has no gene data (Biotech DLC may not be active)");

            return new
            {
                pawn       = pawn.Name.ToStringShort,
                xenotype   = g.Xenotype?.label ?? "baseliner",
                endogenes  = g.Endogenes?.Select(ge => (object)new { defName = ge.def.defName, label = ge.def.label, active = ge.Active }).ToList(),
                xenogenes  = g.Xenogenes?.Select(ge => (object)new { defName = ge.def.defName, label = ge.def.label, active = ge.Active }).ToList()
            };
        }

        public static object GetPawnArea(string id)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var pawn = FindColonist(id);
            if (pawn == null) return Error($"Pawn '{id}' not found");

            var area = pawn.playerSettings?.AreaRestrictionInPawnCurrentMap;
            return new
            {
                pawn      = pawn.Name.ToStringShort,
                restricted = area != null,
                areaLabel  = area?.Label ?? "unrestricted",
                areaId     = area?.ID ?? -1
            };
        }

        // ── Stockpile / inventory ─────────────────────────────────────────────

        public static List<object> GetStockpileContents()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.zoneManager.AllZones.OfType<Zone_Stockpile>()
                .Select(z =>
                {
                    var settings = z.GetStoreSettings();
                    var filter   = settings?.filter;

                    var contents = z.cells
                        .SelectMany(c => c.GetThingList(map))
                        .Where(t => t.def.category == ThingCategory.Item)
                        .GroupBy(t => t.def.defName)
                        .Select(gr => new { label = gr.First().def.label, count = gr.Sum(t => t.stackCount) })
                        .OrderByDescending(x => x.count)
                        .Select(x => (object)x)
                        .ToList();

                    var allowedDefs = filter?.AllowedThingDefs?
                        .Select(d => d.label)
                        .Take(30)
                        .ToList() ?? new List<string>();

                    return (object)new
                    {
                        label       = z.label,
                        cells       = z.cells.Count,
                        priority    = settings?.Priority.ToString() ?? "Normal",
                        contents,
                        allowedDefs
                    };
                })
                .ToList();
        }

        // ── Corpses ───────────────────────────────────────────────────────────

        public static List<object> GetCorpses()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.listerThings.AllThings
                .OfType<Corpse>()
                .Where(c => c.Spawned)
                .Select(c =>
                {
                    var rot = c.TryGetComp<CompRottable>();
                    return (object)new
                    {
                        id          = c.ThingID,
                        pawnName    = c.InnerPawn?.Name?.ToStringShort ?? c.InnerPawn?.LabelShort ?? "unknown",
                        race        = c.InnerPawn?.def?.label ?? "unknown",
                        faction     = c.InnerPawn?.Faction?.Name ?? "none",
                        position    = new { x = c.Position.x, z = c.Position.z },
                        rotProgress = rot != null ? (float)Math.Round(rot.RotProgress, 1) : -1f,
                        desiccated  = c.IsDessicated()
                    };
                })
                .ToList();
        }

        // ── Drug policies ─────────────────────────────────────────────────────

        public static object GetDrugPolicies()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            var allPolicies = Current.Game.drugPolicyDatabase.AllPolicies
                .Select(p => (object)new { label = p.label })
                .ToList();

            var assignments = map.mapPawns.FreeColonistsSpawned
                .Select(p => (object)new
                {
                    pawn   = p.Name.ToStringShort,
                    policy = p.drugs?.CurrentPolicy?.label ?? "none"
                })
                .ToList();

            return new { allPolicies, assignments };
        }

        // ── Room assignments ──────────────────────────────────────────────────

        public static List<object> GetRoomAssignments()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.listerBuildings.allBuildingsColonist
                .OfType<Building_Bed>()
                .Select(b => new { b, comp = b.GetComp<CompAssignableToPawn>() })
                .Where(x => x.comp != null && x.comp.AssignedPawns.Any())
                .Select(x =>
                {
                    var bx = x.b.Position.x;
                    var bz = x.b.Position.z;
                    return (object)new
                    {
                        id           = x.b.ThingID,
                        label        = x.b.def.label,
                        position     = new { x = bx, z = bz },
                        forPrisoners = x.b.ForPrisoners,
                        assignedTo   = x.comp.AssignedPawns
                            .Select(p => p.Name?.ToStringShort ?? p.LabelShort)
                            .ToList()
                    };
                })
                .ToList();
        }

        // ── Mechs (Biotech) ───────────────────────────────────────────────────

        public static List<object> GetMechs()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.mapPawns.FreeColonistsSpawned
                .Where(p => p.mechanitor != null)
                .Select(p =>
                {
                    var m = p.mechanitor;
                    var mechList = TryGetList<Pawn>(m, "MechsForReading");
                    var mechs = mechList
                        .Select(mech =>
                        {
                            IntVec3 mechPos = ((Thing)mech).Position;
                            return (object)new
                            {
                                id     = mech.ThingID,
                                name   = mech.LabelShort,
                                race   = mech.def.label,
                                health = (float)Math.Round(mech.health.summaryHealth.SummaryHealthPercent, 2),
                                pos    = new { x = mechPos.x, z = mechPos.z },
                                job    = JobLabel(mech)
                            };
                        })
                        .ToList();

                    int used  = m.UsedBandwidth;
                    int total = m.TotalBandwidth;
                    return (object)new
                    {
                        mechanitor     = p.Name.ToStringShort,
                        usedBandwidth  = used,
                        totalBandwidth = total,
                        mechs
                    };
                })
                .ToList();
        }

        // ── Incidents / archive ───────────────────────────────────────────────

        public static List<object> GetIncidents()
        {
            return Find.Archive.ArchivablesListForReading
                .OfType<Letter>()
                .Take(30)
                .Select(l => (object)new
                {
                    label    = l.Label.RawText,
                    type     = l.def?.defName ?? "unknown",
                    typeLabel = l.def?.label ?? "unknown"
                })
                .ToList();
        }

        // ── Colony-level social overview ──────────────────────────────────────

        public static object GetColonySocial()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            var colonists = map.mapPawns.FreeColonistsSpawned.ToList();

            // All romantic pairs (lover / spouse / fiancee)
            var romanticDefs = new System.Collections.Generic.HashSet<string>
                { "Lover", "Spouse", "Fiance", "Fiancee", "ExLover", "ExSpouse" };

            var pairs = new System.Collections.Generic.List<object>();
            var seen  = new System.Collections.Generic.HashSet<string>();
            foreach (var p in colonists)
            {
                foreach (var rel in p.relations.DirectRelations
                    .Where(r => romanticDefs.Contains(r.def.defName)))
                {
                    string key = string.Compare(p.ThingID, rel.otherPawn?.ThingID ?? "") < 0
                        ? $"{p.ThingID}_{rel.otherPawn?.ThingID}"
                        : $"{rel.otherPawn?.ThingID}_{p.ThingID}";
                    if (seen.Add(key))
                        pairs.Add(new
                        {
                            pawnA    = p.Name.ToStringShort,
                            pawnB    = rel.otherPawn?.Name?.ToStringShort ?? "unknown",
                            relation = rel.def.label
                        });
                }
            }

            // All direct family relations between colonists
            var family = new System.Collections.Generic.List<object>();
            var seenF  = new System.Collections.Generic.HashSet<string>();
            foreach (var p in colonists)
            {
                foreach (var rel in p.relations.DirectRelations
                    .Where(r => !romanticDefs.Contains(r.def.defName)
                             && colonists.Any(c => c == r.otherPawn)))
                {
                    string key = $"{p.ThingID}_{rel.otherPawn?.ThingID}_{rel.def.defName}";
                    if (seenF.Add(key))
                        family.Add(new
                        {
                            pawnA    = p.Name.ToStringShort,
                            pawnB    = rel.otherPawn?.Name?.ToStringShort ?? "unknown",
                            relation = rel.def.label
                        });
                }
            }

            // Best and worst opinions
            var opinions = new System.Collections.Generic.List<object>();
            foreach (var p in colonists)
                foreach (var other in colonists.Where(c => c != p))
                {
                    int op = p.relations.OpinionOf(other);
                    if (op >= 50 || op <= -20)
                        opinions.Add(new { from = p.Name.ToStringShort, to = other.Name.ToStringShort, opinion = op });
                }

            return new { romanticPairs = pairs, familyRelations = family, notableOpinions = opinions };
        }

        // ── Map cell info ─────────────────────────────────────────────────────

        public static object GetCellInfo(int x, int z)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            var cell = new IntVec3(x, 0, z);
            if (!cell.InBounds(map)) return Error("Cell out of bounds");

            var things = map.thingGrid.ThingsListAt(cell)
                .Select(t => (object)new { id = t.ThingID, label = t.def.label, defName = t.def.defName, hp = t.HitPoints })
                .ToList();

            float temp = 0f;
            try { temp = (float)Math.Round(GenTemperature.GetTemperatureForCell(cell, map), 1); } catch { }

            return new
            {
                x,
                z,
                terrain     = map.terrainGrid.TerrainAt(cell)?.label ?? "unknown",
                roofed      = map.roofGrid.Roofed(cell),
                temperature = temp,
                fertility   = (float)Math.Round(map.fertilityGrid.FertilityAt(cell), 2),
                zone        = map.zoneManager.ZoneAt(cell)?.label ?? "none",
                things
            };
        }

        // ── Animals ──────────────────────────────────────────────────────────

        public static List<object> GetAnimalTraining()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.mapPawns.AllPawnsSpawned
                .Where(p => p.RaceProps.Animal && p.Spawned && p.Faction == Faction.OfPlayer && !p.Dead)
                .Select(p =>
                {
                    var tr = p.training;
                    var steps = DefDatabase<TrainableDef>.AllDefsListForReading
                        .Select(td => new
                        {
                            defName = td.defName,
                            label   = td.label,
                            learned = tr?.HasLearned(td) ?? false,
                            wanted  = tr?.GetWanted(td) ?? false
                        })
                        .Where(s => s.learned || s.wanted)
                        .ToList();

                    var bonds = p.relations?.DirectRelations?
                        .Where(r => r.def == PawnRelationDefOf.Bond)
                        .Select(r => r.otherPawn?.Name?.ToStringShort ?? "unknown")
                        .ToList() ?? new List<string>();

                    return (object)new
                    {
                        id       = p.ThingID,
                        name     = p.LabelShort,
                        race     = p.def.label,
                        position = Pos(p),
                        health   = (float)Math.Round(p.health.summaryHealth.SummaryHealthPercent, 2),
                        training = steps,
                        bondedTo = bonds
                    };
                })
                .ToList();
        }

        // ── World-level ───────────────────────────────────────────────────────

        public static List<object> GetCaravans()
        {
            return Find.WorldObjects.Caravans
                .Where(c => c.IsPlayerControlled)
                .Select(c => (object)new
                {
                    id      = c.ID,
                    name    = c.Label,
                    tile    = c.Tile.tileId,
                    moving  = c.pather?.Moving ?? false,
                    members = c.PawnsListForReading
                        .Select(p => new { name = p.Name?.ToStringShort ?? p.LabelShort, role = p.RaceProps.Animal ? "animal" : "colonist" })
                        .ToList()
                })
                .ToList();
        }

        public static List<object> GetWorldFactions()
        {
            return Find.FactionManager.AllFactionsListForReading
                .Where(f => !f.IsPlayer && !f.Hidden && !f.defeated)
                .Select(f => new
                {
                    name     = f.Name,
                    def      = f.def.label,
                    goodwill = f.PlayerGoodwill,
                    relation = Faction.OfPlayer.RelationKindWith(f).ToString(),
                    hostile  = f.HostileTo(Faction.OfPlayer)
                })
                .OrderByDescending(x => x.goodwill)
                .Select(x => (object)x)
                .ToList();
        }

        public static List<object> GetWorldSites()
        {
            return Find.WorldObjects.SettlementBases
                .Select(s => (object)new
                {
                    id      = s.ID,
                    name    = s.Label,
                    faction = s.Faction?.Name ?? "none",
                    // Tile is a PlanetTile struct in 1.6. Serialised whole, its properties
                    // lead into the surface tile's road links, which refer back to it.
                    tile    = s.Tile.tileId,
                    hostile = s.Faction?.HostileTo(Faction.OfPlayer) ?? false
                })
                .ToList();
        }

        // ── Events / alerts ───────────────────────────────────────────────────

        public static List<object> GetMessages()
        {
            return Find.LetterStack.LettersListForReading
                .Take(30)
                .Select(l => (object)new
                {
                    label    = l.Label.RawText,
                    type     = l.def?.label ?? "unknown",
                    typeDef  = l.def?.defName ?? "unknown"
                })
                .ToList();
        }

        public static object GetAlerts()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            var colonists = map.mapPawns.FreeColonistsSpawned.ToList();

            // Food estimate
            float nutrition = 0f;
            foreach (var t in map.listerThings.ThingsInGroup(ThingRequestGroup.HaulableEver))
            {
                if (t.Spawned && t.def.IsNutritionGivingIngestible)
                    try { nutrition += t.GetStatValue(StatDefOf.Nutrition) * t.stackCount; } catch { }
            }
            float foodDays = colonists.Count > 0 ? nutrition / (colonists.Count * 1.6f) : 0f;

            // Power
            float gen = 0f, cons = 0f;
            foreach (var b in map.listerBuildings.allBuildingsColonist)
            {
                var pt = b.TryGetComp<CompPowerTrader>();
                if (pt == null) continue;
                if (pt.PowerOutput > 0) gen  += pt.PowerOutput;
                else                    cons -= pt.PowerOutput;
            }

            var fires = map.listerThings.ThingsOfDef(ThingDefOf.Fire).Count(f => f.Spawned);

            var bleeding = colonists.Where(p => p.health.hediffSet.BleedRateTotal > 0)
                .Select(p => p.Name.ToStringShort).ToList();

            var downed = colonists.Where(p => p.Downed)
                .Select(p => p.Name.ToStringShort).ToList();

            var mental = colonists.Where(p => p.InMentalState)
                .Select(p => $"{p.Name.ToStringShort}: {p.MentalStateDef?.label ?? "unknown"}").ToList();

            var lowMood = colonists
                .Where(p => (p.needs?.mood?.CurLevelPercentage ?? 1f) < (p.mindState?.mentalBreaker?.BreakThresholdMajor ?? 0.2f) + 0.05f)
                .Select(p => p.Name.ToStringShort).ToList();

            var hostile = map.mapPawns.AllPawnsSpawned
                .Count(p => p.Spawned && !p.Dead && p.HostileTo(Faction.OfPlayer));

            return new
            {
                foodDays             = (float)Math.Round(foodDays, 1),
                lowFood              = foodDays < 3f,
                powerSurplus         = gen - cons,
                powerDeficit         = gen < cons,
                activeFires          = fires,
                hostileCount         = hostile,
                bleedingColonists    = bleeding,
                downedColonists      = downed,
                mentalBreaks         = mental,
                colonistsNearBreak   = lowMood,
                dangerRating         = map.dangerWatcher.DangerRating.ToString()
            };
        }

        // ── Medical ───────────────────────────────────────────────────────────

        public static List<object> GetMedical()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.mapPawns.AllPawnsSpawned
                .Where(p => p.Spawned && !p.Dead && p.health.HasHediffsNeedingTend())
                .Select(p =>
                {
                    var tendable = p.health.hediffSet.hediffs
                        .Where(h => h.TendableNow())
                        .Select(h => (object)new
                        {
                            label    = h.def.label,
                            severity = (float)Math.Round(h.Severity, 3),
                            part     = h.Part?.Label ?? "whole body",
                            bleeding = h.Bleeding
                        })
                        .ToList();

                    return (object)new
                    {
                        id       = p.ThingID,
                        name     = p.Name?.ToStringShort ?? p.LabelShort,
                        faction  = p.Faction?.Name ?? "none",
                        position = Pos(p),
                        health   = (float)Math.Round(p.health.summaryHealth.SummaryHealthPercent, 2),
                        tendable
                    };
                })
                .ToList();
        }

        // ── Production ───────────────────────────────────────────────────────

        public static List<object> GetProduction()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.listerBuildings.allBuildingsColonist
                .OfType<IBillGiver>()
                .Where(bg => bg.BillStack.Count > 0)
                .Select(bg =>
                {
                    var b = (Thing)bg;
                    var bills = bg.BillStack.Bills
                        .Select(bill => (object)new
                        {
                            id     = bill.GetUniqueLoadID(),
                            label  = bill.Label,
                            recipe = bill.recipe?.label ?? "unknown",
                            suspended = bill.suspended
                        })
                        .ToList();

                    return (object)new
                    {
                        id       = b.ThingID,
                        label    = b.def.label,
                        position = new { x = b.Position.x, z = b.Position.z },
                        bills
                    };
                })
                .ToList();
        }

        // ── Apparel policies ─────────────────────────────────────────────────

        public static object GetApparel()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            var policies = Current.Game.outfitDatabase.AllOutfits
                .Select(o => (object)new { label = o.label })
                .ToList();

            var assignments = map.mapPawns.FreeColonistsSpawned
                .Select(p => (object)new
                {
                    pawn   = p.Name.ToStringShort,
                    policy = TryGetOutfitLabel(p)
                })
                .ToList();

            return new { policies, assignments };
        }

        // ── Areas / cells rectangle ───────────────────────────────────────────

        public static List<object> GetAreas()
        {
            var map = Find.CurrentMap;
            if (map == null) return new List<object> { Error("No active map") };

            return map.areaManager.AllAreas
                .Select(a => (object)new
                {
                    id        = a.ID,
                    label     = a.Label,
                    type      = a.GetType().Name,
                    cellCount = a.TrueCount,
                    mutable   = a is Area_Allowed
                })
                .ToList();
        }

        public static object GetCellsRect(int x1, int z1, int x2, int z2)
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            // Cap to 1024 cells
            var rect = new CellRect(x1, z1, x2 - x1 + 1, z2 - z1 + 1).ClipInsideMap(map);
            if (rect.Area > 1024) return Error("Rectangle too large (max 1024 cells)");

            var cells = rect.Select(cell => (object)new
            {
                x           = cell.x,
                z           = cell.z,
                terrain     = map.terrainGrid.TerrainAt(cell)?.defName ?? "unknown",
                roofed      = map.roofGrid.Roofed(cell),
                zone        = map.zoneManager.ZoneAt(cell)?.label ?? null,
                designation = map.designationManager.AllDesignations
                    .FirstOrDefault(d => d.target.HasThing ? false : d.target.Cell == cell)?.def.defName ?? null,
                things      = map.thingGrid.ThingsListAt(cell)
                    .Select(t => t.def.defName).ToList()
            }).ToList();

            return new { x1, z1, x2, z2, cellCount = cells.Count, cells };
        }

        // ── Trading / quests / ideology ───────────────────────────────────────

        public static object GetTraders()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");

            // Ground traders: pawns on the current map with a TraderKind
            var groundTraders = map.mapPawns.AllPawnsSpawned
                .Where(p => p.TraderKind != null && p.Faction != Faction.OfPlayer && !p.Dead)
                .Select(p => (object)new
                {
                    id         = p.ThingID,
                    name       = p.Name?.ToStringShort ?? p.LabelShort,
                    faction    = p.Faction?.Name ?? "unknown",
                    traderKind = p.TraderKind?.label ?? "unknown",
                    canTrade   = p.CanTradeNow,
                    position   = Pos(p),
                    stock      = p.CanTradeNow
                        ? p.inventory?.innerContainer?
                            .GroupBy(t => t.def.defName)
                            .Select(g => new { label = g.First().def.label, count = g.Sum(t => t.stackCount) })
                            .Take(20)
                            .ToList()
                        : null
                })
                .ToList();

            // Orbital trade ships (world level)
            var orbitalTraders = Find.WorldObjects.AllWorldObjects
                .OfType<TradeShip>()
                .Select(ship => (object)new
                {
                    name       = ship.TraderName,
                    traderKind = ship.TraderKind?.label ?? "unknown",
                    daysLeft   = (float)Math.Round(ship.ticksUntilDeparture / 60000f, 1)
                })
                .ToList();

            return new { groundTraders, orbitalTraders };
        }

        public static object GetQuests()
        {
            var raw    = Find.QuestManager.questsInDisplayOrder.ToList();
            var quests = raw
                .Select(q => (object)new
                {
                    id          = q.id,
                    name        = q.name,
                    state       = q.State.ToString(),
                    ongoing     = !q.Historical,
                    // TaggedString is a struct. Serialised whole it becomes an object, and
                    // an empty one throws from Length; RawText is the text, or null.
                    description = q.description.RawText
                })
                .ToList();

            return new
            {
                ongoing = raw.Count(q => !q.Historical),
                total   = raw.Count,
                quests
            };
        }

        public static object GetIdeology()
        {
            var map = Find.CurrentMap;
            if (map == null) return Error("No active map");
            var ideo = map.mapPawns.FreeColonistsSpawned
                .Select(p => p.Ideo)
                .FirstOrDefault(i => i != null);
            if (ideo == null)
                return Error("Ideology DLC not active or colony has no ideology");

            var memes = ideo.memes?
                .Select(m => (object)new { defName = m.defName, label = m.label })
                .ToList() ?? new List<object>();

            var precepts = ideo.PreceptsListForReading?
                .Select(p => (object)new
                {
                    defName = p.def.defName,
                    label   = p.def.label,
                    impact  = p.def.impact.ToString()
                })
                .ToList() ?? new List<object>();

            return new { name = ideo.name, memes, precepts };
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private static string TryGetOutfitLabel(Pawn p)
        {
            try
            {
                var outfit = p.outfits?.GetType()
                    .GetField("CurrentOutfit")?
                    .GetValue(p.outfits) as ApparelPolicy;
                return outfit?.label ?? "unknown";
            }
            catch { return "unknown"; }
        }

        private static float TryGetFloat(object obj, string propertyName)
        {
            try
            {
                var val = obj.GetType().GetProperty(propertyName)?.GetValue(obj);
                return val == null ? 0f : (float)Math.Round(System.Convert.ToSingle(val), 2);
            }
            catch { return 0f; }
        }

        private static List<T> TryGetList<T>(object obj, string propertyName)
        {
            try
            {
                var val = obj.GetType().GetProperty(propertyName,
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)
                    ?.GetValue(obj);
                if (val is List<T> list) return list;
                if (val is System.Collections.Generic.IEnumerable<T> seq) return seq.ToList();
                return new List<T>();
            }
            catch { return new List<T>(); }
        }

        private static float TryRoomStat(Room room, RoomStatDef stat)
        {
            try   { return (float)Math.Round(room.GetStat(stat), 2); }
            catch { return 0f; }
        }

        private static object Error(string msg) => new { error = msg };
    }
}
