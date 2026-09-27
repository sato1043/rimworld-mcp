using HarmonyLib;
using RimWorld;
using Verse;

namespace MCP
{
    /// <summary>
    /// Notes an entry leaving the game's archive, including one dropped inside Add, which
    /// comparing the archive between reads could never see.
    /// </summary>
    [HarmonyPatch(typeof(Archive), ArchiveRemovePatch.Method)]
    internal static class ArchiveRemovePatch
    {
        /// <summary>The patched method, named once for the patch and for its check.</summary>
        internal const string Method = nameof(Archive.Remove);

        private static void Postfix(Archive __instance, IArchivable __0, bool __result)
        {
            if (!__result) return; // Remove found nothing to remove.
            ArchiveEvents.Follow("noting a removed entry", (Archive: __instance, Entry: __0), static (ledger, call) =>
            {
                if (call.Entry == null || call.Archive != Find.Archive) return;
                ledger.Removed(call.Entry);
            });
        }
    }
}
