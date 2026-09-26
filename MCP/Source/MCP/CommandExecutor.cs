using System;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using RimWorld;
using Verse;
using Verse.AI;

namespace MCP
{
    internal static class CommandExecutor
    {
        // ── Pawn orders ───────────────────────────────────────────────────────

        public static (int, string) Draft(string body)
        {
            var cmd  = Parse(body);
            var pawn = Colonist(cmd, "pawn_id");
            if (pawn == null) return NotFound("pawn_id");

            bool drafted = cmd["drafted"]?.Value<bool>() ?? true;
            pawn.drafter.Drafted = drafted;
            return Ok(new { pawn = pawn.Name.ToStringShort, drafted });
        }

        public static (int, string) Move(string body)
        {
            var cmd  = Parse(body);
            var pawn = Colonist(cmd, "pawn_id");
            if (pawn == null) return NotFound("pawn_id");

            int x    = cmd["x"]?.Value<int>() ?? 0;
            int z    = cmd["z"]?.Value<int>() ?? 0;
            var dest = new IntVec3(x, 0, z);

            if (!dest.InBounds(pawn.Map))  return Bad("Cell out of bounds");
            if (!dest.Walkable(pawn.Map))  return Bad("Cell not walkable");

            var job = JobMaker.MakeJob(JobDefOf.Goto, dest);
            pawn.jobs.StartJob(job, JobCondition.InterruptForced);
            return Ok(new { pawn = pawn.Name.ToStringShort, movingTo = new { x, z } });
        }

        public static (int, string) Attack(string body)
        {
            var cmd    = Parse(body);
            var pawn   = Colonist(cmd, "pawn_id");
            if (pawn == null) return NotFound("pawn_id");

            string targetId = cmd["target_id"]?.Value<string>() ?? "";
            var target = pawn.Map.mapPawns.AllPawnsSpawned
                .FirstOrDefault(p => p.ThingID == targetId);
            if (target == null) return NotFound("target_id");

            var attackJob = pawn.equipment?.Primary?.def.IsRangedWeapon == true
                ? JobMaker.MakeJob(JobDefOf.AttackStatic, target)
                : JobMaker.MakeJob(JobDefOf.AttackMelee,  target);

            pawn.jobs.StartJob(attackJob, JobCondition.InterruptForced);
            return Ok(new { pawn = pawn.Name.ToStringShort, attacking = target.LabelShort });
        }

        public static (int, string) AssignJob(string body)
        {
            var cmd  = Parse(body);
            var pawn = Colonist(cmd, "pawn_id");
            if (pawn == null) return NotFound("pawn_id");

            string jobName = cmd["job"]?.Value<string>() ?? "";
            var jobDef = DefDatabase<JobDef>.GetNamedSilentFail(jobName);
            if (jobDef == null) return Bad($"Unknown JobDef '{jobName}'");

            string targetId = cmd["target_id"]?.Value<string>() ?? "";
            Thing? target = null;
            if (!string.IsNullOrEmpty(targetId))
                target = pawn.Map.listerThings.AllThings
                    .FirstOrDefault(t => t.ThingID == targetId);

            var job = target != null
                ? JobMaker.MakeJob(jobDef, target)
                : JobMaker.MakeJob(jobDef);

            pawn.jobs.StartJob(job, JobCondition.InterruptForced);
            return Ok(new { pawn = pawn.Name.ToStringShort, job = jobName, target = target?.LabelShort ?? "none" });
        }

        // ── Designations ──────────────────────────────────────────────────────

        public static (int, string) Hunt(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string targetId = cmd["target_id"]?.Value<string>() ?? "";
            var animal = map.mapPawns.AllPawnsSpawned.FirstOrDefault(p =>
                p.RaceProps.Animal &&
                (p.ThingID == targetId ||
                 p.LabelShort.Equals(targetId, StringComparison.OrdinalIgnoreCase)));

            if (animal == null) return NotFound("target_id");
            if (map.designationManager.DesignationOn(animal, DesignationDefOf.Hunt) != null)
                return Bad($"{animal.LabelShort} is already designated for hunting");

            map.designationManager.AddDesignation(new Designation(animal, DesignationDefOf.Hunt));
            return Ok(new { designated = animal.LabelShort, race = animal.def.label, type = "hunt" });
        }

