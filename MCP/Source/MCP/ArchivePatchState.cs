using HarmonyLib;
using RimWorld;

namespace MCP
{
    /// <summary>Whether the patches on the game's archive took.</summary>
    internal static class ArchivePatchState
    {
        /// <summary>
        /// Whether both patches are in place, as Harmony reports after patching. Without
        /// them the ledger learns of entries only by comparing at read time, and cannot
        /// vouch for drops.
        /// </summary>
        public static bool Applied { get; private set; }

        /// <summary>Records whether both patches took, for <see cref="Applied"/>.</summary>
        public static void Check(string harmonyId)
        {
            bool Patched(string method) =>
                Harmony.GetPatchInfo(AccessTools.Method(typeof(Archive), method))?.Owners.Contains(harmonyId) == true;
            Applied = Patched(ArchiveAddPatch.Method) && Patched(ArchiveRemovePatch.Method);
        }
    }
}
