namespace MCP
{
    /// <summary>
    /// What the ledger needs to know about one archived entry: its kind, the tick the
    /// game places it at, and the game's own number for it.
    /// </summary>
    internal readonly struct EventStamp
    {
        public readonly EventKind Kind;
        public readonly int Id;
        public readonly int Tick;

        public EventStamp(EventKind kind, int id, int tick)
        {
            Kind = kind;
            Id   = id;
            Tick = tick;
        }
    }
}
