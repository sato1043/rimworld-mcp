using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using MCP;
using Xunit;

namespace MCP.Tests
{
    /// <summary>
    /// What <see cref="NoticeLog"/> promises: nothing recorded is lost to the
    /// count, repeats are written at a doubling cadence rather than every time,
    /// and a caller that builds kinds from variable text cannot grow it without
    /// bound. Each case names one of those, so removing one fails an identifiable
    /// test rather than shrinking a number.
    /// </summary>
    public class NoticeLogTests
    {
        private static List<string> Drain(NoticeLog log)
        {
            var written = new List<string>();
            log.Flush(written.Add);
            return written;
        }

        // ── Writing at all ───────────────────────────────────────────────────

        [Fact]
        public void WritesNothingWhenNothingWasRecorded()
            => Assert.Empty(Drain(new NoticeLog()));

        [Fact]
        public void WritesTheFirstOccurrence()
        {
            var log = new NoticeLog();
            log.Record("refused");
            Assert.Equal(new[] { "refused" }, Drain(log));
        }

        [Fact]
        public void KeepsTheDetailOfTheFirstOccurrenceOnly()
        {
            var log = new NoticeLog();
            log.Record("failed", "first");
            log.Record("failed", "second");
            Assert.Contains("first", Drain(log).Single());
        }

        [Fact]
        public void WritesNothingOnASecondFlushWithNothingNew()
        {
            var log = new NoticeLog();
            log.Record("refused");
            Drain(log);
            Assert.Empty(Drain(log));
        }

        // ── The doubling cadence ─────────────────────────────────────────────

        [Fact]
        public void WritesAtDoublingCountsAndNotInBetween()
        {
            // Flushing after every single record is the worst case for the
            // cadence: if it wrote every time, this would produce nine lines.
            var log = new NoticeLog();
            var written = new List<string>();
            for (var i = 0; i < 9; i++)
            {
                log.Record("refused");
                log.Flush(written.Add);
            }

            Assert.Equal(4, written.Count);   // occurrences 1, 2, 4, 8
            Assert.Equal("refused", written[0]);
            Assert.Contains("2 so far", written[1]);
            Assert.Contains("4 so far", written[2]);
            Assert.Contains("8 so far", written[3]);
        }

        [Fact]
        public void ReportsTheRunningTotalNotTheNumberSinceTheLastLine()
        {
            var log = new NoticeLog();
            for (var i = 0; i < 4; i++) log.Record("refused");
            Assert.Contains("4 so far", Drain(log).Single());
        }

        [Fact]
        public void CountsRepeatsThatArriveBetweenTwoFlushes()
        {
            var log = new NoticeLog();
            log.Record("refused");
            Drain(log);
            for (var i = 0; i < 7; i++) log.Record("refused");
            Assert.Contains("8 so far", Drain(log).Single());
        }

        [Fact]
        public void KeepsKindsApart()
        {
            var log = new NoticeLog();
            log.Record("refused");
            log.Record("failed");
            Assert.Equal(2, Drain(log).Count);
        }

        [Fact]
        public void DoesNotWriteTheSingularFormWithACount()
        {
            var log = new NoticeLog();
            log.Record("refused");
            Assert.DoesNotContain("so far", Drain(log).Single());
        }

        // ── The cap on kinds ─────────────────────────────────────────────────

        [Fact]
        public void FoldsKindsBeyondTheCapIntoOne()
        {
            var log = new NoticeLog(maxKinds: 3);
            for (var i = 0; i < 50; i++) log.Record("kind " + i);

            // Three kinds by name, plus the one bucket everything else folds
            // into: 50 distinct kinds must not become 50 entries.
            var written = Drain(log);
            Assert.Equal(4, written.Count);
            Assert.Contains(written, line => line.StartsWith(NoticeLog.OverflowKind));
        }

        [Fact]
        public void StillCountsTheFoldedOccurrences()
        {
            var log = new NoticeLog(maxKinds: 1);
            log.Record("first");
            for (var i = 0; i < 4; i++) log.Record("other " + i);

            var overflow = Drain(log).Single(l => l.StartsWith(NoticeLog.OverflowKind));
            Assert.Contains("4 so far", overflow);
        }

        [Fact]
        public void KeepsCountingAKindItAlreadyKnowsAfterTheCapIsReached()
        {
            var log = new NoticeLog(maxKinds: 1);
            log.Record("known");
            log.Record("other");
            log.Record("known");
            Assert.Contains("2 so far", Drain(log).Single(l => l.StartsWith("known")));
        }

        [Fact]
        public void RefusesACapBelowOne()
            => Assert.Throws<ArgumentOutOfRangeException>(() => new NoticeLog(0));

        [Fact]
        public void RefusesANullKind()
            => Assert.Throws<ArgumentNullException>(() => new NoticeLog().Record(null!));

        // ── Clearing ─────────────────────────────────────────────────────────

        [Fact]
        public void ForgetsEverythingWhenCleared()
        {
            var log = new NoticeLog();
            log.Record("refused");
            Drain(log);
            log.Clear();
            log.Record("refused");
            Assert.Equal(new[] { "refused" }, Drain(log));
        }

        // ── Concurrency ──────────────────────────────────────────────────────

        [Fact]
        public void LosesNoOccurrenceWhenManyThreadsRecordAtOnce()
        {
            // The whole reason this type exists is that requests arrive on thread
            // pool workers. A count that drops occurrences under contention would
            // understate exactly the case it was built for.
            const int threads = 8;
            const int each = 500;

            var log = new NoticeLog();
            Parallel.For(0, threads, _ =>
            {
                for (var i = 0; i < each; i++) log.Record("refused");
            });

            Assert.Contains($"{threads * each} so far", Drain(log).Single());
        }
    }
}
