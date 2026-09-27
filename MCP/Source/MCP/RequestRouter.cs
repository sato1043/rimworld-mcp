using Newtonsoft.Json;

namespace MCP
{
    internal static class RequestRouter
    {
        public static (int statusCode, string body) Handle(PendingRequest req)
        {
            return req.Method switch
            {
                "GET"  => HandleGet(req.Path, req.QueryString),
                "POST" => HandlePost(req.Path, req.Body),
                _      => (405, "{\"error\":\"Method not allowed\"}")
            };
        }

        private static (int, string) HandleGet(string path, string query) => path switch
        {
            "/ping"         => (200, "{\"status\":\"pong\"}"),
            "/state"        => Ok(GameStateReader.GetWorldState()),
            "/pawns"        => Ok(GameStateReader.GetColonists()),
            "/animals"      => Ok(GameStateReader.GetAnimals()),
            "/enemies"      => Ok(GameStateReader.GetEnemies()),
            "/fertility"    => Ok(GameStateReader.GetFertilityMap()),
            "/things"       => Ok(GameStateReader.GetThings()),
            "/buildings"    => Ok(GameStateReader.GetBuildings()),
            "/research"     => Ok(GameStateReader.GetResearch()),
            "/weather"      => Ok(GameStateReader.GetWeather()),
            "/designations" => Ok(GameStateReader.GetDesignations()),
            "/power"        => Ok(GameStateReader.GetPower()),
            "/rooms"        => Ok(GameStateReader.GetRooms()),
            "/zones"        => Ok(GameStateReader.GetZones()),
            "/prisoners"    => Ok(GameStateReader.GetPrisoners()),
            "/colony"       => Ok(GameStateReader.GetColony()),
            "/threats"      => Ok(GameStateReader.GetThreats()),
            "/traders"      => Ok(GameStateReader.GetTraders()),
            "/quests"       => Ok(GameStateReader.GetQuests()),
            "/ideology"          => Ok(GameStateReader.GetIdeology()),
            "/animals/training"  => Ok(GameStateReader.GetAnimalTraining()),
            "/caravans"          => Ok(GameStateReader.GetCaravans()),
            "/world/factions"    => Ok(GameStateReader.GetWorldFactions()),
            "/world/sites"       => Ok(GameStateReader.GetWorldSites()),
            "/messages"          => Ok(GameStateReader.GetMessages()),
            "/alerts"            => Ok(GameStateReader.GetAlerts()),
            "/medical"           => Ok(GameStateReader.GetMedical()),
            "/production"        => Ok(GameStateReader.GetProduction()),
            "/apparel"           => Ok(GameStateReader.GetApparel()),
            "/areas"             => Ok(GameStateReader.GetAreas()),
            "/social"            => Ok(GameStateReader.GetColonySocial()),
            "/stockpiles"        => Ok(GameStateReader.GetStockpileContents()),
            "/corpses"           => Ok(GameStateReader.GetCorpses()),
            "/drug_policies"     => Ok(GameStateReader.GetDrugPolicies()),
            "/room_assignments"  => Ok(GameStateReader.GetRoomAssignments()),
            "/mechs"             => Ok(GameStateReader.GetMechs()),
            "/incidents"         => Ok(GameStateReader.GetIncidents()),
            "/events"            => HandleEvents(query),
            _ when path.StartsWith("/cell/")  => HandleCellPath(path),
            _ when path.StartsWith("/cells/") => HandleCellsRectPath(path),
            _ when path.StartsWith("/pawn/")  => HandlePawnPath(path),
            _ => (404, "{\"error\":\"Not found\"}")
        };

        private static (int, string) HandleCellsRectPath(string path)
        {
            // /cells/{x1}/{z1}/{x2}/{z2}
            var parts = path.Substring("/cells/".Length).Split('/');
            if (parts.Length < 4) return (400, "{\"error\":\"Expected /cells/{x1}/{z1}/{x2}/{z2}\"}");
            if (!int.TryParse(parts[0], out int x1) || !int.TryParse(parts[1], out int z1) ||
                !int.TryParse(parts[2], out int x2) || !int.TryParse(parts[3], out int z2))
                return (400, "{\"error\":\"Invalid coordinates\"}");
            return Ok(GameStateReader.GetCellsRect(x1, z1, x2, z2));
        }

