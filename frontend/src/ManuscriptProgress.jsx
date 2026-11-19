import { useEffect, useState } from "react";
import { API_URL } from "./api";
import "./ManuscriptProgress.css";

const stateLabels = {
  completed: "Completed",
  current: "Current",
  pending: "Upcoming",
  unknown: "Status unavailable",
};

// Descriptions explain the workflow only; they do not assert a manuscript event.
const stageDescriptions = {
  Submission: "This stage covers manuscript preparation and submission.",
  "Initial Screening": "This stage covers the editorial team's initial assessment.",
  "Initial Editing": "This stage covers initial editing and associated approvals.",
  "Peer Review": "This stage covers reviewer assignments and evaluations.",
  "EIC Decision": "This stage covers the editor-in-chief's editorial decision.",
  "Author Agreement": "This stage covers review of the applicable author agreement.",
  "Final Editing": "This stage covers final editing and its review.",
  Formatting: "This stage covers formatting and review of the manuscript.",
  Publication: "This stage represents publication of an accepted manuscript in the local prototype.",
};

function ManuscriptProgress({ manuscriptId, token, revision = 0, suspendRefreshRef, onStageChange, onProgressChange, showTitle = true, showNextAction = true, showRound = true }) {
  const [result, setResult] = useState({ loading: true });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const onFocus = () => {
      if (!suspendRefreshRef?.current && document.visibilityState === "visible") setAttempt(value => value + 1);
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [suspendRefreshRef]);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setResult(previous => previous.token === token && previous.data?.manuscript_id === manuscriptId
        ? { ...previous, loading: false, refreshing: true, refreshError: false }
        : { loading: true });
      try {
        const response = await fetch(`${API_URL}/manuscripts/${manuscriptId}/progress`, {
          headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
        });
        if (!response.ok) throw new Error("Unable to load manuscript progress.");
        const data = await response.json();
        if (!data || data.manuscript_id !== manuscriptId) throw new Error("Invalid manuscript response.");
        if (!controller.signal.aborted) setResult({ data, token });
      } catch {
        if (!controller.signal.aborted) setResult(previous => previous.token === token && previous.data?.manuscript_id === manuscriptId
          ? { data: previous.data, token, refreshError: true }
          : { error: true });
      }
    }
    load();
    return () => controller.abort();
  }, [manuscriptId, token, attempt, revision]);

  const data = result.token === token && result.data?.manuscript_id === manuscriptId ? result.data : null;
  const stage = typeof data?.current_stage === "string" && data.current_stage.trim() ? data.current_stage : null;
  useEffect(() => { onStageChange?.(stage); }, [stage, manuscriptId, onStageChange]);
  useEffect(() => {
    if (onProgressChange) onProgressChange(data && !result.refreshError && !result.refreshing ? data : null);
  }, [data, result.refreshError, result.refreshing, onProgressChange]);
  const action = typeof data?.next_action === "string" && data.next_action.trim() ? data.next_action : "Unavailable";
  const round = Number.isInteger(data?.review_round) && data.review_round > 0 ? data.review_round : "Unavailable";
  const stages = Array.isArray(data?.stages) ? data.stages : [];

  return (
    <section className="manuscript-progress" aria-label={`Manuscript ${manuscriptId} progress`}>
      <div className="progress-header"><h4>Manuscript Progress</h4></div>
      {result.loading || (!data && !result.error) ? <p role="status">Loading progress...</p> : result.error ? (
        <p role="alert">Unable to load manuscript progress. Return to this view to try again.</p>
      ) : <>
        {result.refreshError && <p role="alert">Progress could not be updated; showing the last available information.</p>}
        <div className="progress-summary">
          <div className="progress-summary-top">
            {showTitle && <p className="progress-title">{typeof data.title === "string" && data.title.trim() ? data.title : "Manuscript"} (#{manuscriptId})</p>}
            {showRound && <span className="progress-round">Review round: {round}</span>}
          </div>
          {showNextAction && <p className="progress-next"><strong>Next action:</strong> {action}</p>}
        </div>
        {stages.length === 0 && <p className="progress-note" role="status">
          {Array.isArray(data?.stages) ? "No workflow stages are listed in this view." : "Workflow stage information is unavailable."}
        </p>}
        <ol className="progress-timeline" aria-label="Workflow timeline">
          {stages.map(item => {
            const state = Object.hasOwn(stateLabels, item.state) ? item.state : "unknown";
            const steps = Array.isArray(item.steps) ? item.steps : null;
            return (
              <li key={item.name} className={`progress-${state}`}>
                <details>
                  <summary className="progress-stage-row">
                    <span>{item.name}</span><strong>{stateLabels[state]}</strong>
                  </summary>
                  <div className="progress-stage-details">
                    {stageDescriptions[item.name] && <p className="progress-detail-empty"><strong>Stage purpose:</strong> {stageDescriptions[item.name]}</p>}
                    <h5>Milestones</h5>
                    {steps?.length ? <ul>
                      {steps.map((step, index) => <li key={`${step.name}-${index}`}>
                        <span>{step.name}</span><strong>{stateLabels[step.state] || stateLabels.unknown}</strong>
                      </li>)}
                    </ul> : <p className="progress-detail-empty">
                      {steps ? "No milestones are listed for this stage." : "Detailed milestones are not included in this view."}
                    </p>}
                    {state === "unknown" && <p className="progress-detail-empty">This stage's status cannot be verified from the available information.</p>}
                  </div>
                </details>
              </li>
            );
          })}
        </ol>
        {stages.some(item => !["completed", "current", "pending"].includes(item.state)) && <p className="progress-note">Some stage information is unavailable; unverified stages are not marked complete.</p>}
        <p className="progress-note">Publication is a local prototype.</p>
      </>}
    </section>
  );
}

export default ManuscriptProgress;
