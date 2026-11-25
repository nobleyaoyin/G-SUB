import { useEffect, useState } from "react";
import { API_URL } from "./api";

export default function EICReviewPolicyPanel({ manuscriptId, token, invitationCount, onChanged }) {
  const [policy, setPolicy] = useState(null);
  const [choice, setChoice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const url = `${API_URL}/eic/manuscripts/${manuscriptId}/review-policy`;
  useEffect(() => {
    const controller = new AbortController();
    fetch(url, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(); return response.json(); })
      .then(setPolicy)
      .catch(error => { if (error.name !== "AbortError") setError("Review policy is unavailable. Refresh before retrying."); });
    return () => controller.abort();
  }, [url, token, invitationCount]);
  async function save(event) {
    event.preventDefault();
    if (!policy || !choice || busy) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(url, { method: "PUT", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ mode: choice, expected_revision: policy.revision }) });
      if (!response.ok) throw new Error();
      setPolicy(await response.json()); setChoice("");
      try {
        if (onChanged && await onChanged() === false) throw new Error('Refresh superseded');
      } catch {
        setError('Policy saved, but dashboard refresh failed. Return to this view before acting.');
      }
    } catch {
      setError("Policy could not be saved or its outcome is uncertain. Refresh before retrying.");
      setPolicy(null);
    } finally { setBusy(false); }
  }
  return <section aria-label="Review policy">
    <h4>Review policy</h4>
    {error && <p role="alert">{error}</p>}
    {!policy && !error && <p>Loading review policy…</p>}
    {policy && <>
      <p>State: {policy.state === "missing" ? "Missing — requires EIC review" : policy.state === "selected" ? "Selected" : "Locked"}{policy.mode ? ` · ${policy.mode === "single_blind" ? "Single blind" : "Double blind"}` : ""}</p>
      {policy.state !== "locked" && <form onSubmit={save}>
        <label>Review mode <select required value={choice} onChange={event => setChoice(event.target.value)}>
          <option value="">Select a mode</option><option value="single_blind">Single blind</option><option value="double_blind">Double blind</option>
        </select></label>
        <button disabled={busy || !choice || choice === policy.mode}>Save review policy</button>
      </form>}
      <p>The policy locks when the first reviewer invitation is created. Existing assignments without a policy require separate editorial review.</p>
      <p>Documents are not automatically anonymized.</p>
      {policy.mode === "double_blind" && <p>Double blind reviewer downloads require an approved reviewer copy. The release service is not configured; contact the system administrator before inviting reviewers.</p>}
    </>}
  </section>;
}
