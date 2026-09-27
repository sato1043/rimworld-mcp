using System.Collections.Generic;

namespace MCP
{
    /// <summary>The outcome of one read.</summary>
    internal sealed class EventSelection
    {
        /// <summary>Positions in the list given to the selector, in the order entries entered.</summary>
        public IReadOnlyList<int> Indices { get; }
        public EventCursor Next { get; }

        /// <summary>
        /// Entries after the cursor left the archive before being read, or the ledger
        /// cannot vouch that none did. The next cursor moves past them once everything
        /// after them has been returned.
        /// </summary>
        public bool Gap { get; }

        /// <summary>The cursor came from another load, so the read started over.</summary>
        public bool Reloaded { get; }

        /// <summary>
        /// The limit cut the read: more entries follow, and reading again from
        /// <see cref="Next"/> returns them.
        /// </summary>
        public bool More { get; }

        public EventSelection(IReadOnlyList<int> indices, EventCursor next, bool gap, bool reloaded, bool more)
        {
            Indices  = indices;
            Next     = next;
            Gap      = gap;
            Reloaded = reloaded;
            More     = more;
        }
    }
}
