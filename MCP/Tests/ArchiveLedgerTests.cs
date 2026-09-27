using System.Linq;
using MCP;
using Xunit;
using static MCP.Tests.TestArchive;

namespace MCP.Tests
{
    /// <summary>
    /// What <see cref="ArchiveLedger{T}"/> promises: each entry is numbered in the order
    /// it entered the archive, told apart by reference, and the highest number that left
    /// is remembered, including an entry dropped as it was added.
    /// </summary>
    public class ArchiveLedgerTests
    {
        // ── Numbering ────────────────────────────────────────────────────────

        [Fact]
        public void NumbersMessagesInTheOrderTheyAreSentNotTheirOwnNumbers()
        {
            // Message 11 was made after message 10 but sent first.
            var archive = new TestArchive();
            var later = archive.Add(M(11, 100));
            var earlier = archive.Add(M(10, 100));
            Assert.True(archive.Number(later) < archive.Number(earlier));
        }

        [Fact]
        public void NumbersADelayedLetterWhenItArrives()
        {
            var archive = new TestArchive();
            var arrivedFirst = archive.Add(L(11, 200));
            var delayed = archive.Add(L(10, 200));
            Assert.True(archive.Number(arrivedFirst) < archive.Number(delayed));
        }

        [Fact]
        public void AnEntryWhoseAddDidNotCompleteIsReturnedWhenItArrives()
        {
            // Numbered by the patch, but Add did not take it; a reader read meanwhile.
            var archive = new TestArchive();
            var entry = new Entry(M(1, 100));
            archive.Ledger.Entering(entry);
            archive.Add(M(2, 100));
            var next = archive.Read(null).Selection.Next;

            archive.Ledger.Entering(entry);
            archive.Present.Add(entry);
            AssertEntries(new[] { entry }, archive.Read(next).Picked);
        }

        [Fact]
        public void ACancelledAddIsNeitherReturnedNorCountedAsAGap()
        {
            var archive = new TestArchive();
            archive.Add(M(1, 100));
            var next = archive.Read(null).Selection.Next;

            archive.AddCancelled(M(2, 100));
            var later = archive.Add(M(3, 100));
            var (picked, selection) = archive.Read(next);
            AssertEntries(new[] { later }, picked);
            Assert.False(selection.Gap);
            Assert.True(archive.Ledger.Reliable);
        }

        [Fact]
        public void ACancelledEntryThatArrivesLaterTakesANewNumber()
        {
            var archive = new TestArchive();
            var entry = archive.AddCancelled(M(1, 100));
            Assert.False(archive.Ledger.TryGetNumber(entry, out _));

            archive.Ledger.Entering(entry);
            archive.Present.Add(entry);
            Assert.Equal(2, archive.Number(entry));
        }

        [Fact]
        public void WithdrawingAnEntryDroppedAsItWasAddedKeepsTheDrop()
        {
            var archive = new TestArchive();
            archive.Add(M(1, 100));
            var next = archive.Read(null).Selection.Next;

            var dropped = new Entry(M(2, 100));
            var number = archive.Ledger.Entering(dropped);
            archive.Ledger.Removed(dropped);
            archive.Ledger.Withdraw(dropped, number);
            Assert.True(archive.Read(next).Selection.Gap);
        }

        [Fact]
        public void WithdrawLeavesANumberItDidNotGive()
        {
            var archive = new TestArchive();
            var entry = archive.Add(M(1, 100));

            // Announced again while it already has a number: that call gave none.
            archive.Ledger.Withdraw(entry, archive.Ledger.Entering(entry));
            Assert.Equal(1, archive.Number(entry));

            // Nor can a number given to another entry take it away.
            var other = archive.Add(M(2, 100));
            archive.Ledger.Withdraw(entry, archive.Number(other));
            Assert.Equal(1, archive.Number(entry));
        }

