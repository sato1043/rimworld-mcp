using System;
using System.Globalization;
using System.Linq;

namespace MCP
{
    /// <summary>
    /// Where a reader left off: the load it read from, and the ledger number it read
    /// up to. Handed to the caller as an opaque string and given back on the next read.
    /// The generation matters because each load numbers its entries afresh.
    /// </summary>
    internal sealed class EventCursor
    {
        private const char Separator = '.';

        public string Generation { get; }
        public long Number { get; }

        public EventCursor(string generation, long number)
        {
            if (!IsGeneration(generation)) throw new ArgumentException("Generation must be lower-case letters and digits", nameof(generation));
            if (number < 0) throw new ArgumentOutOfRangeException(nameof(number));
            Generation = generation;
            Number     = number;
        }

        /// <summary>Letters, digits and one '.', so it passes through a URL unchanged.</summary>
        public override string ToString() =>
            Generation + Separator + Number.ToString(CultureInfo.InvariantCulture);

        /// <summary>Reads a cursor written by <see cref="ToString"/>; false for anything else.</summary>
        public static bool TryParse(string? text, out EventCursor? cursor)
        {
            cursor = null;
            if (text == null) return false;

            var parts = text.Split(Separator);
            if (parts.Length != 2 || !IsGeneration(parts[0])) return false;
            if (!long.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out var number)) return false;

            cursor = new EventCursor(parts[0], number);
            return true;
        }

        private static bool IsGeneration(string? text) =>
            !string.IsNullOrEmpty(text) && text!.All(c => (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'));
    }
}
