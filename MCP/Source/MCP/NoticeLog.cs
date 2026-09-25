using System;
using System.Collections.Concurrent;
using System.Threading;

namespace MCP
{
    /// <summary>
    /// Collects things worth telling the player about, counts repeats, and hands
    /// them over on request.
    ///
    /// Two problems meet here. Requests are served on thread pool workers, and the
    /// game's log is not something to call from one; and a page that keeps probing
    /// the bridge would fill that log with the same line. Counting on the worker
    /// and writing on the game thread solves the first. Writing at doubling counts
    /// (1st, 2nd, 4th, 8th, ...) solves the second without losing the fact that it
    /// happened, or the scale: suppressing repeats outright leaves a probe
    /// indistinguishable from a single mistake.
    ///
    /// References nothing from RimWorld or Unity, so the behaviour can be tested.
    /// </summary>
    internal sealed class NoticeLog
    {
        /// <summary>Stands in for kinds beyond the cap, so a caller that builds
        /// kinds from variable text cannot grow this without bound.</summary>
        public const string OverflowKind = "(further kinds)";

        private sealed class Notice
        {
            public long Count;
            public long Reported;
            public string? Detail;
        }

        private readonly int _maxKinds;
        private readonly ConcurrentDictionary<string, Notice> _notices =
            new ConcurrentDictionary<string, Notice>(StringComparer.Ordinal);

        private long _recorded;
        private long _flushedAt;

        /// <param name="maxKinds">
        /// How many kinds are tracked by name. Everything after that is counted
        /// under <see cref="OverflowKind"/>, so the number held is at most
        /// maxKinds + 1.
        /// </param>
        public NoticeLog(int maxKinds = 32)
        {
            if (maxKinds < 1) throw new ArgumentOutOfRangeException(nameof(maxKinds));
            _maxKinds = maxKinds;
        }

        /// <summary>Records one occurrence. Safe to call from any thread.</summary>
        /// <param name="kind">What happened. Repeats are counted under this.</param>
        /// <param name="detail">Kept from the first occurrence only.</param>
        public void Record(string kind, string? detail = null)
        {
            if (kind == null) throw new ArgumentNullException(nameof(kind));

            var key = kind;
            if (!_notices.ContainsKey(key) && _notices.Count >= _maxKinds)
                key = OverflowKind;

            var notice = _notices.GetOrAdd(key, _ => new Notice { Detail = detail });
            Interlocked.Increment(ref notice.Count);
            Interlocked.Increment(ref _recorded);
        }

        /// <summary>
        /// Hands over the notices that are due. Call from one thread only - the
        /// game thread - because it advances what has been reported.
        /// </summary>
        public void Flush(Action<string> write)
        {
            if (write == null) throw new ArgumentNullException(nameof(write));

            // Nothing below depends on this early return: the cadence alone already
            // writes nothing when no count has moved, and removing it fails no test.
            // It is here because the game calls this every frame, and the loop below
            // allocates an enumerator each time it is entered.
            var recorded = Interlocked.Read(ref _recorded);
            if (recorded == _flushedAt) return;
            _flushedAt = recorded;

            foreach (var pair in _notices)
            {
                var notice = pair.Value;
                var count = Interlocked.Read(ref notice.Count);
                var due = notice.Reported == 0 ? 1 : notice.Reported * 2;
                if (count < due) continue;

                notice.Reported = count;
                write(Describe(pair.Key, count, notice.Detail));
            }
        }

        /// <summary>Forgets everything. For a restart of the thing being watched.</summary>
        public void Clear()
        {
            _notices.Clear();
            Interlocked.Exchange(ref _recorded, 0);
            _flushedAt = 0;
        }

        private static string Describe(string kind, long count, string? detail)
        {
            // The count says what it counts, so a reader is not left guessing
            // whether it is a total or the number since the last line.
            var text = count == 1
                ? kind
                : kind + " (" + count + " so far)";
            return string.IsNullOrEmpty(detail) ? text : text + " " + detail;
        }
    }
}