        [Fact]
        public void AnEntryReportedTwiceKeepsItsNumber()
        {
            var archive = new TestArchive();
            var entry = archive.Add(M(1, 100));
            archive.Ledger.Entering(entry);
            Assert.Equal(1, archive.Number(entry));
            Assert.Equal(1, archive.Ledger.HighestNumber);
        }

        [Fact]
        public void TellsEntriesApartByReference()
        {
            var archive = new TestArchive();
            var one = archive.Add(M(1, 100));
            var two = archive.Add(M(2, 100));
            Assert.NotEqual(archive.Number(one), archive.Number(two));
        }

        [Fact]
        public void LeavesOutKindsNotReported()
        {
            var archive = new TestArchive();
            var other = archive.Add(null);
            archive.Remove(other);
            archive.Ledger.Reconcile(new[] { new Entry(null) });
            Assert.False(archive.Ledger.TryGetNumber(other, out _));
            Assert.Equal(0, archive.Ledger.HighestNumber);
            Assert.Equal(0, archive.Ledger.HighestDropped);
        }

        [Fact]
        public void ReadReturnsEachEntryWithItsOwnStampAmongKindsNotReported()
        {
            var archive = new TestArchive();
            var others = new[] { new Entry(null), new Entry(null), new Entry(null) };
            var a = archive.Add(M(1, 100));
            var b = archive.Add(L(2, 100));
            var listed = new[] { others[0], b, others[1], a, others[2] };
            var (events, selection) = archive.Ledger.Read(listed, null, 30, Gen);
            AssertEntries(new[] { a, b }, events.Select(e => e.Entry));
            Assert.Equal(new[] { M(1, 100), L(2, 100) }, events.Select(e => e.Stamp));
            Assert.False(selection.Gap);
        }

        [Fact]
        public void NumbersUnreportedEntriesByTickThenKindThenNumber()
        {
            var ledger = new ArchiveLedger<Entry>(e => e.Stamp);
            var m2 = new Entry(M(2, 100));
            var l9 = new Entry(L(9, 100));
            var m1 = new Entry(M(1, 100));
            var early = new Entry(M(7, 50));
            ledger.Restart(new[] { m2, l9, m1, early });
            var order = new[] { early, l9, m1, m2 }.Select(e => { ledger.TryGetNumber(e, out var n); return n; });
            Assert.Equal(new long[] { 1, 2, 3, 4 }, order);
        }

        [Fact]
        public void ReconcileLeavesNumberedEntriesAlone()
        {
            var archive = new TestArchive();
            var added = archive.Add(M(5, 100));
            var loaded = new Entry(M(1, 50));
            archive.Ledger.Reconcile(new[] { added, loaded });
            Assert.Equal(1, archive.Number(added));
            Assert.True(archive.Ledger.TryGetNumber(loaded, out var number));
            Assert.Equal(2, number);
        }

        [Fact]
        public void ReconcileCountsAnEntryThatLeftUnreportedAsDropped()
        {
            var archive = new TestArchive();
            var gone = archive.Add(M(1, 100));
            var kept = archive.Add(M(2, 100));
            archive.Ledger.Reconcile(new[] { kept });
            Assert.Equal(1, archive.Ledger.HighestDropped);
            Assert.False(archive.Ledger.TryGetNumber(gone, out _));
        }

        [Fact]
        public void RestartPutsLoadedEntriesAheadOfOnesAddedWhileLoading()
        {
            var archive = new TestArchive();
            var addedWhileLoading = archive.Add(M(9, 500));
            archive.AddAndDrop(M(8, 500));
            var loaded = new Entry(L(1, 100));

            archive.Ledger.Restart(new[] { loaded, addedWhileLoading });
            Assert.True(archive.Ledger.TryGetNumber(loaded, out var first));
            Assert.Equal(1, first);
            Assert.Equal(2, archive.Number(addedWhileLoading));
            Assert.Equal(0, archive.Ledger.HighestDropped);
            Assert.Equal(2, archive.Ledger.HighestNumber);
        }