        public static (int, string) Mine(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            int x    = cmd["x"]?.Value<int>() ?? 0;
            int z    = cmd["z"]?.Value<int>() ?? 0;
            var cell = new IntVec3(x, 0, z);

            if (!cell.InBounds(map)) return Bad("Cell out of bounds");

            var mineable = map.thingGrid.ThingsListAt(cell).FirstOrDefault(t => t.def.mineable);
            if (mineable == null) return Bad("No mineable resource at that cell");
            if (map.designationManager.DesignationOn(mineable, DesignationDefOf.Mine) != null)
                return Bad("Already designated for mining");

            map.designationManager.AddDesignation(new Designation(mineable, DesignationDefOf.Mine));
            return Ok(new { designated = mineable.def.label, position = new { x, z }, type = "mine" });
        }

        public static (int, string) CutPlant(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string targetId = cmd["target_id"]?.Value<string>() ?? "";
            Thing plant;

            if (!string.IsNullOrEmpty(targetId))
            {
                plant = map.listerThings.AllThings.FirstOrDefault(t =>
                    t.ThingID == targetId && t.def.category == ThingCategory.Plant);
            }
            else
            {
                int x = cmd["x"]?.Value<int>() ?? 0;
                int z = cmd["z"]?.Value<int>() ?? 0;
                plant = map.thingGrid.ThingsListAt(new IntVec3(x, 0, z))
                    .FirstOrDefault(t => t.def.category == ThingCategory.Plant);
            }

            if (plant == null) return NotFound("plant");
            if (map.designationManager.DesignationOn(plant, DesignationDefOf.CutPlant) != null)
                return Bad("Already designated for cutting");

            map.designationManager.AddDesignation(new Designation(plant, DesignationDefOf.CutPlant));
            return Ok(new { designated = plant.def.label, position = new { x = plant.Position.x, z = plant.Position.z }, type = "cut" });
        }

        // ── Construction ──────────────────────────────────────────────────────

        public static (int, string) Build(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string defName   = cmd["def_name"]?.Value<string>() ?? "";
            int x            = cmd["x"]?.Value<int>() ?? 0;
            int z            = cmd["z"]?.Value<int>() ?? 0;
            string rotStr    = cmd["rotation"]?.Value<string>() ?? "North";
            string stuffName = cmd["stuff_def"]?.Value<string>() ?? "";

            var buildDef = DefDatabase<ThingDef>.AllDefsListForReading
                .FirstOrDefault(d => d.defName == defName && d.BuildableByPlayer);
            if (buildDef == null) return Bad($"Unknown or non-buildable def '{defName}'");

            var cell = new IntVec3(x, 0, z);
            if (!cell.InBounds(map)) return Bad("Cell out of bounds");

            var rot = rotStr switch
            {
                "South" => Rot4.South,
                "East"  => Rot4.East,
                "West"  => Rot4.West,
                _       => Rot4.North
            };

            ThingDef? stuff = null;
            if (!string.IsNullOrEmpty(stuffName))
                stuff = DefDatabase<ThingDef>.GetNamedSilentFail(stuffName);
            if (stuff == null && buildDef.MadeFromStuff)
                stuff = GenStuff.DefaultStuffFor(buildDef);

            var report = GenConstruct.CanPlaceBlueprintAt(buildDef, cell, rot, map);
            if (!report.Accepted)
                return Bad($"Cannot place '{buildDef.label}': {report.Reason}");

            GenConstruct.PlaceBlueprintForBuild(buildDef, cell, map, rot, Faction.OfPlayer, stuff);
            var rotLabel = rot == Rot4.North ? "North" : rot == Rot4.South ? "South" : rot == Rot4.East ? "East" : "West";
            return Ok(new { built = buildDef.label, position = new { x, z }, rotation = rotLabel, stuff = stuff?.label ?? "none" });
        }

