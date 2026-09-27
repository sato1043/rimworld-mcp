using System;
using System.Linq;
using MCP;
using Xunit;
using static MCP.Tests.TestArchive;

namespace MCP.Tests
{
    /// <summary>
    /// What a reader who passes each response's cursor to the next read is promised:
    /// every entry comes back exactly once and in the order it entered the archive,
    /// including entries at a tick already read, delayed letters and messages sent out
    /// of number order; an entry that left before being read is reported, even one
    /// dropped as it was added; a read after loading starts over and says so. Read
    /// through the ledger, as the endpoint reads.
    /// </summary>
    public class EventSelectorTests
    {
        // ── Reading without a cursor ─────────────────────────────────────────

        [Fact]
        public void WithoutACursorReturnsTheLatestInTheOrderTheyEntered()
        {
            var archive = new TestArchive();
            archive.Add(M(3, 300));
            var b = archive.Add(L(1, 100));
            var c = archive.Add(M(2, 200));
            var (picked, selection) = archive.Read(null, limit: 2);
            AssertEntries(new[] { b, c }, picked);
            Assert.False(selection.Gap);
        }

        [Fact]
        public void WithoutACursorTheNextStartsAfterTheHighestGivenEvenIfItLeft()
        {
            var archive = new TestArchive();
            archive.Add(M(1, 100));
            archive.AddAndDrop(M(2, 100));
            var next = archive.Read(null).Selection.Next;
            Assert.Equal(2, next.Number);

            var added = archive.Add(M(3, 100));
            var (picked, selection) = archive.Read(next);
            AssertEntries(new[] { added }, picked);
            Assert.False(selection.Gap);
        }

        [Fact]
        public void WithoutACursorOnAnEmptyArchiveReturnsWhatComesNext()
        {
            var archive = new TestArchive();
            var next = archive.Read(null).Selection.Next;
            var added = archive.Add(M(1, 500));
            AssertEntries(new[] { added }, archive.Read(next).Picked);
        }

        // ── Continuing from a cursor ─────────────────────────────────────────

        [Fact]
        public void ReturnsOnlyWhatEnteredAfterTheCursor()
        {
            var archive = new TestArchive();
            archive.Add(L(1, 100));
            var next = archive.Read(null).Selection.Next;
            var b = archive.Add(M(1, 100));
            var c = archive.Add(M(2, 100));
            AssertEntries(new[] { b, c }, archive.Read(next).Picked);
        }

        [Fact]
        public void ReturnsEntriesInTheOrderTheyEnteredWhateverTheirTicksAndNumbers()
        {
            var archive = new TestArchive();
            var next = archive.Read(null).Selection.Next;
            var a = archive.Add(M(11, 300));
            var b = archive.Add(L(10, 100));
            var c = archive.Add(M(10, 200));
            AssertEntries(new[] { a, b, c }, archive.Read(next).Picked);
        }

        [Fact]
        public void ReturnsNothingWhenNothingEnteredAndKeepsTheCursor()
        {
            var archive = new TestArchive();
            archive.Add(L(1, 100));
            var next = archive.Read(null).Selection.Next;
            var (picked, selection) = archive.Read(next);
            Assert.Empty(picked);
            Assert.Equal(next.ToString(), selection.Next.ToString());
        }

        [Fact]
        public void EntriesCutByTheLimitComeOnTheNextRead()
        {
            var archive = new TestArchive();
            var start = archive.Read(null).Selection.Next;
            var added = Enumerable.Range(1, 5).Select(i => archive.Add(M(i, 100))).ToList();

            var first = archive.Read(start, limit: 3);
            AssertEntries(added.Take(3), first.Picked);
            var second = archive.Read(first.Selection.Next, limit: 3);
            AssertEntries(added.Skip(3), second.Picked);
        }

        [Fact]
        public void SaysWhenTheLimitCutTheRead()
        {
            var archive = new TestArchive();
            var start = archive.Read(null).Selection.Next;
            Enumerable.Range(1, 3).Select(i => archive.Add(M(i, 100))).ToList();

            var first = archive.Read(start, limit: 2);
            Assert.True(first.Selection.More);
            var second = archive.Read(first.Selection.Next, limit: 2);
            Assert.False(second.Selection.More);
        }

        [Fact]
        public void AReadThatReturnsExactlyTheLimitSaysNothingMoreFollows()
        {
            var archive = new TestArchive();
            var start = archive.Read(null).Selection.Next;
            archive.Add(M(1, 100));
            archive.Add(M(2, 100));
            Assert.False(archive.Read(start, limit: 2).Selection.More);
        }

        [Fact]
        public void NothingMoreFollowsAReadWithoutACursor()
        {
            // Entries older than the latest are treated as read.
            var archive = new TestArchive();
            Enumerable.Range(1, 3).Select(i => archive.Add(M(i, 100))).ToList();
            Assert.False(archive.Read(null, limit: 1).Selection.More);
        }

