using System;
using System.Collections.Generic;
using System.Linq;

namespace MCP
{
    /// <summary>
    /// Numbers archive entries in the order they entered, and remembers the highest
    /// number among those that left.
    ///
    /// Nothing the game keeps gives that order. The archive sorts by tick with an
    /// unstable sort, and the tick stands still while the game is paused; a letter
    /// takes its game number when it is made and its tick when it arrives; a message
    /// takes its game number when it is made, not when it is sent. So the order is
    /// taken where it happens: the game is expected to call <see cref="Entering"/> as an
    /// entry goes in and <see cref="Removed"/> as one goes out, including the ones the
    /// archive drops as it adds. Entries are told apart by reference.
    ///
    /// Not locked: it is used from one thread at a time. Reads run on the game's thread,
    /// in the component's update. The patches can also run on the loading thread, and
    /// the game is taken not to update components while it loads, so the two do not
    /// overlap; that is the game's behaviour, not something this class checks.
    /// </summary>
    internal sealed class ArchiveLedger<T> where T : class
    {
        private readonly Func<T, EventStamp?> _stamp;
        private readonly Dictionary<T, long> _numbers = new Dictionary<T, long>(ReferenceComparer.Instance);

        /// <param name="stamp">The stamp of an entry, or null for a kind not reported.</param>
        public ArchiveLedger(Func<T, EventStamp?> stamp)
        {
            _stamp = stamp ?? throw new ArgumentNullException(nameof(stamp));
        }

        /// <summary>The highest number given so far; 0 before the first.</summary>
        public long HighestNumber { get; private set; }

        /// <summary>The highest number among entries that left; 0 when none has.</summary>
        public long HighestDropped { get; private set; }

        /// <summary>
        /// False once the game's calls could not be followed, after which what left
        /// can no longer be vouched for.
        /// </summary>
        public bool Reliable { get; private set; } = true;

        /// <summary>The three facts a read depends on, as they stand now.</summary>
        public LedgerState State => new LedgerState(HighestNumber, HighestDropped, Reliable);

        /// <summary>
        /// An entry the archive does not hold is about to enter it. One already numbered
        /// keeps its number: if an earlier Add failed without saying so, the next read's
        /// <see cref="Reconcile"/> counts the number as dropped, and the entry is
        /// numbered anew when it does arrive.
        /// </summary>
        /// <returns>The number given now, or 0 when none was.</returns>
        public long Entering(T entry)
        {
            if (entry == null) throw new ArgumentNullException(nameof(entry));
            if (_numbers.ContainsKey(entry) || _stamp(entry) == null) return 0;
            return _numbers[entry] = ++HighestNumber;
        }

        /// <summary>
        /// An entry announced by <see cref="Entering"/> did not enter after all, as when
        /// another mod cancels the add. The number that call gave is given up without
        /// counting as dropped: nobody could have read it. Any other number the entry has
        /// is left alone, so a number readers may have seen is never withdrawn. The number
        /// is not given again.
        /// </summary>
        /// <param name="number">The number <see cref="Entering"/> returned.</param>
        public void Withdraw(T entry, long number)
        {
            if (entry == null) throw new ArgumentNullException(nameof(entry));
            if (number != 0 && _numbers.TryGetValue(entry, out var held) && held == number)
                _numbers.Remove(entry);
        }

        /// <summary>An entry has left the archive.</summary>
        public void Removed(T entry)
        {
            if (entry == null) throw new ArgumentNullException(nameof(entry));
            if (_numbers.TryGetValue(entry, out var number))
            {
                _numbers.Remove(entry);
            }
            else
            {
                // Left without having been numbered, so it entered unseen. It is given a
                // number now, which puts it after every reader's cursor: they are told
                // they missed something, rather than not. An entry that entered unseen
                // means others can have come and gone unseen too.
                if (_stamp(entry) == null) return;
                number = ++HighestNumber;
                Reliable = false;
            }
            HighestDropped = Math.Max(HighestDropped, number);
        }