        // ── Colony management ─────────────────────────────────────────────────

        public static (int, string) SetResearch(string body)
        {
            var cmd    = Parse(body);
            string defName = cmd["project_def"]?.Value<string>() ?? "";

            var project = DefDatabase<ResearchProjectDef>.GetNamedSilentFail(defName);
            if (project == null) return Bad($"Unknown research project '{defName}'");
            if (project.IsFinished) return Bad($"'{project.label}' is already completed");

            Find.ResearchManager.SetCurrentProject(project);
            return Ok(new
            {
                researching = project.label,
                progress    = (float)Math.Round(Find.ResearchManager.GetProgress(project) / project.baseCost, 3),
                techLevel   = project.techLevel.ToString()
            });
        }

        public static (int, string) ForbidThing(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string thingId = cmd["thing_id"]?.Value<string>() ?? "";
            bool forbidden = cmd["forbidden"]?.Value<bool>() ?? true;

            var thing = map.listerThings.AllThings.FirstOrDefault(t => t.ThingID == thingId);
            if (thing == null) return NotFound("thing_id");

            thing.SetForbidden(forbidden);
            return Ok(new { thing = thing.def.label, forbidden });
        }

        public static (int, string) Rescue(string body)
        {
            var cmd     = Parse(body);
            var rescuer = Colonist(cmd, "pawn_id");
            if (rescuer == null) return NotFound("pawn_id");

            var map    = Find.CurrentMap;
            string tgt = cmd["target_id"]?.Value<string>() ?? "";
            var target = map.mapPawns.AllPawnsSpawned.FirstOrDefault(p =>
                (p.ThingID == tgt ||
                 p.Name?.ToStringShort.Equals(tgt, StringComparison.OrdinalIgnoreCase) == true)
                && p.Downed);

            if (target == null) return NotFound("target_id (must be a downed pawn on the map)");

            var job = JobMaker.MakeJob(JobDefOf.Rescue, target);
            rescuer.jobs.StartJob(job, JobCondition.InterruptForced);
            return Ok(new { rescuer = rescuer.Name.ToStringShort, rescuing = target.LabelShort });
        }

        // ── Equipment / colonist management ──────────────────────────────────

        public static (int, string) EquipItem(string body)
        {
            var cmd  = Parse(body);
            var pawn = Colonist(cmd, "pawn_id");
            if (pawn == null) return NotFound("pawn_id");

            string itemId = cmd["item_id"]?.Value<string>() ?? "";
            var item = pawn.Map.listerThings.AllThings
                .FirstOrDefault(t => t.ThingID == itemId) as ThingWithComps;
            if (item == null) return NotFound("item_id");
            if (!item.def.IsWeapon) return Bad("Item is not a weapon");

            // Move current weapon to inventory first
            if (pawn.equipment.Primary != null)
                pawn.equipment.TryTransferEquipmentToContainer(pawn.equipment.Primary, pawn.inventory.innerContainer);

            pawn.equipment.AddEquipment(item);
            return Ok(new { pawn = pawn.Name.ToStringShort, equipped = item.def.label });
        }

        public static (int, string) RecruitPrisoner(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string targetId = cmd["pawn_id"]?.Value<string>() ?? "";
            var prisoner = map.mapPawns.PrisonersOfColonySpawned.FirstOrDefault(p =>
                p.ThingID == targetId ||
                p.Name?.ToStringShort.Equals(targetId, StringComparison.OrdinalIgnoreCase) == true);

            if (prisoner == null) return NotFound("pawn_id (must be a prisoner on the map)");

            prisoner.SetFaction(Faction.OfPlayer);
            return Ok(new { recruited = prisoner.Name?.ToStringShort ?? prisoner.LabelShort });
        }