        [Fact]
        public void RefusesALimitBelowOne()
            => Assert.Throws<ArgumentOutOfRangeException>(() => new TestArchive().Read(null, limit: 0));

        // ── Entries that left before being read ──────────────────────────────

        [Fact]
        public void NoGapWhenNothingLeft()
        {
            var archive = new TestArchive();
            var next = archive.Read(null).Selection.Next;
            archive.Add(M(1, 100));
            Assert.False(archive.Read(next).Selection.Gap);
        }

        [Fact]
        public void GapWhenAnEntryAfterTheCursorLeft()
        {
            var archive = new TestArchive();
            var next = archive.Read(null).Selection.Next;
            var gone = archive.Add(M(1, 100));
            archive.Add(M(2, 100));
            archive.Remove(gone);
            Assert.True(archive.Read(next).Selection.Gap);
        }

        [Fact]
        public void GapWhenAnEntryWasDroppedAsItWasAdded()
        {
            var archive = new TestArchive();
            var next = archive.Read(null).Selection.Next;
            archive.AddAndDrop(M(1, 100));
            Assert.True(archive.Read(next).Selection.Gap);
        }

        [Fact]
        public void NoGapWhenOnlyEntriesAlreadyReadLeft()
        {
            var archive = new TestArchive();
            var read = archive.Add(M(1, 100));
            var next = archive.Read(null).Selection.Next;
            archive.Remove(read);
            archive.Add(M(2, 100));
            Assert.False(archive.Read(next).Selection.Gap);
        }

        [Fact]
        public void TheGapIsReportedOnceTheCursorPassesIt()
        {
            var archive = new TestArchive();
            var next = archive.Read(null).Selection.Next;
            archive.AddAndDrop(M(1, 100));

            var first = archive.Read(next);
            Assert.True(first.Selection.Gap);
            Assert.False(archive.Read(first.Selection.Next).Selection.Gap);
        }

        [Fact]
        public void TheGapStaysWhileTheLimitStopsTheCursorBeforeIt()
        {
            var archive = new TestArchive();
            var next = archive.Read(null).Selection.Next;
            archive.Add(M(1, 100));
            archive.Add(M(2, 100));
            archive.AddAndDrop(M(3, 100));

            var first = archive.Read(next, limit: 1);
            Assert.True(first.Selection.Gap);
            var second = archive.Read(first.Selection.Next, limit: 1);
            Assert.True(second.Selection.Gap);
            Assert.False(archive.Read(second.Selection.Next).Selection.Gap);
        }

        [Fact]
        public void GapOnEveryReadOnceTheLedgerIsUnreliable()
        {
            var archive = new TestArchive();
            var next = archive.Read(null).Selection.Next;
            archive.Ledger.MarkUnreliable();
            Assert.True(archive.Read(next).Selection.Gap);
        }

        [Fact]
        public void AnEntryThatEnteredUnseenIsReturnedWithAGap()
        {
            // The patches missed it, so they may have missed others that came and went.
            var archive = new TestArchive();
            var next = archive.Read(null).Selection.Next;
            var unseen = new Entry(M(1, 100));
            archive.Present.Add(unseen);

            var (picked, selection) = archive.Read(next);
            AssertEntries(new[] { unseen }, picked);
            Assert.True(selection.Gap);
        }

        [Fact]
        public void NoGapWithoutACursor()
        {
            var archive = new TestArchive();
            archive.AddAndDrop(M(1, 100));
            Assert.False(archive.Read(null).Selection.Gap);
        }

        // ── Loading a save ───────────────────────────────────────────────────

        [Fact]
        public void ACursorFromAnotherLoadStartsOverAndSaysSo()
        {
            var archive = new TestArchive();
            var a = archive.Add(L(1, 100));
            var b = archive.Add(M(1, 200));

            var (picked, selection) = archive.Read(new EventCursor("old", 1), generation: "new");
            Assert.True(selection.Reloaded);
            Assert.False(selection.Gap);
            AssertEntries(new[] { a, b }, picked);
            Assert.Equal("new", selection.Next.Generation);
        }

        [Fact]
        public void ACursorBeyondAnyNumberGivenStartsOverWithAGap()
        {
            var archive = new TestArchive();
            var a = archive.Add(M(1, 100));
            var (picked, selection) = archive.Read(Cursor(99999));
            AssertEntries(new[] { a }, picked);
            Assert.True(selection.Gap);
            Assert.False(selection.Reloaded);
            Assert.Equal(1, selection.Next.Number);
        }

        [Fact]
        public void ACursorAtTheHighestNumberIsIssued()
        {
            var archive = new TestArchive();
            archive.Add(M(1, 100));
            var (picked, selection) = archive.Read(Cursor(1));
            Assert.Empty(picked);
            Assert.False(selection.Gap);
        }

        [Fact]
        public void ACursorFromThisLoadIsNotReloaded()
        {
            var archive = new TestArchive();
            archive.Add(L(1, 100));
            Assert.False(archive.Read(Cursor(0)).Selection.Reloaded);
        }
    }
}
