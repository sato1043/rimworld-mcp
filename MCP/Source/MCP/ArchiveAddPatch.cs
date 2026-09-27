using HarmonyLib;
using RimWorld;
using Verse;

namespace MCP
{
    /// <summary>
    /// Numbers an entry as it enters the game's archive, so entries are returned in the
    /// order they entered. Before, not after: Add sorts and drops within itself, and a
    /// drop of this very entry must find it already numbered. The parameter is taken by
    /// position, so a renamed parameter in the game does not unhook it.
    /// </summary>
    [HarmonyPatch(typeof(Archive), ArchiveAddPatch.Method)]
    internal static class ArchiveAddPatch
    {
        /// <summary>The patched method, named once for the patch and for its check.</summary>
        internal const string Method = nameof(Archive.Add);

        /// <summary>
        /// Runs ahead of other mods' prefixes at the same or lower priority, so an entry a
        /// mod puts in the archive itself, in place of Add, is numbered before it enters.
        /// Hands the number it gave to the finalizer.
        /// </summary>
        [HarmonyPriority(Priority.First)]
        private static void Prefix(Archive __instance, IArchivable __0, out long __state) =>
            __state = ArchiveEvents.Follow("numbering an added entry", (Archive: __instance, Entry: __0), static (ledger, call) =>
            {
                // Add refuses an entry it already holds, so that is not an arrival.
                if (call.Entry == null || call.Archive != Find.Archive || call.Archive.Contains(call.Entry)) return 0L;
                return ledger.Entering(call.Entry);
            }, 0L);

        /// <summary>
        /// Gives back the number the prefix gave when the entry did not enter, as when a
        /// mod cancels the add or the add throws: that is not a drop. A finalizer, and the
        /// last one, because it runs after every postfix and even when the add throws, so
        /// it sees where the entry ended up. An entry dropped inside Add has already left
        /// the ledger through the remove patch, so there is nothing to give back.
        /// </summary>
        [HarmonyPriority(Priority.Last)]
        private static void Finalizer(Archive __instance, IArchivable __0, long __state)
        {
            if (__state == 0) return;
            ArchiveEvents.Follow("taking back a number the add did not use", (Archive: __instance, Entry: __0, Number: __state), static (ledger, call) =>
            {
                if (!call.Archive.Contains(call.Entry)) ledger.Withdraw(call.Entry, call.Number);
            });
        }
    }
}