        public static (int, string) AssignBed(string body)
        {
            var cmd  = Parse(body);
            var pawn = Colonist(cmd, "pawn_id");
            if (pawn == null) return NotFound("pawn_id");

            string bedId = cmd["bed_id"]?.Value<string>() ?? "";
            var bed = pawn.Map.listerThings.AllThings
                .FirstOrDefault(t => t.ThingID == bedId) as Building_Bed;
            if (bed == null) return NotFound("bed_id (must be a bed ThingID)");

            var comp = bed.GetComp<CompAssignableToPawn>();
            if (comp == null) return Bad("This bed cannot be assigned to pawns");
            comp.TryAssignPawn(pawn);

            return Ok(new { pawn = pawn.Name.ToStringShort, bed = bed.def.label, position = new { x = bed.Position.x, z = bed.Position.z } });
        }

        // ── Production bills ──────────────────────────────────────────────────

        public static (int, string) AddBill(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string benchId    = cmd["bench_id"]?.Value<string>() ?? "";
            string recipeDef  = cmd["recipe_def"]?.Value<string>() ?? "";
            int    count      = cmd["count"]?.Value<int>() ?? 1;

            var bench = map.listerThings.AllThings
                .FirstOrDefault(t => t.ThingID == benchId) as IBillGiver;
            if (bench == null) return NotFound("bench_id (must be a workbench ThingID)");

            var recipe = DefDatabase<RecipeDef>.GetNamedSilentFail(recipeDef);
            if (recipe == null) return Bad($"Unknown RecipeDef '{recipeDef}'");

            var bill = new Bill_Production(recipe);
            bill.repeatCount = count;
            bench.BillStack.AddBill(bill);

            return Ok(new { added = recipe.label, bench = ((Thing)bench).def.label, count });
        }

        public static (int, string) RemoveBill(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string benchId = cmd["bench_id"]?.Value<string>() ?? "";
            string billId  = cmd["bill_id"]?.Value<string>() ?? "";

            var bench = map.listerThings.AllThings
                .FirstOrDefault(t => t.ThingID == benchId) as IBillGiver;
            if (bench == null) return NotFound("bench_id");

            var bill = bench.BillStack.Bills
                .FirstOrDefault(b => b.GetUniqueLoadID() == billId);
            if (bill == null) return NotFound("bill_id");

            bench.BillStack.Delete(bill);
            return Ok(new { removed = bill.Label, bench = ((Thing)bench).def.label });
        }

        // ── Colonist assignments ──────────────────────────────────────────────

        public static (int, string) SetAllowedArea(string body)
        {
            var cmd  = Parse(body);
            var pawn = Colonist(cmd, "pawn_id");
            if (pawn == null) return NotFound("pawn_id");

            int areaId = cmd["area_id"]?.Value<int>() ?? -1;
            Area? area = areaId < 0
                ? null
                : pawn.Map.areaManager.AllAreas.FirstOrDefault(a => a.ID == areaId);

            if (areaId >= 0 && area == null) return NotFound("area_id");

            // In 1.6 the setter is AreaRestriction on Pawn_PlayerSettings
            pawn.playerSettings.GetType()
                .GetProperty("AreaRestriction",
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)
                ?.SetValue(pawn.playerSettings, area);

            return Ok(new { pawn = pawn.Name.ToStringShort, area = area?.Label ?? "unrestricted" });
        }

        // ── Schedule / passion ────────────────────────────────────────────────

        public static (int, string) SetScheduleHour(string body)
        {
            var cmd  = Parse(body);
            var pawn = Colonist(cmd, "pawn_id");
            if (pawn == null) return NotFound("pawn_id");

            int hour = cmd["hour"]?.Value<int>() ?? 0;
            if (hour < 0 || hour > 23) return Bad("Hour must be 0-23");

            string assignStr = cmd["assignment"]?.Value<string>() ?? "Work";
            var assignment   = DefDatabase<TimeAssignmentDef>.AllDefsListForReading
                .FirstOrDefault(d =>
                    d.defName.Equals(assignStr, StringComparison.OrdinalIgnoreCase) ||
                    d.label.Equals(assignStr, StringComparison.OrdinalIgnoreCase));

            if (assignment == null)
                return Bad($"Unknown assignment '{assignStr}'. Valid: Work, Sleep, Joy, Anything");

            pawn.timetable.SetAssignment(hour, assignment);
            return Ok(new { pawn = pawn.Name.ToStringShort, hour, assignment = assignment.label });
        }

