using System;
using HarmonyLib;
using Verse;

namespace MCP
{
    public class MCPMod : Mod
    {
        private const string HarmonyId = "anthonyzolmora.MCP";

        public MCPMod(ModContentPack content) : base(content)
        {
            // The bridge starts whether or not patching succeeds. Without the archive
            // patches the event ledger reports gaps instead of vouching; that is checked
            // below, whatever happened here.
            try
            {
                new Harmony(HarmonyId).PatchAll();
            }
            catch (Exception ex)
            {
                Log.Error($"[MCP] Harmony patching failed. {ex}");
            }
            finally
            {
                // Asked whatever happened above: patching can fail after these took.
                try
                {
                    ArchivePatchState.Check(HarmonyId);
                }
                catch (Exception ex)
                {
                    Log.Error($"[MCP] Could not tell whether the archive patches took. {ex}");
                }
                if (!ArchivePatchState.Applied)
                    Log.Warning("[MCP] The archive patches are not applied; events will report gaps.");
            }

            MCPHttpServer.Start(8080);
        }
    }
}