        [Fact]
        public void RestartForgetsFailuresWhileLoading()
        {
            var archive = new TestArchive();
            archive.Ledger.MarkUnreliable();
            archive.Ledger.Restart(archive.Present);
            Assert.True(archive.Ledger.Reliable);
        }

        // ── Recording what left ──────────────────────────────────────────────

        [Fact]
        public void RemembersTheHighestNumberThatLeft()
        {
            var archive = new TestArchive();
            var a = archive.Add(M(1, 100));
            var b = archive.Add(M(2, 100));
            archive.Remove(b);
            archive.Remove(a);
            Assert.Equal(2, archive.Ledger.HighestDropped);
        }

        [Fact]
        public void AnEntryDroppedAsItIsAddedIsRecorded()
        {
            var archive = new TestArchive();
            var dropped = archive.AddAndDrop(M(1, 100));
            Assert.Equal(1, archive.Ledger.HighestDropped);
            Assert.False(archive.Ledger.TryGetNumber(dropped, out _));
        }

        [Fact]
        public void AnEntryThatLeavesUnnumberedIsPlacedAfterEverything()
        {
            var archive = new TestArchive();
            archive.Add(M(1, 100));
            archive.Ledger.Removed(new Entry(M(9, 100)));
            Assert.Equal(2, archive.Ledger.HighestDropped);
            Assert.Equal(2, archive.Ledger.HighestNumber);
        }

        [Fact]
        public void TheLedgerIsReliableUntilMarkedOtherwise()
        {
            var archive = new TestArchive();
            Assert.True(archive.Ledger.Reliable);
            archive.Ledger.MarkUnreliable();
            Assert.False(archive.Ledger.Reliable);
        }

        // ── Calls that did not arrive ────────────────────────────────────────

        [Fact]
        public void ReconcilingWhatWasReportedKeepsVouching()
        {
            var archive = new TestArchive();
            var kept = archive.Add(M(1, 100));
            archive.AddAndDrop(M(2, 100));
            archive.Ledger.Reconcile(new[] { kept });
            Assert.True(archive.Ledger.Reliable);
        }

        [Fact]
        public void ReconcilingAnEntryThatEnteredUnseenStopsVouching()
        {
            // Another entry could have entered and left unseen in the same way.
            var archive = new TestArchive();
            var kept = archive.Add(M(1, 100));
            archive.Ledger.Reconcile(new[] { kept, new Entry(M(2, 100)) });
            Assert.False(archive.Ledger.Reliable);
        }

        [Fact]
        public void ReconcilingAnEntryThatLeftUnseenStopsVouching()
        {
            var archive = new TestArchive();
            archive.Add(M(1, 100));
            archive.Ledger.Reconcile(new Entry[0]);
            Assert.False(archive.Ledger.Reliable);
        }

        [Fact]
        public void AnEntryThatLeavesUnnumberedStopsVouching()
        {
            var archive = new TestArchive();
            archive.Ledger.Removed(new Entry(M(1, 100)));
            Assert.False(archive.Ledger.Reliable);
        }

        [Fact]
        public void AnEntryOfAnotherKindLeavingUnnumberedKeepsVouching()
        {
            var archive = new TestArchive();
            archive.Ledger.Removed(new Entry(null));
            archive.Ledger.Reconcile(new[] { new Entry(null) });
            Assert.True(archive.Ledger.Reliable);
        }

        [Fact]
        public void RestartNumbersWhatWasLoadedAndStillVouches()
        {
            // Entries loaded from a save never pass through Add.
            var archive = new TestArchive();
            var loaded = new Entry(L(1, 100));
            archive.Ledger.Restart(new[] { loaded });
            Assert.True(archive.Ledger.TryGetNumber(loaded, out _));
            Assert.True(archive.Ledger.Reliable);
        }
    }
}
