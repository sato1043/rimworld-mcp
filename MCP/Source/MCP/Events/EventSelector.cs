using System;
using System.Collections.Generic;
using System.Linq;

namespace MCP
{
    /// <summary>
    /// Chooses which archived entries a read returns. References nothing from RimWorld
    /// or Unity, so the rules can be tested without the game.
    /// </summary>
    internal static class EventSelector
    {
        public const int DefaultLimit = 30;
        public const int MaxLimit = 200;

        /// <param name="numbers">The ledger number of each entry in the archive, in any order.</param>
        /// <param name="since">Where the caller left off, or null to read the latest.</param>
        /// <param name="limit">How many entries to return at most.</param>
        /// <param name="generation">Identifies the current load.</param>
        /// <param name="ledger">The ledger the numbers came from, as it stood when they were taken.</param>
        public static EventSelection Select(
            IReadOnlyList<long> numbers,
            EventCursor? since,
            int limit,
            string generation,
            LedgerState ledger)
        {
            if (numbers == null) throw new ArgumentNullException(nameof(numbers));
            if (limit < 1) throw new ArgumentOutOfRangeException(nameof(limit));

            var ordered = Enumerable.Range(0, numbers.Count).OrderBy(i => numbers[i]).ToList();
            var reloaded = since != null && since.Generation != generation;
            // A cursor of this load beyond any number given was never issued, so where
            // its reader left off is unknown: it starts over, told it may have missed some.
            var unissued = !reloaded && since != null && since.Number > ledger.HighestNumber;
            var from = reloaded || unissued ? null : since;

            if (from == null)
            {
                // The latest, and a cursor at the highest number given: what came before
                // is treated as read, so nothing more follows.
                var latest = ordered.Skip(Math.Max(0, ordered.Count - limit)).ToList();
                return new EventSelection(latest, new EventCursor(generation, ledger.HighestNumber), unissued, reloaded, more: false);
            }

            var after = ordered.Where(i => numbers[i] > from.Number).ToList();
            var chosen = after.Take(limit).ToList();
            var cut = after.Count > limit;
            // Cut by the limit, the cursor stops at the last entry returned. Otherwise it
            // moves to the highest number given, past any that left unread, which this
            // response reports through the gap.
            var next = cut
                ? numbers[chosen[chosen.Count - 1]]
                : ledger.HighestNumber;
            var gap = !ledger.Reliable || ledger.HighestDropped > from.Number;

            return new EventSelection(chosen, new EventCursor(generation, next), gap, reloaded: false, more: cut);
        }
    }
}
