using Xunit;

namespace MCP.Tests
{
    /// <summary>
    /// The truth table of <see cref="RequestGuard.RefusalReason"/>. Each case names one
    /// condition, so that removing a condition from the guard fails an identifiable test
    /// rather than shrinking a count.
    /// </summary>
    public class RequestGuardTests
    {
        private const string Host = "127.0.0.1:8080";

        private static bool Allowed(string? origin = null, string? secFetchSite = null,
                                    string? host = Host, string? expectedToken = null,
                                    string? presentedToken = null)
            => Reason(origin, secFetchSite, host, expectedToken, presentedToken) == null;

        private static string? Reason(string? origin = null, string? secFetchSite = null,
                                      string? host = Host, string? expectedToken = null,
                                      string? presentedToken = null)
            => RequestGuard.RefusalReason(origin, secFetchSite, host, expectedToken,
                                          presentedToken);

        // ── The shape a non-browser client produces ──────────────────────────────────

        [Fact]
        public void AllowsARequestWithNoBrowserHeadersAndNoTokenConfigured()
        {
            Assert.True(Allowed());
            Assert.Null(Reason());
        }

        [Theory]
        [InlineData("127.0.0.1:8080")]
        [InlineData("127.0.0.1")]
        [InlineData("localhost:8080")]
        [InlineData("localhost")]
        [InlineData("LOCALHOST:8080")]
        public void AllowsTheLoopbackHostsWithAndWithoutAPort(string host)
            => Assert.True(Allowed(host: host));

        // ── Browser-borne requests ───────────────────────────────────────────────────

        [Fact]
        public void RefusesARequestCarryingAnOriginHeader()
        {
            Assert.False(Allowed(origin: "https://example.test"));
            Assert.Contains("Origin", Reason(origin: "https://example.test"));
        }

        [Fact]
        public void RefusesARequestCarryingASecFetchSiteHeader()
        {
            Assert.False(Allowed(secFetchSite: "cross-site"));
            Assert.Contains("Sec-Fetch-Site", Reason(secFetchSite: "cross-site"));
        }

        [Fact]
        public void RefusesASecFetchSiteOfSameOriginToo()
        {
            // The bridge serves no page of its own, so any Sec-Fetch-* value means a
            // browser is talking to it.
            Assert.False(Allowed(secFetchSite: "same-origin"));
        }

        [Fact]
        public void TreatsAnEmptyOriginAsAbsent()
        {
            // Browsers send the literal "null" for an opaque origin, never an empty
            // value, so an empty string is not a browser signal.
            Assert.True(Allowed(origin: ""));
        }

        [Fact]
        public void RefusesAnOpaqueOrigin()
            => Assert.False(Allowed(origin: "null"));

        // ── DNS rebinding ────────────────────────────────────────────────────────────

        [Theory]
        [InlineData("evil.test")]
        [InlineData("evil.test:8080")]
        // Beginning with a name we answer to is not answering to it.
        [InlineData("127.0.0.1.evil.test")]
        [InlineData("localhost.evil.test")]
        // Nor is ending with one. Without these two, relaxing the comparison from
        // equality to "ends with" passes every other case in this file.
        [InlineData("notlocalhost")]
        [InlineData("evil-127.0.0.1")]
        [InlineData("[::1]:8080")]
        public void RefusesAHostItDoesNotAnswerTo(string host)
        {
            Assert.False(Allowed(host: host));
            Assert.Contains("Host", Reason(host: host));
        }

        [Theory]
        [InlineData(null)]
        [InlineData("")]
        public void RefusesAMissingHost(string? host)
            => Assert.False(Allowed(host: host));

        // ── The optional shared secret ───────────────────────────────────────────────

        [Fact]
        public void AllowsTheMatchingSecretWhenOneIsConfigured()
            => Assert.True(Allowed(expectedToken: "s3cret", presentedToken: "s3cret"));

        [Fact]
        public void RefusesAWrongSecret()
        {
            Assert.False(Allowed(expectedToken: "s3cret", presentedToken: "s3cres"));
            Assert.Contains(RequestGuard.TokenHeader,
                            Reason(expectedToken: "s3cret", presentedToken: "s3cres"));
        }

        [Fact]
        public void RefusesASecretOfTheWrongLength()
            => Assert.False(Allowed(expectedToken: "s3cret", presentedToken: "s3cret "));

        [Fact]
        public void RefusesAnAbsentSecretWhenOneIsConfigured()
            => Assert.False(Allowed(expectedToken: "s3cret", presentedToken: null));

        [Fact]
        public void IgnoresAPresentedSecretWhenNoneIsConfigured()
            => Assert.True(Allowed(expectedToken: null, presentedToken: "anything"));

        [Fact]
        public void TreatsAnEmptyConfiguredSecretAsNotConfigured()
            => Assert.True(Allowed(expectedToken: "", presentedToken: null));

        // ── Order of the checks ──────────────────────────────────────────────────────

        [Fact]
        public void ReportsTheBrowserHeaderBeforeTheHostWhenBothAreWrong()
        {
            // Keeps the refusal reason stable: the first condition that matches is the
            // one reported, so a test asserting on a reason is not order-dependent.
            Assert.Contains("Origin", Reason(origin: "https://example.test",
                                             host: "evil.test"));
        }

        [Fact]
        public void ChecksTheSecretOnlyAfterTheHostIsAccepted()
        {
            // The presented secret is wrong on purpose. With a matching one this case
            // reports the host whichever check runs first, and the test would hold just
            // as well against a guard that had the two the other way round.
            Assert.Contains("Host", Reason(host: "evil.test",
                                           expectedToken: "s3cret",
                                           presentedToken: "wrong"));
        }

        // ── The media type a body has to arrive as ───────────────────────────────────

        [Theory]
        [InlineData("application/json")]
        [InlineData("application/json; charset=utf-8")]
        [InlineData("application/json;charset=UTF-8")]
        [InlineData("APPLICATION/JSON")]
        [InlineData(" application/json ")]
        public void AcceptsJsonWithOrWithoutParameters(string contentType)
            => Assert.True(RequestGuard.IsAcceptedContentType(contentType));

        [Theory]
        [InlineData(null)]
        [InlineData("")]
        [InlineData("text/plain")]
        [InlineData("text/plain;charset=UTF-8")]
        [InlineData("application/x-www-form-urlencoded")]
        [InlineData("multipart/form-data; boundary=----x")]
        public void RefusesTheMediaTypesAFormCanPost(string? contentType)
        {
            // These three, and only these three, are what a form element can send, and
            // sending any of them takes no preflight and so no Origin check to pass.
            Assert.False(RequestGuard.IsAcceptedContentType(contentType));
        }

        [Theory]
        [InlineData("application/jsonx")]
        [InlineData("application/vnd.api+json")]
        [InlineData("text/plain; x=application/json")]
        public void RefusesAMediaTypeThatMerelyContainsTheWord(string contentType)
        {
            // The comparison is on the whole media type, not a substring of the header:
            // "text/plain; x=application/json" is a form post wearing a costume.
            Assert.False(RequestGuard.IsAcceptedContentType(contentType));
        }
    }
}
