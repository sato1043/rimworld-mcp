using System;
using System.Globalization;

namespace MCP
{
    /// <summary>Reads the query string of an events request.</summary>
    internal static class EventQuery
    {
        public const string SinceTwice = "since given more than once";
        public const string LimitTwice = "limit given more than once";
        public const string NotACursor = "since is not a cursor returned by this endpoint; leave since out to read the latest";
        public static readonly string LimitOutOfRange = $"limit must be a whole number from 1 to {EventSelector.MaxLimit}";

        /// <summary>
        /// Reads since and limit, or says why the query is refused. Parameters other
        /// than those two are ignored. Either one given twice, or given without a value,
        /// is refused: reading it as absent would restart a reader whose cursor went
        /// missing without telling it, and picking one of two would hide the caller's
        /// mistake.
        /// </summary>
        /// <param name="query">The raw query string, with or without its leading '?'.</param>
        /// <param name="refusal">Why the query is refused, when this returns false.</param>
        public static bool TryRead(string? query, out EventCursor? since, out int limit, out string? refusal)
        {
            since = null;
            limit = EventSelector.DefaultLimit;
            refusal = null;
            string? sinceText = null, limitText = null;

            foreach (var pair in (query ?? "").TrimStart('?').Split('&'))
            {
                if (pair.Length == 0) continue;
                var eq = pair.IndexOf('=');
                var name  = Uri.UnescapeDataString(eq < 0 ? pair : pair.Substring(0, eq));
                var value = Uri.UnescapeDataString(eq < 0 ? "" : pair.Substring(eq + 1));
                switch (name)
                {
                    case "since":
                        if (sinceText != null) { refusal = SinceTwice; return false; }
                        sinceText = value;
                        break;
                    case "limit":
                        if (limitText != null) { refusal = LimitTwice; return false; }
                        limitText = value;
                        break;
                }
            }

            if (sinceText != null && !EventCursor.TryParse(sinceText, out since))
            {
                refusal = NotACursor;
                return false;
            }

            if (limitText != null
                && (!int.TryParse(limitText, NumberStyles.None, CultureInfo.InvariantCulture, out limit)
                    || limit < 1 || limit > EventSelector.MaxLimit))
            {
                refusal = LimitOutOfRange;
                return false;
            }

            return true;
        }
    }
}
