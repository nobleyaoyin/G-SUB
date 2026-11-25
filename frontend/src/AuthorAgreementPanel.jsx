import {workflowStatusLabel} from './workflowStatus';
import useReturnRefresh from "./useReturnRefresh";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL } from "./api";
import "./InitialEditingPanel.css";

function recordedTime(value) {
  if (!/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return `${value.replace('T', ' ')} (timezone not recorded)`;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function AuthorAgreementPanel({ token, onChanged, manuscriptId }) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const scope = useRef({ token, manuscriptId });
  const sequence = useRef(0);
  const running = useRef(null);
  if (scope.current.token !== token || scope.current.manuscriptId !== manuscriptId) {
    scope.current = { token, manuscriptId }; sequence.current++;
  }
  const [owner, setOwner] = useState(scope.current);
  const load = useCallback(async () => {
    const expected = scope.current, version = ++sequence.current;
    setLoading(true);
    try {
    const response = await fetch(`${API_URL}/agreements/my`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new Error("Could not load author agreements.");
    const result = await response.json();
    if (scope.current === expected && sequence.current === version) setItems(result);
    } finally {
      if (scope.current === expected && sequence.current === version) setLoading(false);
    }
  }, [token, manuscriptId]);
  useEffect(() => {
    const expected = scope.current;
    setOwner(expected); setItems([]); setError(""); setMessage(""); setBusy(false);
    load().catch(e => { if (scope.current === expected) setError(e.message); });
  }, [load]);
  useReturnRefresh(() => {
    const expected = scope.current;
    return load().catch(e => { if (scope.current === expected) setError(e.message); });
  }, busy);
  const respond = async (item, decision) => {
    const expected = scope.current;
    if (running.current === expected) return;
    running.current = expected;
    setBusy(true); setError(""); setMessage("");
    let body;
    try {
      const response = await fetch(`${API_URL}/agreements/${item.agreement_id}/respond`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ decision, agreement_version: item.agreement_version }),
      });
      body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}).`);
      if (body.status !== (decision === "accept" ? "accepted" : "declined")) throw new Error("The saved response could not be verified");
    } catch (e) {
      if (scope.current === expected) {
        setError(`Could not confirm the agreement response: ${e.message}. Return to this view to check its status before trying again.`);
        setBusy(false);
      }
      if (running.current === expected) running.current = null;
      return;
    }
    if (scope.current !== expected) { if (running.current === expected) running.current = null; return; }
    // Keep the saved response visible and prevent another submission even if a refresh fails.
    const savedStatus = body.status;
    setItems(previous => previous.map(existing => existing.agreement_id === item.agreement_id
      ? { ...existing, status: savedStatus, manuscript_status: body.manuscript_status, responded_at: body.responded_at }
      : existing));
    setMessage(`Agreement response recorded: ${savedStatus}.`);
    const results = await Promise.allSettled([load(), Promise.resolve().then(() => onChanged?.())]);
    if (scope.current !== expected) { if (running.current === expected) running.current = null; return; }
    if (results.some(result => result.status === "rejected" || result.value === false)) {
      setError("Response saved, but refresh failed. Return to this view to check the latest status; do not submit the response again.");
    }
    setBusy(false);
    if (running.current === expected) running.current = null;
  };
  const visibleItems = manuscriptId == null ? items : items.filter(item => item.manuscript_id === manuscriptId);
  if (owner !== scope.current) return null;
  if (!visibleItems.length && !error && !message && !loading) return null;
  return <section
    className="initial-editing-panel author-agreement-panel"
    aria-label="Author agreements"
  >
    <div className="initial-editing-heading">
      <div>
        <h2>Author Agreement</h2>
        <p className="agreement-description">
          Review and respond to your manuscript agreement.
        </p>
      </div>
    </div>

    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {loading && <p role="status">Loading author agreements…</p>}

    {!visibleItems.length ? (!loading && (
      <div className="agreement-empty">
        <h3>No pending agreements</h3>
        <p>There are currently no author agreements requiring your response.</p>
      </div>
    )) : (
      <div className="agreement-list">
        {visibleItems.map(item => (
          <article className="agreement-card" key={item.agreement_id}>
            <div className="agreement-card-header">
              <div>
                <span className="agreement-eyebrow">
                  MANUSCRIPT #{item.manuscript_id}
                </span>
                <h3>{item.manuscript_title}</h3>
              </div>

              <span className={`agreement-status ${item.status}`}>
                {typeof item.status === "string"
                  ? workflowStatusLabel(item.status)
                  : "Unknown"}
              </span>
            </div>

            <div className="agreement-metadata">
              <span>
                Version
                <strong>{item.agreement_version}</strong>
              </span>
              {item.created_at && <span>Generated <strong>{recordedTime(item.created_at)}</strong></span>}
              {item.responded_at && (
                <span>
                  Responded
                  <strong>{recordedTime(item.responded_at)}</strong>
                </span>
              )}
            </div>

            <div className="agreement-terms">
              {item.template_status === 'prototype' && <p>Prototype only — this is not an approved legal agreement.</p>}
              {item.template_status === 'prototype' && <p>Template approval: Pending owner approval.</p>}
              {item.template_status === 'unverified' && <p>Template approval is unavailable for this historical agreement.</p>}
              <h4>Agreement Terms</h4>
              <div className="agreement-text">{item.agreement_text}</div>
            </div>

            {item.status === "pending" &&
              item.manuscript_status === "awaiting_author_agreement" && (
                <div className="agreement-actions">
                  <p>Please review the agreement before submitting your decision.</p>
                  <div className="agreement-buttons">
                    <button
                      type="button"
                      className="agreement-accept"
                      disabled={busy}
                      onClick={() => respond(item, "accept")}
                    >
                      Accept Agreement
                    </button>
                    <button
                      type="button"
                      className="agreement-decline"
                      disabled={busy}
                      onClick={() => respond(item, "decline")}
                    >
                      Decline Agreement
                    </button>
                  </div>
                </div>
              )}

            {item.status === "declined" && (
              <div className="agreement-notice">
                Final editing is on hold. Contact the editorial team.
              </div>
            )}
          </article>
        ))}
      </div>
    )}
  </section>;
}
