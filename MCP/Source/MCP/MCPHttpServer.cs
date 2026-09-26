using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using Verse;

namespace MCP
{
    public static class MCPHttpServer
    {
        private static HttpListener? _listener;
        private static Thread? _thread;

        /// <summary>
        /// Shared secret the bridge expects, or null when the player configured none.
        /// Read once at startup: the game does not see later changes to its environment.
        /// </summary>
        private static string? _expectedToken;

        /// <summary>
        /// What the request threads have to say. They must not write to the game's
        /// log themselves, so they record here and <see cref="MCPGameComponent"/>
        /// writes on the game thread.
        /// </summary>
        internal static readonly NoticeLog Notices = new NoticeLog();

        internal static readonly ConcurrentQueue<PendingRequest> Queue =
            new ConcurrentQueue<PendingRequest>();

        public static void Start(int port = 8080)
        {
            if (_listener != null) return;

            if (!HttpListener.IsSupported)
            {
                Log.Error("[MCP] HttpListener is not supported on this platform.");
                return;
            }

            _expectedToken =
                Environment.GetEnvironmentVariable(RequestGuard.TokenEnvironmentVariable);
            Notices.Clear();

            _listener = new HttpListener();
            _listener.Prefixes.Add($"http://127.0.0.1:{port}/");
            _listener.Start();

            _thread = new Thread(ListenLoop)
            {
                IsBackground = true,
                Name = "MCP_HttpServer"
            };
            _thread.Start();

            Log.Message($"[MCP] HTTP bridge listening on http://127.0.0.1:{port}/");
            Log.Message(string.IsNullOrEmpty(_expectedToken)
                ? "[MCP] No shared secret configured. Set "
                  + $"{RequestGuard.TokenEnvironmentVariable} before launching the game "
                  + "to require one."
                : $"[MCP] Requests must carry the shared secret in {RequestGuard.TokenHeader}.");
        }

        public static void Stop()
        {
            try { _listener?.Stop(); _listener?.Close(); }
            catch { /* shutdown */ }
            _listener = null;
        }

        private static void ListenLoop()
        {
            while (_listener != null && _listener.IsListening)
            {
                HttpListenerContext ctx;
                try { ctx = _listener.GetContext(); }
                catch { break; }
                ThreadPool.QueueUserWorkItem(_ => Serve(ctx));
            }
        }

        /// <summary>
        /// Runs one request on a thread pool worker, and keeps whatever it throws
        /// from leaving the worker.
        ///
        /// This is not a swallowed exception: it is counted and written to the
        /// game's log by <see cref="MCPGameComponent"/>, and the connection is
        /// dropped so the client is not left waiting. It is caught because an
        /// exception that escapes a thread pool work item ends the process, and a
        /// client hanging up part way through a response is enough to raise one.
        /// </summary>
        private static void Serve(HttpListenerContext ctx)
        {
            try
            {
                HandleContext(ctx);
            }
            catch (Exception e)
            {
                Notices.Record("A request failed with " + e.GetType().Name + ".",
                               e.ToString());
                try { ctx.Response.Abort(); }
                catch { /* the client is already gone; nothing further to do */ }
            }
        }

        private static void HandleContext(HttpListenerContext ctx)
        {
            // Decide before reading the body or reaching the game thread: a refused
            // request must cost nothing beyond the response written below.
            // Named rather than positional: all five are string?, so a reordering here
            // would compile, and the guard would go on refusing and allowing requests
            // with the wrong values in hand.
            var refusal = RequestGuard.RefusalReason(
                origin:         ctx.Request.Headers["Origin"],
                secFetchSite:   ctx.Request.Headers["Sec-Fetch-Site"],
                hostHeader:     ctx.Request.UserHostName,   // the Host header, port included
                expectedToken:  _expectedToken,
                presentedToken: ctx.Request.Headers[RequestGuard.TokenHeader]);

            if (refusal != null)
            {
                Notices.Record("Refused a request. " + refusal);
                Respond(ctx, 403, "{\"error\":" + JsonConvert.ToString(refusal) + "}");
                return;
            }

            // Every command the bridge has is a POST, so this covers all of them. The
            // method is compared exactly, as RequestRouter compares it: a method in any
            // other casing is not POST and gets a 405 there without touching a command.
            if (ctx.Request.HttpMethod == "POST"
                && !RequestGuard.IsAcceptedContentType(ctx.Request.ContentType))
            {
                var wanted = "Send the body as " + RequestGuard.RequiredContentType;
                Notices.Record("Refused a POST sent as some other media type.");
                Respond(ctx, 415, "{\"error\":" + JsonConvert.ToString(wanted) + "}");
                return;
            }

            string body = "";
            if (ctx.Request.HasEntityBody)
            {
                using var reader = new StreamReader(ctx.Request.InputStream, Encoding.UTF8);
                body = reader.ReadToEnd();
            }

            // Named rather than positional: all four are strings, so a reordering here
            // would still compile.
            var pending = new PendingRequest(
                method:      ctx.Request.HttpMethod,
                path:        ctx.Request.Url.AbsolutePath,
                queryString: ctx.Request.Url.Query,
                body:        body);

            Queue.Enqueue(pending);

            if (!pending.Done.Wait(TimeSpan.FromSeconds(15)))
            {
                pending.StatusCode = 503;
                pending.Response   = "{\"error\":\"Game thread timeout\"}";
            }

            Respond(ctx, pending.StatusCode, pending.Response ?? "{}");
        }

        /// <summary>
        /// Writes the whole response. No Access-Control-Allow-Origin header is sent:
        /// the bridge answers local tools, and granting every origin read access was
        /// what let a page in the player's browser read the response it provoked.
        /// </summary>
        private static void Respond(HttpListenerContext ctx, int status, string json)
        {
            var resp = ctx.Response;
            resp.StatusCode  = status;
            resp.ContentType = "application/json; charset=utf-8";
            var bytes = Encoding.UTF8.GetBytes(json);
            resp.ContentLength64 = bytes.Length;
            resp.OutputStream.Write(bytes, 0, bytes.Length);
            resp.OutputStream.Close();
        }
    }
}
