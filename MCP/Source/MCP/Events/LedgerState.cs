namespace MCP
{
    /// <summary>What a read needs from the ledger, fixed at one moment.</summary>
    internal readonly struct LedgerState
    {
        /// <summary>The highest number given so far; 0 before the first.</summary>
        public readonly long HighestNumber;

        /// <summary>The highest number among entries that left; 0 when none has.</summary>
        public readonly long HighestDropped;

        /// <summary>Whether what left can be vouched for.</summary>
        public readonly bool Reliable;

        public LedgerState(long highestNumber, long highestDropped, bool reliable)
        {
            HighestNumber  = highestNumber;
            HighestDropped = highestDropped;
            Reliable       = reliable;
        }
    }
}
