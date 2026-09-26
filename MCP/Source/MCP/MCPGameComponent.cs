using System;
using System.Collections.Generic;
using Verse;

namespace MCP
{
    public class MCPGameComponent : GameComponent
    {
        /// <summary>
        /// Failures already written to the log, by path and exception type. A failing read
        /// fails again on every request, so writing each one would bury the log; the first
        /// is enough to carry the stack.
        /// </summary>
        private readonly HashSet<string> _loggedFailures = new HashSet<string>();

        public MCPGameComponent(Game game) { }

        public override void GameComponentUpdate()
        {
            // The request threads record rather than log, because the game's log is
            // not for them to touch. Writing happens here, on the game thread.
            MCPHttpServer.Notices.Flush(message => Log.Warning("[MCP] " + message));

            while (MCPHttpServer.Queue.TryDequeue(out var req))
            {
                try
                {
                    (req.StatusCode, req.Response) = RequestRouter.Handle(req);
                }
                catch (Exception ex)
                {
                    req.StatusCode = 500;
                    req.Response   = $"{{\"error\":{Newtonsoft.Json.JsonConvert.ToString(ex.Message)}}}";
                    // The response carries the message only; the stack is what locates the
                    // fault, so it goes to the log.
                    if (_loggedFailures.Add(req.Path + " " + ex.GetType().FullName))
                        Log.Warning($"[MCP] {req.Method} {req.Path} failed: {ex}");
                }
                finally
                {
                    req.Done.Set();
                }
            }
        }
    }
}
