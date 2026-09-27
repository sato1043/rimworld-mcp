using System;
using System.Collections.Generic;
using RimWorld;
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

        private const int GenerationLength = 8;

        /// <summary>
        /// Identifies the archive's current numbering. Made afresh in the same place the
        /// ledger numbers the archive afresh, so an event cursor carrying a different value
        /// came from an earlier numbering, whatever the game does between loads.
        /// </summary>
        public string Generation { get; private set; } = NewGeneration();

        /// <summary>
        /// Whether loading has finished and the archive has been numbered afresh. Before
        /// then, the entries loaded from the save are not numbered yet.
        /// </summary>
        public bool LoadFinished { get; private set; }

        /// <summary>
        /// The order entries entered the archive during this load. Fed by the patches on
        /// Archive.Add and Archive.Remove, and numbered afresh with each load along with
        /// <see cref="Generation"/>.
        /// </summary>
        internal ArchiveLedger<IArchivable> ArchiveLedger { get; } =
            new ArchiveLedger<IArchivable>(ArchiveEvents.StampOf);

        public MCPGameComponent(Game game) { }

        public override void FinalizeInit()
        {
            // Nobody has read yet. Numbering afresh puts the entries loaded from the save,
            // which never pass through Archive.Add, ahead of any the game added while
            // loading, and marks the ledger unreliable if the patches are not in place.
            Generation = NewGeneration();
            ArchiveEvents.Follow("numbering the archive after loading", 0, static (ledger, _) =>
            {
                ledger.Restart(Find.Archive.ArchivablesListForReading);
                // MCPMod has logged why the patches are missing.
                if (!ArchivePatchState.Applied) ledger.MarkUnreliable();
            });
            LoadFinished = true;
        }

        private static string NewGeneration() => Guid.NewGuid().ToString("N").Substring(0, GenerationLength);

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
