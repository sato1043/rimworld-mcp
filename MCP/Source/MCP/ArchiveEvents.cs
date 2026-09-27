using System;
using System.Collections.Generic;
using System.Linq;
using RimWorld;
using Verse;

namespace MCP
{
    /// <summary>
    /// The game's side of the events endpoint: which archive entries are events and what
    /// the ledger needs to know of them, reading the archive through the ledger, and
    /// following the archive from inside the game's own code. The rules themselves are in
    /// <see cref="ArchiveLedger{T}"/> and <see cref="EventSelector"/>.
    /// </summary>
    internal static class ArchiveEvents
    {
        /// <summary>
        /// Letters and messages from the archive, continuing from where the caller left
        /// off.
        /// </summary>
        public static object Read(EventCursor? since, int limit)
        {
            var component = Current.Game.GetComponent<MCPGameComponent>();
            var ledger = component.ArchiveLedger;
            var vouched = ledger.Reliable;
            var (events, selection) = ledger.Read(
                Find.Archive.ArchivablesListForReading, since, limit, component.Generation);

            // Only reconciling changes the ledger during a read, and it does so when the
            // archive held what the patches did not report.
            if (vouched && !ledger.Reliable) WarnMissed(component.Generation);

            return new
            {
                events = events.Select(e => (object)new
                {
                    tick  = e.Stamp.Tick,
                    kind  = EventKinds.Word(e.Stamp.Kind),
                    type  = DefNameOf(e.Entry, e.Stamp.Kind),
                    label = LabelOf(e.Entry, component.Generation)
                }).ToList(),
                next     = selection.Next.ToString(),
                more     = selection.More,
                gap      = selection.Gap,
                reloaded = selection.Reloaded
            };
        }

        /// <summary>
        /// The stamp of an archive entry the events endpoint reports, or null for other
        /// kinds. The archive is open to any IArchivable, mods' own included, so those
        /// are left out rather than refused.
        /// </summary>
        internal static EventStamp? StampOf(IArchivable entry) => entry switch
        {
            Letter letter   => new EventStamp(EventKind.Letter, letter.ID, entry.CreatedTicksGame),
            Message message => new EventStamp(EventKind.Message, MessageId(message), entry.CreatedTicksGame),
            _ => null
        };

        /// <summary>The def of an entry already known to be of the kind given.</summary>
        private static string? DefNameOf(IArchivable entry, EventKind kind) => kind switch
        {
            EventKind.Letter  => ((Letter)entry).def?.defName,
            EventKind.Message => ((Message)entry).def?.defName,
            _ => throw new ArgumentOutOfRangeException(nameof(kind), kind, null)
        };

        /// <summary>
        /// The entry's label, or null when the entry cannot produce one: one broken entry
        /// should not stop every read that includes it, and keep the cursor from moving.
        /// </summary>
        private static string? LabelOf(IArchivable entry, string generation)
        {
            try
            {
                return entry.ArchivedLabel;
            }
            catch (Exception ex)
            {
                if (FirstTime(generation + " label " + ex.GetType().FullName))
                    Log.Warning($"[MCP] An archive entry has no readable label; events report it without one. {ex}");
                return null;
            }
        }

        /// <summary>
        /// Message keeps its number private. The ledger uses it only to order, among
        /// entries it numbers by itself (those loaded from a save, or that entered
        /// unseen), messages of the same tick. A game version without the field loses
        /// that order alone, so the number is then taken as 0 rather than failing reads.
        /// </summary>
        private static readonly System.Reflection.FieldInfo? MessageIdField =
            typeof(Message).GetField("ID",
                System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);

        private static int MessageId(Message message) =>
            MessageIdField == null ? 0 : (int)MessageIdField.GetValue(message);

        /// <summary>
        /// What has already been logged, by load and what went wrong: a failure repeats
        /// on every call, and the first carries the stack. Locked: loading can run on
        /// the game's loading thread.
        /// </summary>
        private static readonly HashSet<string> Logged = new HashSet<string>();

        private static bool FirstTime(string key)
        {
            lock (Logged)
                return Logged.Add(key);
        }

        /// <summary>Says once per load that the patches missed what the archive did.</summary>
        private static void WarnMissed(string generation)
        {
            if (FirstTime(generation + " missed"))
                Log.Warning("[MCP] The archive patches missed entries that entered or left the archive; " +
                            "events report gaps until loading next finishes.");
        }

        /// <summary>
        /// Runs a step of following the archive, from inside the game's own code where an
        /// exception would break loading or the receiving of a letter. Finding the
        /// component is inside the guard too. A failure is logged once per step and
        /// exception type and leaves the ledger marked unreliable, so every later read
        /// reports a gap instead of vouching for what it cannot. A step that finds the
        /// patches missed something is logged too, once loading has finished: until then
        /// the entries loaded from the save are expected to be missing, and the numbering
        /// at the end of loading puts the ledger right. The argument is passed through
        /// rather than captured, so a call allocates no closure.
        /// </summary>
        /// <param name="otherwise">The result when the step did not run or failed.</param>
        internal static TResult Follow<TArg, TResult>(
            string step, TArg arg, Func<ArchiveLedger<IArchivable>, TArg, TResult> action, TResult otherwise)
        {
            MCPGameComponent? component = null;
            try
            {
                component = Current.Game?.GetComponent<MCPGameComponent>();
                if (component == null) return otherwise;
                var vouched = component.ArchiveLedger.Reliable;
                var result = action(component.ArchiveLedger, arg);
                if (vouched && !component.ArchiveLedger.Reliable && component.LoadFinished)
                    WarnMissed(component.Generation);
                return result;
            }
            catch (Exception ex)
            {
                component?.ArchiveLedger.MarkUnreliable();
                // Written to the game's log directly rather than through the notice log,
                // which folds kinds past its cap and would lose this line's stack.
                if (FirstTime(component?.Generation + " " + step + " " + ex.GetType().FullName))
                    Log.Warning($"[MCP] The event ledger failed while {step}; events report gaps until loading next finishes. {ex}");
                return otherwise;
            }
        }

        /// <inheritdoc cref="Follow{TArg, TResult}"/>
        internal static void Follow<TArg>(string step, TArg arg, Action<ArchiveLedger<IArchivable>, TArg> action) =>
            Follow(step, (Arg: arg, Action: action), static (ledger, call) =>
            {
                call.Action(ledger, call.Arg);
                return true;
            }, false);
    }
}
