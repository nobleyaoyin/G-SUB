import useReturnRefresh from "./useReturnRefresh";
import { useCallback, useEffect, useState } from "react";
import { API_URL } from "./api";
import "./InitialEditingPanel.css";

export default function AuthorAgreementPanel({ token, onChanged, manuscriptId }) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const response = await fetch(`${API_URL}/agreements/my`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new Error("Could not load author agreements.");
    setItems(await response.json());
  }, [token]);
  useEffect(() => { load().catch(e => setError(e.message)); }, [load]);
  useReturnRefresh(() => load().catch(e => setError(e.message)), busy);
  const respond = async (item, decision) => {
    setBusy(true); setError(""); setMessage("");
    let body;
    try {
      const response = await fetch(`${API_URL}/agreements/${item.agreement_id}/respond`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ decision, agreement_version: item.agreement_version }),
      });
      body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}).`);
    } catch (e) {
      setError(`Could not confirm the agreement response: ${e.message}. Return to this view to check its status before trying again.`);
      setBusy(false);
      return;
    }
    // Keep the saved response visible and prevent another submission even if a refresh fails.
    const savedStatus = body.status || (decision === "accept" ? "accepted" : "declined");
    setItems(previous => previous.map(existing => existing.agreement_id === item.agreement_id
      ? { ...existing, status: savedStatus, manuscript_status: body.manuscript_status, responded_at: body.responded_at }
      : existing));
    setMessage(`Prototype agreement ${savedStatus}.`);
    const results = await Promise.allSettled([load(), Promise.resolve().then(() => onChanged())]);
    if (results.some(result => result.status === "rejected" || result.value === false)) {
      setError("Response saved, but refresh failed. Return to this view to check the latest status; do not submit the response again.");
    }
    setBusy(false);
  };
  const visibleItems = manuscriptId == null ? items : items.filter(item => item.manuscript_id === manuscriptId);
  if (!visibleItems.length && !error && !message) return null;
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

    {!visibleItems.length ? (
      <div className="agreement-empty">
        <h3>No pending agreements</h3>
        <p>There are currently no author agreements requiring your response.</p>
      </div>
    ) : (
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
                  ? item.status.replaceAll("_", " ")
                  : "Unknown"}
              </span>
            </div>

            <div className="agreement-metadata">
              <span>
                **Version**
                <strong>{item.agreement_version}</strong>
              </span>
              {item.responded_at && (
                <span>
                  **Responded**
                  <strong>{new Date(item.responded_at).toLocaleString()}</strong>
                </span>
              )}
            </div>

            <div className="agreement-terms">
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
