using System;
using System.Linq;
using MCP;
using Xunit;

namespace MCP.Tests
{
    /// <summary>What <see cref="EventKinds"/> promises: each kind is written its own way.</summary>
    public class EventKindsTests
    {
        [Fact]
        public void EveryKindHasItsOwnWord()
        {
            var kinds = Enum.GetValues(typeof(EventKind)).Cast<EventKind>().ToList();
            Assert.Equal(kinds.Count, kinds.Select(EventKinds.Word).Distinct().Count());
        }
    }
}
