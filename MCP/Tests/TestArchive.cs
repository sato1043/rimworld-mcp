using System.Collections.Generic;
using System.Linq;
using MCP;
using Xunit;

namespace MCP.Tests
{
    /// <summary>
    /// The game's archive as the patches see it: calls around each add and remove, and
    /// reads through the same <see cref="ArchiveLedger{T}.Read"/> the endpoint uses.
    /// </summary>
    internal sealed class TestArchive
    {
        public const string Gen = "g1";

        public static EventStamp L(int id, int tick) => new EventStamp(EventKind.Letter, id, tick);
        public static EventStamp M(int id, int tick) => new EventStamp(EventKind.Message, id, tick);

        public static EventCursor Cursor(long number) => new EventCursor(Gen, number);

        /// <summary>An archive entry: identity is the object, as in the game.</summary>
        public sealed class Entry
        {
            public readonly EventStamp? Stamp;
            public Entry(EventStamp? stamp) { Stamp = stamp; }
            // Equal to every other entry, so a ledger that compared by equality would mix them up.
            public override bool Equals(object? obj) => obj is Entry;
            public override int GetHashCode() => 0;
            public override string ToString() => Stamp == null ? "other" : $"{Stamp.Value.Kind}{Stamp.Value.Id}@{Stamp.Value.Tick}";
        }

        public readonly ArchiveLedger<Entry> Ledger = new ArchiveLedger<Entry>(e => e.Stamp);
        public readonly List<Entry> Present = new List<Entry>();

        public Entry Add(EventStamp? stamp)
        {
            var entry = new Entry(stamp);
            Ledger.Entering(entry);
            Present.Add(entry);
            return entry;
        }

        public void Remove(Entry entry)
        {
            // By reference: List.Remove would take the first entry equal to it, which is any.
            Present.RemoveAt(Present.FindIndex(e => ReferenceEquals(e, entry)));
            Ledger.Removed(entry);
        }

        /// <summary>An Add that another mod cancels after the patch has announced it.</summary>
        public Entry AddCancelled(EventStamp stamp)
        {
            var entry = new Entry(stamp);
            Ledger.Withdraw(entry, Ledger.Entering(entry));
            return entry;
        }

        /// <summary>What Add does when it drops the entry it was given.</summary>
        public Entry AddAndDrop(EventStamp stamp)
        {
            var entry = Add(stamp);
            Remove(entry);
            return entry;
        }

        public (List<Entry> Picked, EventSelection Selection) Read(
            EventCursor? since, int limit = 30, string generation = Gen)
        {
            // Listed by tick as the game lists them, and within a tick in the reverse of
            // the order they entered, since the game's sort keeps no order there: the
            // ledger has to restore the order they entered in.
            var listed = Present
                .Select((e, i) => (Entry: e, Index: i))
                .OrderBy(x => x.Entry.Stamp?.Tick ?? 0)
                .ThenByDescending(x => x.Index)
                .Select(x => x.Entry)
                .ToList();
            var (events, selection) = Ledger.Read(listed, since, limit, generation);
            return (events.Select(e => e.Entry).ToList(), selection);
        }

        public long Number(Entry entry)
        {
            Assert.True(Ledger.TryGetNumber(entry, out var number));
            return number;
        }

        /// <summary>
        /// The same entries in the same order, compared by reference. Assert.Equal would
        /// compare with Entry.Equals, which holds for any two entries.
        /// </summary>
        public static void AssertEntries(IEnumerable<Entry> expected, IEnumerable<Entry> actual)
        {
            var want = expected.ToList();
            var got = actual.ToList();
            Assert.True(want.Count == got.Count && want.Zip(got, ReferenceEquals).All(same => same),
                $"expected [{string.Join(", ", want)}] but got [{string.Join(", ", got)}]");
        }
    }
}
