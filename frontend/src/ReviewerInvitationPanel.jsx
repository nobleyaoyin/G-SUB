import {workflowStatusLabel} from './workflowStatus';
import useReturnRefresh from "./useReturnRefresh";
import { useCallback, useEffect, useState } from "react";
import { API_URL, actionFailureMessage, submitAction } from "./api";
import "./ReviewerInvitationPanel.css";

export default function ReviewerInvitationPanel({ manuscriptId, round, status, token, onChanged, invitationPath = "/assignments/", artifactBinding = false, splitReview, allowBrowse = false }) {
  const [assignments, setAssignments] = useState([]);
  const [progress, setProgress] = useState(null);
  const [reviewerId, setReviewerId] = useState("");
  const [query, setQuery] = useState("");
  const [reviewers, setReviewers] = useState([]);
  const [searchState, setSearchState] = useState("idle");
  const [searchVersion, setSearchVersion] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const load = useCallback(async () => {
    const headers = { Authorization: `Bearer ${token}` };
    const [response, summary] = await Promise.all([
      fetch(`${API_URL}/assignments/manuscript/${manuscriptId}`, { headers }),
      fetch(`${API_URL}/assignments/manuscript/${manuscriptId}/summary`, { headers }),
    ]);
    if (!response.ok || !summary.ok) throw new Error("Could not load reviewer invitations and progress.");
    setAssignments(await response.json());
    setProgress((await summary.json()).decision_progress);
  }, [manuscriptId, token]);
  useEffect(() => { load().catch(e => setError(e.message)); }, [load]);
  useEffect(() => {
    const controller = new AbortController();
    const term = query.trim();
    setReviewers([]); setReviewerId("");
    if ((!term && !allowBrowse) || (term.length > 0 && term.length < 2) || !["ready_for_peer_review", "revised"].includes(status)) {
      setSearchState("idle");
      return () => controller.abort();
    }
    setSearchState("loading");
    const timer = setTimeout(async () => {
      try {
        const all = [], seen = new Set();
        for (let offset = 0; offset <= 100000; offset += 20) {
          const response = await fetch(`${API_URL}/assignments/manuscript/${manuscriptId}/reviewer-directory?${new URLSearchParams({ ...(term ? { q: term } : {}), offset: String(offset) })}`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal });
          if (!response.ok) throw new Error("Search unavailable");
          const data = await response.json();
          if (!Array.isArray(data) || data.length > 20) throw new Error("Invalid search response");
          for (const reviewer of data) {
            if (!reviewer || seen.has(reviewer.reviewer_id)) throw new Error("Incomplete reviewer directory");
            seen.add(reviewer.reviewer_id); all.push(reviewer);
          }
          if (data.length < 20) break;
          if (offset === 100000) throw new Error("Incomplete reviewer directory");
        }
        if (!controller.signal.aborted) { setReviewers(all); setSearchState("ready"); }
      } catch {
        if (!controller.signal.aborted) { setReviewers([]); setSearchState("error"); }
      }
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, manuscriptId, round, status, token, searchVersion, allowBrowse]);
  useReturnRefresh(() => load().then(() => { setNeedsRefresh(false); setError(""); setSearchVersion(value => value + 1); }).catch(e => setError(e.message)), busy);
  const invite = async event => {
    event.preventDefault(); if (busy || needsRefresh || !reviewers.some(r => String(r.reviewer_id) === reviewerId && r.selectable)) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await submitAction(`${API_URL}${splitReview?.classification === "split" ? "/assignments/additional-reviewer" : invitationPath}`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ manuscript_id: manuscriptId, reviewer_id: Number(reviewerId), review_round: round }) });
    } catch (e) {
      setError(actionFailureMessage(e)); if (!e.confirmedRejection) setNeedsRefresh(true); setBusy(false); return;
    }
    setReviewerId(""); setMessage("Reviewer invitation sent."); setSearchVersion(value => value + 1);
    try { await load(); if (onChanged && await onChanged() === false) throw new Error("Refresh superseded"); }
    catch { setNeedsRefresh(true); setError("Invitation saved, but refresh failed. Displayed data may be stale. Return to this view to check; do not repeat the action."); }
    finally { setBusy(false); }
  };
  const current = assignments.filter(a => a.review_round === round);
  const active = current.filter(a => a.invitation_status !== "declined");
  const selected = reviewers.find(r => String(r.reviewer_id) === reviewerId);
  const bindArtifact = async assignmentId => {
    if (busy || needsRefresh) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await submitAction(`${API_URL}/assignments/demo-invitations/${assignmentId}/bind-artifact`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      setMessage("Reviewer document bound.");
      try { await load(); } catch { setNeedsRefresh(true); setError("Binding saved, but refresh failed. Return to this view to check before retrying."); }
    } catch (e) { setError(actionFailureMessage(e)); if (!e.confirmedRejection) setNeedsRefresh(true); }
    finally { setBusy(false); }
  };
  return (
    <section className="reviewer-invitation-panel" aria-label="Reviewer invitations">
      <div className="reviewer-panel-heading">
        <div>
          <span className="reviewer-panel-eyebrow">PEER REVIEW</span>
          <h4>Reviewer Assignment</h4>
          <p>Manage reviewer invitations and monitor review progress.</p>
        </div>
        <span className="reviewer-round-badge">Round {round}</span>
      </div>

      <div className="reviewer-summary-grid">
        <div className="reviewer-summary-card">
          <span>Active Reviewers</span>
          <strong>{active.length}</strong>
          <small>Current review round</small>
        </div>

        {progress && (
          <div className="reviewer-summary-card">
            <span>Decision progress</span>
            <strong>
              {Math.min(progress.completed_distinct, progress.required)}/{progress.required}
            </strong>
            <small>
              Completed distinct reviewers
              {progress.policy === "legacy" ? " · Historical rule" : ""}
            </small>
          </div>
        )}
      </div>

      {progress && progress.completed_distinct > progress.required && (
        <p className="reviewer-progress-extra">
          {progress.completed_distinct} reviewers have completed their reviews.
        </p>
      )}

      {error && <p className="reviewer-feedback error" role="alert">{error}</p>}
      {message && <p className="reviewer-feedback success" role="status">{message}</p>}

      {["ready_for_peer_review", "revised"].includes(status) &&
        progress?.blocked_reason && (
          <p className="reviewer-feedback warning">
            Decision blocked: {progress.blocked_reason}
          </p>
        )}

      <section className="reviewer-assignment-section">
        <div className="reviewer-section-heading">
          <h5>Assigned Reviewers</h5>
          <span>{assignments.length} total assignments</span>
        </div>

        {assignments.length ? (
          <div className="reviewer-assignment-list">
            {assignments.map(a => (
              <article className="reviewer-assignment-card" key={a.assignment_id}>
                <div className="reviewer-assignment-main">
                  <div className="reviewer-avatar" aria-hidden="true">
                    R
                  </div>
                  <div>
                    <strong>Reviewer #{a.reviewer_id}</strong>
                    <p>Review round {a.review_round}</p>
                  </div>
                </div>

                <div className="reviewer-assignment-statuses">
                  <span className={`reviewer-status invitation-${a.invitation_status}`}>
                    {a.invitation_status === "legacy"
                      ? "Existing assignment"
                      : workflowStatusLabel(a.invitation_status)}
                  </span>
                  <span className={`reviewer-status review-${a.status}`}>
                    {a.status === "completed"
                      ? "Completed"
                      : a.invitation_status === "declined"
                        ? "Declined"
                        : a.invitation_status === "pending"
                          ? "Awaiting response"
                          : "Assigned"}
                  </span>
                </div>

                {artifactBinding &&
                  a.review_round === round &&
                  a.invitation_status === "accepted" &&
                  a.status === "assigned" && (
                    <button
                      type="button"
                      className="reviewer-bind-button"
                      disabled={busy || needsRefresh}
                      onClick={() => bindArtifact(a.assignment_id)}
                    >
                      Bind reviewer document
                    </button>
                  )}
              </article>
            ))}
          </div>
        ) : (
          <div className="reviewer-empty-state">
            <strong>No reviewers assigned yet</strong>
            <p>Reviewer assignments will appear here once invitations are sent.</p>
          </div>
        )}
      </section>

      {["ready_for_peer_review", "revised"].includes(status) &&
        (splitReview?.classification !== "split" || splitReview.can_invite_additional) && (
          <section className="reviewer-search-section">
            <div className="reviewer-section-heading">
              <h5>Invite a Reviewer</h5>
              <span>Reviewer directory</span>
            </div>

            <form className="reviewer-directory-form" onSubmit={invite}>
              <label>
                Search reviewers by name, email or institution
                <input
                  type="search"
                  maxLength={100}
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  autoComplete="off"
                  placeholder="Enter reviewer name, email or institution..."
                />
              </label>

              <p className="reviewer-search-feedback" aria-live="polite">
                {searchState === "idle"
                  ? allowBrowse ? "Enter at least two characters to search, or clear the field to browse." : "Enter at least two characters to search."
                  : searchState === "loading"
                    ? "Searching reviewers…"
                    : searchState === "error"
                      ? "Reviewer search failed. Change the search or return to this view."
                      : reviewers.length
                        ? "Select one reviewer. Existing assignments cannot be selected again."
                        : "No matching reviewers."}
              </p>

              <label>
                Reviewer
                <select
                  value={reviewerId}
                  onChange={e => setReviewerId(e.target.value)}
                  required
                  disabled={busy || searchState !== "ready" || reviewers.length === 0}
                >
                  <option value="">Choose a reviewer</option>
                  {reviewers.map(r => (
                    <option
                      key={r.reviewer_id}
                      value={r.reviewer_id}
                      disabled={!r.selectable}
                    >
                      {[r.name, r.profile?.professional_title, r.profile?.institution, r.email]
                        .filter(Boolean).join(" — ")}
                      {r.invitation_status
                        ? ` · ${workflowStatusLabel(r.invitation_status)} / ${workflowStatusLabel(r.assignment_status)}`
                        : ""}
                    </option>
                  ))}
                </select>
              </label>

              {selected && (
                <div className="reviewer-profile-summary">
                  <div className="reviewer-profile-heading">
                    <strong>Professional Profile</strong>
                    <span>
                      {selected.profile
                        ? "self-reported; not verified"
                        : "Not provided or unavailable"}
                    </span>
                  </div>

                  <dl>
                    {[
                      ["Title", selected.profile?.professional_title],
                      ["Institution", selected.profile?.institution],
                      ["Department", selected.profile?.department],
                      ["Research Areas", selected.profile?.research_areas?.join(", ")],
                      ["Expertise", selected.profile?.expertise?.join(", ")]
                    ].map(([label, value]) => (
                      <div key={label}>
                        <dt>{label}</dt>
                        <dd>{value || (selected.profile
                          ? "Not provided"
                          : "Not provided or unavailable")}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}

              <button
                className="reviewer-invite-button"
                disabled={busy || needsRefresh || !reviewerId}
              >
                {busy
                  ? "Processing..."
                  : splitReview?.classification === "split"
                    ? "Invite additional reviewer"
                    : "Invite reviewer"}
              </button>

              {splitReview?.classification === "split" && (
                <p className="reviewer-split-hint">
                  Reviewer recommendations are split. An additional reviewer can be invited.
                </p>
              )}
            </form>
          </section>
        )}
    </section>
  );
}