        private static (int, string) HandleCellPath(string path)
        {
            var rest  = path.Substring("/cell/".Length); // "50/80"
            var slash = rest.IndexOf('/');
            if (slash < 0) return (400, "{\"error\":\"Expected /cell/{x}/{z}\"}");
            if (!int.TryParse(rest.Substring(0, slash), out int x)) return (400, "{\"error\":\"Invalid x\"}");
            if (!int.TryParse(rest.Substring(slash + 1), out int z)) return (400, "{\"error\":\"Invalid z\"}");
            return Ok(GameStateReader.GetCellInfo(x, z));
        }

        private static (int, string) HandlePawnPath(string path)
        {
            var rest  = path.Substring("/pawn/".Length);
            var slash = rest.IndexOf('/');

            if (slash < 0)
                return Ok(GameStateReader.GetPawn(rest));

            var id  = rest.Substring(0, slash);
            var sub = rest.Substring(slash + 1);

            return sub switch
            {
                "health"    => Ok(GameStateReader.GetPawnHealth(id)),
                "needs"     => Ok(GameStateReader.GetPawnNeeds(id)),
                "mood"      => Ok(GameStateReader.GetPawnMood(id)),
                "inventory" => Ok(GameStateReader.GetPawnInventory(id)),
                "backstory"  => Ok(GameStateReader.GetPawnBackstory(id)),
                "capacities" => Ok(GameStateReader.GetPawnCapacities(id)),
                "psycasts"   => Ok(GameStateReader.GetPawnPsycasts(id)),
                "genes"      => Ok(GameStateReader.GetPawnGenes(id)),
                "area"       => Ok(GameStateReader.GetPawnArea(id)),
                "traits"    => Ok(GameStateReader.GetPawnTraits(id)),
                "relations" => Ok(GameStateReader.GetPawnRelations(id)),
                "work"      => Ok(GameStateReader.GetPawnWork(id)),
                "schedule"  => Ok(GameStateReader.GetPawnSchedule(id)),
                _ => (404, "{\"error\":\"Unknown pawn sub-path\"}")
            };
        }

        private static (int, string) HandlePost(string path, string body) => path switch
        {
            "/command/draft"    => CommandExecutor.Draft(body),
            "/command/move"     => CommandExecutor.Move(body),
            "/command/attack"   => CommandExecutor.Attack(body),
            "/command/job"      => CommandExecutor.AssignJob(body),
            "/command/hunt"     => CommandExecutor.Hunt(body),
            "/command/mine"     => CommandExecutor.Mine(body),
            "/command/cut"      => CommandExecutor.CutPlant(body),
            "/command/build"    => CommandExecutor.Build(body),
            "/command/research" => CommandExecutor.SetResearch(body),
            "/command/forbid"   => CommandExecutor.ForbidThing(body),
            "/command/rescue"   => CommandExecutor.Rescue(body),
            "/command/pause"       => CommandExecutor.SetPause(body),
            "/command/speed"       => CommandExecutor.SetSpeed(body),
            "/command/equip"       => CommandExecutor.EquipItem(body),
            "/command/recruit"     => CommandExecutor.RecruitPrisoner(body),
            "/command/assign_bed"  => CommandExecutor.AssignBed(body),
            "/command/add_bill"    => CommandExecutor.AddBill(body),
            "/command/remove_bill"    => CommandExecutor.RemoveBill(body),
            "/command/set_area"             => CommandExecutor.SetAllowedArea(body),
            "/command/set_schedule"         => CommandExecutor.SetScheduleHour(body),
            "/command/set_passion"          => CommandExecutor.SetPassion(body),
            "/command/set_zone_plant"       => CommandExecutor.SetZonePlant(body),
            "/command/set_stockpile_priority" => CommandExecutor.SetStockpilePriority(body),
            "/command/set_stockpile_filter" => CommandExecutor.SetStockpileFilter(body),
            "/command/medical_op"           => CommandExecutor.MedicalOp(body),
            "/command/deconstruct"          => CommandExecutor.Deconstruct(body),
            "/command/area_paint"           => CommandExecutor.AreaPaint(body),
            "/command/create_area"   => CommandExecutor.CreateAllowedArea(body),
            "/command/clear_area"    => CommandExecutor.ClearArea(body),
            "/command/delete_area"   => CommandExecutor.DeleteArea(body),
            "/command/delete_zone"   => CommandExecutor.DeleteZone(body),
            _ => (404, "{\"error\":\"Not found\"}")
        };

        private static (int, string) HandleEvents(string query)
        {
            if (!EventQuery.TryRead(query, out var since, out var limit, out var refusal))
                return (400, JsonConvert.SerializeObject(new { error = refusal }));
            return Ok(ArchiveEvents.Read(since, limit));
        }

        private static (int, string) Ok(object data) =>
            (200, JsonConvert.SerializeObject(data));
    }
}