        public static (int, string) SetPassion(string body)
        {
            var cmd  = Parse(body);
            var pawn = Colonist(cmd, "pawn_id");
            if (pawn == null) return NotFound("pawn_id");

            string skillDefName = cmd["skill_def"]?.Value<string>() ?? "";
            string passionStr   = cmd["passion"]?.Value<string>() ?? "None";

            var skillDef = DefDatabase<SkillDef>.GetNamedSilentFail(skillDefName);
            if (skillDef == null) return Bad($"Unknown SkillDef '{skillDefName}'");

            if (!System.Enum.TryParse<Passion>(passionStr, true, out var passion))
                return Bad($"Unknown passion '{passionStr}'. Valid: None, Minor, Major");

            var rec = pawn.skills?.GetSkill(skillDef);
            if (rec == null) return Bad("Pawn does not have that skill");

            rec.passion = passion;
            return Ok(new { pawn = pawn.Name.ToStringShort, skill = skillDef.label, passion = passion.ToString() });
        }

        // ── Growing zones ─────────────────────────────────────────────────────

        public static (int, string) SetZonePlant(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string zoneId    = cmd["zone_id"]?.Value<string>() ?? "";
            string plantName = cmd["plant_def"]?.Value<string>() ?? "";

            var zone = map.zoneManager.AllZones.OfType<Zone_Growing>()
                .FirstOrDefault(z => z.ID.ToString() == zoneId || z.label == zoneId);
            if (zone == null) return NotFound("zone_id (must be a growing zone label or ID)");

            var plant = DefDatabase<ThingDef>.GetNamedSilentFail(plantName);
            if (plant == null) return Bad($"Unknown plant def '{plantName}'");
            if (plant.plant == null || !plant.plant.Sowable)
                return Bad($"'{plantName}' is not a sowable plant");

            zone.SetPlantDefToGrow(plant);
            return Ok(new { zone = zone.label, plant = plant.label });
        }

        // ── Stockpile management ──────────────────────────────────────────────

        public static (int, string) SetStockpilePriority(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string zoneId   = cmd["zone_id"]?.Value<string>() ?? "";
            string priStr   = cmd["priority"]?.Value<string>() ?? "Normal";

            var zone = map.zoneManager.AllZones.OfType<Zone_Stockpile>()
                .FirstOrDefault(z => z.ID.ToString() == zoneId || z.label == zoneId);
            if (zone == null) return NotFound("zone_id (must be a stockpile label or ID)");

            if (!System.Enum.TryParse<StoragePriority>(priStr, true, out var priority))
                return Bad($"Unknown priority '{priStr}'. Valid: Unstored, Low, Normal, Preferred, Important, Critical");

            zone.GetStoreSettings().Priority = priority;
            return Ok(new { zone = zone.label, priority = priority.ToString() });
        }

