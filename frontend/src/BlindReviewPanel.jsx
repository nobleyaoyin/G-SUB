import useReturnRefresh from "./useReturnRefresh";
import { useCallback, useEffect, useState } from "react";
import { API_URL, actionFailureMessage, submitAction } from "./api";
import ReviewerInvitationPanel from "./ReviewerInvitationPanel";

// The server controls availability; no request parameter enables the experimental mode.
export default function BlindReviewPanel({ manuscriptId, round, status, token, onChanged, splitReview }) {
  const [policy, setPolicy] = useState(null);
  const [state, setState] = useState("loading");
  const [choice, setChoice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const load = useCallback(async () => {
    const response = await fetch(`${API_URL}/assignments/review-policy/${manuscriptId}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
    if (response.status === 404) { setState("disabled"); return; }
    if (!response.ok) throw new Error("Blind review status unavailable.");
    setPolicy(await response.json()); setState("ready"); setNeedsRefresh(false);
  }, [manuscriptId, token]);
  useEffect(() => { let active = true; load().catch(e => { if (active) { setState("error"); setError(e.message); } }); return () => { active = false; }; }, [load]);
  useReturnRefresh(() => load().catch(e => setError(e.message)), busy);
  const save = async event => {
    event.preventDefault(); if (busy || needsRefresh || !choice) return;
    setBusy(true); setError("");
    try {
      await submitAction(`${API_URL}/assignments/review-policy/${manuscriptId}`, { method: "PUT", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ mode: choice, expected_revision: policy?.revision ?? null }) });
      setChoice("");
      try { await load(); } catch { setNeedsRefresh(true); setError("Mode saved, but refresh failed. Return to this view before making another change."); }
    } catch (e) { setError(actionFailureMessage(e)); if (!e.confirmedRejection) setNeedsRefresh(true); }
    finally { setBusy(false); }
  };
  if (state === "loading") return <p>Loading reviewer invitation settings…</p>;
  if (state === "disabled") return <ReviewerInvitationPanel manuscriptId={manuscriptId} round={round} status={status} token={token} onChanged={onChanged} splitReview={splitReview} />;
  if (state === "error") return <p role="alert">{error}</p>;
  return <section aria-label="Blind review"><h3>Blind review (experimental)</h3>
    <p>Mode: {policy?.mode === "single_blind" ? "Single-Blind" : policy?.mode === "double_blind" ? "Double-Blind" : "Not selected"} · {policy?.locked ? "Locked" : "Not locked"}</p>
    {error && <p role="alert">{error}</p>}
    {!policy?.locked && <form onSubmit={save}><label>Review mode <select required value={choice} onChange={e => setChoice(e.target.value)}><option value="">Choose mode</option><option value="single_blind">Single-Blind</option><option value="double_blind">Double-Blind</option></select></label><button disabled={busy || needsRefresh || !choice}>Save review mode</button></form>}
    {policy?.mode === "double_blind" && <p>Use a separately prepared, approved reviewer document. Bind it after the reviewer accepts; uploads are not automatically anonymized.</p>}
    {policy?.mode && <ReviewerInvitationPanel manuscriptId={manuscriptId} round={round} status={status} token={token} onChanged={async () => { await load(); return onChanged?.(); }} invitationPath="/assignments/review-invitations" artifactBinding={policy.mode === "double_blind"} splitReview={splitReview} />}
  </section>;
}
