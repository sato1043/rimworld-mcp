using System;

namespace MCP
{
    /// <summary>
    /// How each kind is written. Kept here so that a new kind fails where it is tested,
    /// rather than in the game code that reports it.
    /// </summary>
    internal static class EventKinds
    {
        /// <summary>The word a response uses for the kind.</summary>
        public static string Word(EventKind kind) => kind switch
        {
            EventKind.Letter  => "letter",
            EventKind.Message => "message",
            _ => throw new ArgumentOutOfRangeException(nameof(kind), kind, null)
        };
    }
}