        /// <summary>
        /// Brings the ledger in line with what the archive holds, for whatever the calls
        /// did not report. A numbered entry the archive no longer holds left unreported,
        /// and counts as removed. An entry the archive holds without a number entered
        /// unreported, and is numbered after the others. Either means the calls are not
        /// all arriving, so an entry could also have entered and left between two reads
        /// without leaving a trace: the ledger stops vouching until it is restarted.
        /// </summary>
        public void Reconcile(IReadOnlyCollection<T> archive)
        {
            if (Absorb(archive)) Reliable = false;
        }

        /// <summary>
        /// Forgets everything, failures included, and numbers what the archive holds
        /// afresh. For the end of loading, before anyone has read: entries the game added
        /// while loading would otherwise come before the older entries loaded from the
        /// save, and whatever went wrong while following the load is rebuilt here. The
        /// entries loaded from the save never pass through Add, so numbering them here is
        /// expected and does not count against the ledger.
        /// </summary>
        public void Restart(IReadOnlyCollection<T> archive)
        {
            _numbers.Clear();
            HighestNumber = 0;
            HighestDropped = 0;
            Reliable = true;
            Absorb(archive);
        }

        /// <summary>
        /// Takes in what the archive holds, as <see cref="Reconcile"/> describes, and says
        /// whether anything was missing from the ledger. Entries without a number are
        /// numbered by tick, then kind, then the game's number: an order chosen here to be
        /// the same every time, since the archive's own sort is not.
        /// </summary>
        private bool Absorb(IReadOnlyCollection<T> archive)
        {
            if (archive == null) throw new ArgumentNullException(nameof(archive));

            var held = new HashSet<T>(archive, ReferenceComparer.Instance);
            var gone = _numbers.Keys.Where(e => !held.Contains(e)).ToList();
            foreach (var entry in gone)
                Removed(entry);

            var unnumbered = archive
                .Where(e => !_numbers.ContainsKey(e))
                .Select(e => (Entry: e, Stamp: _stamp(e)))
                .Where(x => x.Stamp != null)
                .Select(x => (x.Entry, Stamp: x.Stamp!.Value))
                .OrderBy(x => x.Stamp.Tick)
                .ThenBy(x => x.Stamp.Kind)
                .ThenBy(x => x.Stamp.Id)
                .ToList();
            foreach (var x in unnumbered)
                _numbers[x.Entry] = ++HighestNumber;

            return gone.Count > 0 || unnumbered.Count > 0;
        }

        /// <summary>
        /// One read of the archive: reconciles first, so an entry that entered unseen is
        /// returned late rather than never and one that left unseen counts as dropped,
        /// then chooses the entries through <see cref="EventSelector"/>. Returns them in
        /// the order they entered, each with its stamp. The selection's indices count
        /// only the reported entries, not the archive, so the entries are read from
        /// Events rather than looked up by index.
        /// </summary>
        /// <param name="archive">What the archive holds, in any order.</param>
        public (IReadOnlyList<(T Entry, EventStamp Stamp)> Events, EventSelection Selection) Read(
            IReadOnlyList<T> archive, EventCursor? since, int limit, string generation)
        {
            Reconcile(archive);

            var rows = new List<(T Entry, EventStamp Stamp, long Number)>();
            foreach (var entry in archive)
            {
                var stamp = _stamp(entry);
                if (stamp == null) continue;
                if (!_numbers.TryGetValue(entry, out var number))
                    throw new InvalidOperationException("An archive entry has no number right after reconciling.");
                rows.Add((entry, stamp.Value, number));
            }

            var selection = EventSelector.Select(rows.Select(r => r.Number).ToList(), since, limit, generation, State);
            return (selection.Indices.Select(i => (rows[i].Entry, rows[i].Stamp)).ToList(), selection);
        }

        public bool TryGetNumber(T entry, out long number) => _numbers.TryGetValue(entry, out number);

        /// <summary>The game's calls could not be followed; see <see cref="Reliable"/>.</summary>
        public void MarkUnreliable() => Reliable = false;

        /// <summary>Identity, not equality: two distinct entries are two entries.</summary>
        private sealed class ReferenceComparer : IEqualityComparer<object>
        {
            public static readonly ReferenceComparer Instance = new ReferenceComparer();
            bool IEqualityComparer<object>.Equals(object? x, object? y) => ReferenceEquals(x, y);
            public int GetHashCode(object obj) => System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
        }
    }
}
