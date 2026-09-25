using System;
using Verse;

namespace MCP
{
    public class MCPGameComponent : GameComponent
    {
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
                }
                finally
                {
                    req.Done.Set();
                }
            }
        }
    }
}
