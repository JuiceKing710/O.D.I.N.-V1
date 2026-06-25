import React, { useEffect, useRef, useState } from "react";
import { fetchResearchRun, runResearchAgent } from "../ipc/apiClient.js";
import { useAgentStore } from "../state/agentStore.js";
import { useAppState } from "../state/appContext.jsx";

const STATUS_GLYPH = { running: "◌", done: "✓", error: "✕" };
const POLL_INTERVAL_MS = 1500;

export function AgentsView() {
  const [goal, setGoal] = useState("");
  const [error, setError] = useState("");
  const run = useAgentStore((state) => state.run);
  const startRun = useAgentStore((state) => state.startRun);
  const applyRunSnapshot = useAgentStore((state) => state.applyRunSnapshot);
  const { currentUser } = useAppState();
  const busy = run.status === "starting" || run.status === "running";
  const pollRef = useRef(null);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  // Stop polling if the panel unmounts mid-run.
  useEffect(() => stopPolling, []);

  async function launch(event) {
    event.preventDefault();
    const trimmed = goal.trim();
    if (!trimmed || busy) {
      return;
    }
    setError("");
    stopPolling();
    startRun(trimmed);
    let snapshot;
    try {
      // Returns immediately with the run id; the run continues in the background.
      snapshot = await runResearchAgent({ goal: trimmed, username: currentUser.username });
    } catch (requestError) {
      setError(requestError.message);
      return;
    }
    applyRunSnapshot(snapshot);
    // Poll for the final report (WS agent.* events also update the store live).
    const runId = snapshot.run_id;
    pollRef.current = setInterval(async () => {
      try {
        const status = await fetchResearchRun(runId);
        applyRunSnapshot(status);
        if (status.status === "complete" || status.status === "error") {
          stopPolling();
        }
      } catch {
        // Transient poll failure; keep trying — live events still flow.
      }
    }, POLL_INTERVAL_MS);
  }

  return (
    <section className="panel agents-panel" aria-label="Autonomous agents">
      <header className="agents-header">
        <h1>Deep Research</h1>
        <p>
          An autonomous agent that plans queries, searches the web, reads sources, and writes a
          cited report — running unattended in a pre-approved network scope.
        </p>
      </header>

      <form className="agents-composer" onSubmit={launch}>
        <label htmlFor="agent-goal">Research goal</label>
        <textarea
          id="agent-goal"
          rows={2}
          value={goal}
          placeholder="e.g. What is PewDiePie's Odysseus and how does it compare to local AI assistants?"
          onChange={(event) => setGoal(event.target.value)}
          disabled={busy}
        />
        <button type="submit" disabled={busy || !goal.trim()}>
          {busy ? "Researching…" : "Run research"}
        </button>
      </form>

      {error && <p className="error provider-notice">{error}</p>}

      {run.status !== "idle" && (
        <div className="agent-run" aria-live="polite">
          <p className="agent-goal-label">
            <strong>Goal:</strong> {run.goal}
          </p>

          {run.queries.length > 0 && (
            <div className="agent-plan">
              <h2>Plan</h2>
              <ol>
                {run.queries.map((query, index) => (
                  <li key={`${query}-${index}`}>{query}</li>
                ))}
              </ol>
            </div>
          )}

          {run.steps.length > 0 && (
            <ul className="agent-steps">
              {run.steps.map((step, index) => (
                <li key={`${step.label}-${index}`} className={`agent-step ${step.status}`}>
                  <span className="agent-step-glyph" aria-hidden="true">
                    {STATUS_GLYPH[step.status] || "•"}
                  </span>
                  <span>{step.label}</span>
                  {step.detail && <small>{step.detail}</small>}
                </li>
              ))}
            </ul>
          )}

          {run.status === "error" && <p className="error provider-notice">{run.error}</p>}

          {run.report && (
            <article className="agent-report">
              <h2>Report</h2>
              <p>{run.report}</p>
              {run.sources.length > 0 && (
                <div className="agent-sources">
                  <h3>Sources</h3>
                  <ol>
                    {run.sources.map((source, index) => (
                      <li key={`${source.url}-${index}`}>
                        <a href={source.url} target="_blank" rel="noreferrer noopener">
                          {source.title || source.url}
                        </a>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </article>
          )}
        </div>
      )}
    </section>
  );
}