        public static (int, string) SetStockpileFilter(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string zoneId  = cmd["zone_id"]?.Value<string>() ?? "";
            string action  = cmd["action"]?.Value<string>()?.ToLower() ?? "allow";  // allow, disallow, clear
            string defName = cmd["def_name"]?.Value<string>() ?? "";
            string defType = cmd["def_type"]?.Value<string>()?.ToLower() ?? "thing"; // thing, category

            var zone = map.zoneManager.AllZones.OfType<Zone_Stockpile>()
                .FirstOrDefault(z => z.ID.ToString() == zoneId || z.label == zoneId);
            if (zone == null) return NotFound("zone_id");

            var filter = zone.GetStoreSettings().filter;

            if (action == "clear")
            {
                filter.SetDisallowAll();
                return Ok(new { zone = zone.label, action = "cleared all" });
            }

            bool allow = action == "allow";

            if (defType == "category")
            {
                var cat = DefDatabase<ThingCategoryDef>.GetNamedSilentFail(defName);
                if (cat == null) return Bad($"Unknown ThingCategoryDef '{defName}'");
                filter.SetAllow(cat, allow);
                return Ok(new { zone = zone.label, action, category = cat.label });
            }
            else
            {
                var def = DefDatabase<ThingDef>.GetNamedSilentFail(defName);
                if (def == null) return Bad($"Unknown ThingDef '{defName}'");
                filter.SetAllow(def, allow);
                return Ok(new { zone = zone.label, action, thing = def.label });
            }
        }

        // ── Medical ───────────────────────────────────────────────────────────

        public static (int, string) MedicalOp(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string targetId  = cmd["pawn_id"]?.Value<string>() ?? "";
            string recipeDef = cmd["recipe_def"]?.Value<string>() ?? "";
            string partDef   = cmd["part_def"]?.Value<string>() ?? "";

            var pawn = map.mapPawns.AllPawnsSpawned.FirstOrDefault(p =>
                p.ThingID == targetId ||
                p.Name?.ToStringShort.Equals(targetId, StringComparison.OrdinalIgnoreCase) == true);
            if (pawn == null) return NotFound("pawn_id");

            var recipe = DefDatabase<RecipeDef>.GetNamedSilentFail(recipeDef);
            if (recipe == null) return Bad($"Unknown RecipeDef '{recipeDef}'");

            var bill = recipe.MakeNewBill() as Bill_Medical;
            if (bill == null) return Bad("Recipe is not a medical procedure");

            if (!string.IsNullOrEmpty(partDef))
            {
                var part = pawn.health.hediffSet.GetNotMissingParts()
                    .FirstOrDefault(p2 => p2.def.defName == partDef);
                if (part != null) bill.Part = part;
            }

            pawn.health.surgeryBills.AddBill(bill);
            return Ok(new { pawn = pawn.Name?.ToStringShort ?? pawn.LabelShort, operation = recipe.label, part = bill.Part?.Label ?? "any" });
        }

        // ── Designations ──────────────────────────────────────────────────────

        public static (int, string) Deconstruct(string body)
        {
            var cmd = Parse(body);
            var map = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string thingId = cmd["thing_id"]?.Value<string>() ?? "";
            var thing      = map.listerThings.AllThings.FirstOrDefault(t => t.ThingID == thingId);
            if (thing == null) return NotFound("thing_id");

            if (map.designationManager.DesignationOn(thing, DesignationDefOf.Deconstruct) != null)
                return Bad("Already designated for deconstruction");

            map.designationManager.AddDesignation(new Designation(thing, DesignationDefOf.Deconstruct));
            return Ok(new { designated = thing.def.label, position = new { x = thing.Position.x, z = thing.Position.z } });
        }

        // ── Areas / zones ─────────────────────────────────────────────────────

        public static (int, string) AreaPaint(string body)
        {
            var cmd   = Parse(body);
            var map   = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            int areaId  = cmd["area_id"]?.Value<int>() ?? -1;
            int x1      = cmd["x1"]?.Value<int>() ?? 0;
            int z1      = cmd["z1"]?.Value<int>() ?? 0;
            int x2      = cmd["x2"]?.Value<int>() ?? 0;
            int z2      = cmd["z2"]?.Value<int>() ?? 0;
            bool include = cmd["include"]?.Value<bool>() ?? true;

            var area = map.areaManager.AllAreas.FirstOrDefault(a => a.ID == areaId) as Area_Allowed;
            if (area == null) return NotFound("area_id (must be a mutable allowed area)");

            var rect  = new CellRect(x1, z1, x2 - x1 + 1, z2 - z1 + 1).ClipInsideMap(map);
            int count = 0;
            foreach (var cell in rect) { area[cell] = include; count++; }

            return Ok(new { area = area.Label, cells = count, include });
        }

