using System;
using System.Collections.ObjectModel;

namespace MCP
{
    /// <summary>
    /// Decides whether an incoming bridge request may reach the game.
    ///
    /// The bridge listens on loopback with no authentication, so a page the player
    /// happens to have open can otherwise read the colony and issue commands. This type
    /// holds that decision as a pure function over header values: it references nothing
    /// from RimWorld or Unity, so it compiles and runs outside the game and the truth
    /// table can be tested.
    /// </summary>
    internal static class RequestGuard
    {
        /// <summary>
        /// Host names the bridge answers to. Matched by equality, not by pattern, and
        /// held read-only: this is the allow list, and an array would let any later
        /// method in this class add to it without saying so.
        /// </summary>
        private static readonly ReadOnlyCollection<string> AllowedHosts =
            Array.AsReadOnly(new[] { "127.0.0.1", "localhost" });

        /// <summary>Header carrying the shared secret, when one is configured.</summary>
        public const string TokenHeader = "X-MCP-Token";

        /// <summary>Environment variable the shared secret is read from.</summary>
        public const string TokenEnvironmentVariable = "RIMWORLD_MCP_TOKEN";

        /// <summary>Media type a request body has to be sent as.</summary>
        public const string RequiredContentType = "application/json";

        /// <summary>
        /// Why this request is refused, or null when it may proceed. Returning the reason
        /// rather than a flag and an out parameter keeps "there is a reason exactly when
        /// the request is refused" a fact the caller's compiler can check.
        /// </summary>
        /// <param name="origin">Value of the Origin header, or null when absent.</param>
        /// <param name="secFetchSite">Value of the Sec-Fetch-Site header, or null when absent.</param>
        /// <param name="hostHeader">Value of the Host header, with or without a port.</param>
        /// <param name="expectedToken">Configured shared secret; null or empty disables the check.</param>
        /// <param name="presentedToken">Value of the X-MCP-Token header, or null when absent.</param>
        public static string? RefusalReason(string? origin, string? secFetchSite,
                                            string? hostHeader, string? expectedToken,
                                            string? presentedToken)
        {
            // A browser attaches Origin to every cross-origin fetch and to every POST,
            // including form posts and simple requests, and page script cannot remove it.
            if (!string.IsNullOrEmpty(origin))
                return "Origin header present: this bridge does not serve browsers";

            // Sec-Fetch-Site catches what Origin does not: a no-cors GET, such as an
            // image or script tag pointed at the bridge.
            if (!string.IsNullOrEmpty(secFetchSite))
                return "Sec-Fetch-Site header present: this bridge does not serve browsers";

            // A DNS rebinding attack reaches loopback while the browser still believes it
            // is talking to the attacker's name, which is what appears here.
            // In the game this check does not fire today: the listener answers 400 to any
            // Host that differs from its prefix, 127.0.0.1, before this code runs, and that
            // includes localhost. It stays so that widening the prefix does not open the
            // bridge to rebinding without anyone noticing.
            if (!IsAllowedHost(hostHeader))
                return "Unexpected Host header: expected 127.0.0.1 or localhost";

            if (!string.IsNullOrEmpty(expectedToken)
                && !FixedTimeEquals(expectedToken!, presentedToken))
                return "Missing or wrong " + TokenHeader;

            return null;
        }

        /// <summary>
        /// Whether a body sent as this media type may be accepted.
        ///
        /// The checks above refuse a request that says it came from a browser. This one
        /// does not depend on the browser saying so. A form can post three media types
        /// and this is not among them, and asking fetch for it makes the request
        /// non-simple, so the browser sends a preflight first - which arrives with an
        /// Origin header and is refused above. A page is then out of reach of the
        /// commands by construction rather than by a header it might not have sent.
        /// </summary>
        /// <param name="contentType">Value of the Content-Type header, parameters and all.</param>
        public static bool IsAcceptedContentType(string? contentType)
        {
            if (string.IsNullOrEmpty(contentType)) return false;

            // The charset and friends say nothing about the type: application/json and
            // "application/json; charset=utf-8" are the same media type.
            int semicolon = contentType!.IndexOf(';');
            string mediaType = semicolon < 0 ? contentType : contentType.Substring(0, semicolon);

            return string.Equals(mediaType.Trim(), RequiredContentType,
                                 StringComparison.OrdinalIgnoreCase);
        }

        private static bool IsAllowedHost(string? hostHeader)
        {
            if (string.IsNullOrEmpty(hostHeader)) return false;

            // Strip the port. An IPv6 literal would be bracketed and contain colons, but
            // the listener binds 127.0.0.1 only, so such a host is not one we answer to
            // and falling through to the equality check refuses it.
            int colon = hostHeader!.IndexOf(':');
            string name = colon < 0 ? hostHeader : hostHeader.Substring(0, colon);

            foreach (var allowed in AllowedHosts)
            {
                if (string.Equals(name, allowed, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }

        /// <summary>
        /// Compares without returning early on the first differing character, so that
        /// response timing does not reveal how much of the secret was guessed. The length
        /// is not hidden, which is acceptable: it is a configured secret, not a password.
        /// </summary>
        private static bool FixedTimeEquals(string expected, string? presented)
        {
            if (presented == null || expected.Length != presented.Length) return false;

            int difference = 0;
            for (int i = 0; i < expected.Length; i++)
            {
                difference |= expected[i] ^ presented[i];
            }
            return difference == 0;
        }
    }
}
