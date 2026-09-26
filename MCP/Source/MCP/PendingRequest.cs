using System.Threading;

namespace MCP
{
    internal class PendingRequest
    {
        public readonly string Method;
        public readonly string Path;
        public readonly string QueryString;
        public readonly string Body;
        public string? Response;
        public int StatusCode = 200;
        public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);

        public PendingRequest(string method, string path, string queryString, string body)
        {
            Method      = method;
            Path        = path;
            QueryString = queryString;
            Body        = body;
        }
    }
}