        public static (int, string) CreateAllowedArea(string body)
        {
            var cmd  = Parse(body);
            var map  = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string label = cmd["label"]?.Value<string>() ?? "New Area";
            Area_Allowed? area = null;
            map.areaManager.TryMakeNewAllowed(out area);
            if (area == null) return Bad("Could not create area");
            area.SetLabel(label);

            return Ok(new { id = area.ID, label = area.Label });
        }

        public static (int, string) ClearArea(string body)
        {
            var cmd    = Parse(body);
            var map    = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            int areaId = cmd["area_id"]?.Value<int>() ?? -1;
            var area   = map.areaManager.AllAreas.FirstOrDefault(a => a.ID == areaId) as Area_Allowed;
            if (area == null) return NotFound("area_id (must be a mutable allowed area)");

            foreach (var cell in map.AllCells.Where(c => area[c]))
                area[cell] = false;

            return Ok(new { cleared = area.Label });
        }

        public static (int, string) DeleteArea(string body)
        {
            var cmd    = Parse(body);
            var map    = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            int areaId = cmd["area_id"]?.Value<int>() ?? -1;
            var area   = map.areaManager.AllAreas.FirstOrDefault(a => a.ID == areaId) as Area_Allowed;
            if (area == null) return NotFound("area_id (must be a mutable allowed area)");

            string label = area.Label;
            map.areaManager.AllAreas.Remove(area);
            return Ok(new { deleted = label });
        }

        public static (int, string) DeleteZone(string body)
        {
            var cmd   = Parse(body);
            var map   = Find.CurrentMap;
            if (map == null) return Bad("No active map");

            string zoneId = cmd["zone_id"]?.Value<string>() ?? "";
            var zone      = map.zoneManager.AllZones
                .FirstOrDefault(z => z.ID.ToString() == zoneId || z.label == zoneId);
            if (zone == null) return NotFound("zone_id");

            string label = zone.label;
            map.zoneManager.DeregisterZone(zone);
            return Ok(new { deleted = label });
        }

        // ── Game control ──────────────────────────────────────────────────────

        public static (int, string) SetPause(string body)
        {
            var cmd    = Parse(body);
            bool pause = cmd["paused"]?.Value<bool>() ?? true;
            if (pause) Find.TickManager.Pause();
            else       Find.TickManager.CurTimeSpeed = TimeSpeed.Normal;
            return Ok(new { paused = Find.TickManager.Paused, speed = Find.TickManager.CurTimeSpeed.ToString() });
        }

        public static (int, string) SetSpeed(string body)
        {
            var cmd   = Parse(body);
            int speed = cmd["speed"]?.Value<int>() ?? 1;
            var ts    = speed switch
            {
                0 => TimeSpeed.Paused,
                2 => TimeSpeed.Fast,
                3 => TimeSpeed.Superfast,
                4 => TimeSpeed.Ultrafast,
                _ => TimeSpeed.Normal
            };
            Find.TickManager.CurTimeSpeed = ts;
            return Ok(new { speed = Find.TickManager.CurTimeSpeed.ToString() });
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private static JObject Parse(string body)
        {
            try   { return JObject.Parse(body); }
            catch { return new JObject(); }
        }

        private static Pawn? Colonist(JObject cmd, string field)
        {
            var id = cmd[field]?.Value<string>() ?? "";
            return GameStateReader.FindColonist(id);
        }

        private static (int, string) Ok(object data) =>
            (200, JsonConvert.SerializeObject(data));

        private static (int, string) Bad(string msg) =>
            (400, JsonConvert.SerializeObject(new { error = msg }));

        private static (int, string) NotFound(string field) =>
            (404, JsonConvert.SerializeObject(new { error = $"'{field}' not found on map" }));
    }
}
