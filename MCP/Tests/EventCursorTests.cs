using System;
using MCP;
using Xunit;

namespace MCP.Tests
{
    /// <summary>
    /// What <see cref="EventCursor"/> promises: its text comes back as the same cursor,
    /// passes through a URL unchanged, and nothing else reads as a cursor.
    /// </summary>
    public class EventCursorTests
    {
        [Fact]
        public void TheCursorSurvivesTheRoundTrip()
        {
            var cursor = new EventCursor("a1b2", 123456);
            Assert.Equal("a1b2.123456", cursor.ToString());
            Assert.True(EventCursor.TryParse(cursor.ToString(), out var parsed));
            Assert.Equal("a1b2", parsed!.Generation);
            Assert.Equal(123456, parsed.Number);
        }

        [Fact]
        public void TheCursorPassesThroughAUrlUnchanged()
        {
            var text = new EventCursor("a1", 7).ToString();
            Assert.Equal(Uri.EscapeDataString(text), text);
        }

        [Fact]
        public void RefusesANegativeNumber()
            => Assert.Throws<ArgumentOutOfRangeException>(() => new EventCursor("a1", -1));

        [Theory]
        [InlineData("")]
        [InlineData("a1")]
        [InlineData("a1.")]
        [InlineData("a1.-1")]
        [InlineData("a1.+1")]
        [InlineData("a1.x")]
        [InlineData("a1.1.2")]
        [InlineData("A1.1")]
        [InlineData("a-1.1")]
        [InlineData(".1")]
        [InlineData("a1.99999999999999999999")]
        [InlineData("a1. 1")]
        public void RefusesTextThatIsNotACursor(string text)
            => Assert.False(EventCursor.TryParse(text, out _));

        [Fact]
        public void RefusesNull()
            => Assert.False(EventCursor.TryParse(null, out _));
    }
}
