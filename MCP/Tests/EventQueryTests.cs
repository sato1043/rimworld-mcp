using MCP;
using Xunit;

namespace MCP.Tests
{
    /// <summary>
    /// What <see cref="EventQuery"/> promises: since and limit are read, decoded as a URL
    /// query is, and anything it cannot honour is refused rather than guessed at.
    /// </summary>
    public class EventQueryTests
    {
        [Theory]
        [InlineData(null)]
        [InlineData("")]
        [InlineData("?")]
        public void AnEmptyQueryReadsTheLatestAtTheDefaultLimit(string? query)
        {
            Assert.True(EventQuery.TryRead(query, out var since, out var limit, out _));
            Assert.Null(since);
            Assert.Equal(EventSelector.DefaultLimit, limit);
        }

        [Fact]
        public void ReadsTheCursorAndTheLimit()
        {
            Assert.True(EventQuery.TryRead("?since=a1.7&limit=5&other=x", out var since, out var limit, out _));
            Assert.Equal("a1.7", since!.ToString());
            Assert.Equal(5, limit);
        }

        [Fact]
        public void ReadsACursorWhoseUnreservedCharactersWereEncoded()
        {
            // A client may percent-encode any character, unreserved ones included.
            Assert.True(EventQuery.TryRead("since=a1%2E7", out var since, out _, out _));
            Assert.Equal("a1.7", since!.ToString());
        }

        [Theory]
        [InlineData("1", 1)]
        [InlineData("200", 200)]
        public void AcceptsTheLimitAtItsBounds(string text, int expected)
        {
            Assert.True(EventQuery.TryRead("limit=" + text, out _, out var limit, out _));
            Assert.Equal(expected, limit);
        }

        /// <summary>Each query with the reason it must be refused for, so one refusal cannot stand in for another.</summary>
        public static readonly TheoryData<string, string> Refused = new TheoryData<string, string>
        {
            { "limit=0", EventQuery.LimitOutOfRange },
            { "limit=201", EventQuery.LimitOutOfRange },
            { "limit=-1", EventQuery.LimitOutOfRange },
            { "limit=x", EventQuery.LimitOutOfRange },
            { "limit=", EventQuery.LimitOutOfRange },
            { "limit=2147483648", EventQuery.LimitOutOfRange },
            { "limit=%201", EventQuery.LimitOutOfRange },
            { "limit=+1", EventQuery.LimitOutOfRange },
            { "limit=%EF%BC%91", EventQuery.LimitOutOfRange },
            { "since=nope", EventQuery.NotACursor },
            { "since=", EventQuery.NotACursor },
            { "since", EventQuery.NotACursor },
            { "since=a1.99999999999999999999", EventQuery.NotACursor },
            { "since=a1.%207", EventQuery.NotACursor },
            { "since=%zz", EventQuery.NotACursor },
            { "since=a1.7%26limit%3D5", EventQuery.NotACursor },
            { "since=a1.7&since=a1.8", EventQuery.SinceTwice },
            { "since=a1.7&%73ince=a1.8", EventQuery.SinceTwice },
            { "limit=1&limit=2", EventQuery.LimitTwice },
        };

        [Theory]
        [MemberData(nameof(Refused))]
        public void RefusesAQueryItCannotHonourAndSaysWhy(string query, string reason)
        {
            Assert.False(EventQuery.TryRead(query, out _, out _, out var refusal));
            Assert.Equal(reason, refusal);
        }

        [Fact]
        public void TheRefusalOfACursorSaysHowToStartOver()
        {
            Assert.False(EventQuery.TryRead("since=nope", out _, out _, out var refusal));
            Assert.Contains("leave since out", refusal);
        }
    }
}
