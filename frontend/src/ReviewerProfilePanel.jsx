import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL } from "./api";
import "./ReviewerProfilePanel.css";
import useReturnRefresh from "./useReturnRefresh";

const empty = { full_name: "", professional_title: "", institution: "", department: "", research_areas: "", expertise: "" };
const fields = [["professional_title", "Professional Title", 100], ["institution", "Institution / Affiliation", 200], ["department", "Department", 150]];
const lists = [["research_areas", "Research Areas"], ["expertise", "Expertise Keywords"]];
const fromProfile = (profile, account) => ({ full_name: account?.name || "", professional_title: profile?.professional_title || "", institution: profile?.institution || "", department: profile?.department || "", research_areas: (profile?.research_areas || []).join("\n"), expertise: (profile?.expertise || []).join("\n") });
const hasControls = value => /\p{C}/u.test(value);

function validate(form, account) {
  const result = {};
  if (account) {
    const name = form.full_name.trim();
    if (!name || Array.from(form.full_name).length > 100 || hasControls(name)) throw new Error('Full name is required, with at most 100 characters and no control characters.');
    result.full_name = name;
  }
  for (const [key, label, limit] of fields) {
    const raw = form[key]; const value = raw.trim();
    if (Array.from(raw).length > limit || (value && hasControls(value))) throw new Error(`${label} must contain at most ${limit} characters and no control characters.`);
    result[key] = value || null;
  }
  for (const [key, label] of lists) {
    const values = form[key].split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (values.length > 12 || values.some(value => Array.from(value).length > 80 || hasControls(value))) throw new Error(`${label} supports up to 12 entries, each at most 80 characters without control characters.`);
    result[key] = values;
  }
  return result;
}

export default function ReviewerProfilePanel({ token, onDirtyChange }) {
  const [form, setForm] = useState(empty);
  const [account, setAccount] = useState(null);
  const [saved, setSaved] = useState(empty);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [available, setAvailable] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const loadRequest = useRef(null);
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);

  const load = useCallback(async () => {
    loadRequest.current?.abort();
    const controller = new AbortController(); loadRequest.current = controller; const signal = controller.signal;
    setLoading(true); setError(""); setMessage("");
    try {
      const response = await fetch(`${API_URL}/users/me/reviewer-profile`, { headers: { Authorization: `Bearer ${token}` }, signal });
      if (!response.ok) throw new Error(response.status === 503 ? "Professional profile is currently unavailable. Try again later." : "Could not load your professional profile.");
      const data = await response.json();
      if (signal?.aborted) return;
      const value = fromProfile(data.profile, data.account); setAccount(data.account || null);
      setForm(value); setSaved(value); onDirtyChange(false); setAvailable(true); setUncertain(false);
    } catch (err) {
      if (!signal?.aborted) { setAvailable(false); setError(err.message || "Could not load your professional profile."); }
    } finally { if (!signal?.aborted) setLoading(false); }
  }, [token, onDirtyChange]);
  useEffect(() => { load(); return () => loadRequest.current?.abort(); }, [load]);
  useReturnRefresh(load, busy || dirty);
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = event => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const change = (key, value) => {
    const next = { ...form, [key]: value }; setForm(next); onDirtyChange(JSON.stringify(next) !== JSON.stringify(saved)); setMessage("");
  };
  const reset = () => { if (!dirty || window.confirm("Discard unsaved profile changes?")) { setForm(saved); onDirtyChange(false); setError(""); setMessage(""); } };
  const submit = async event => {
    event.preventDefault(); if (busy || uncertain) return;
    let payload;
    try { payload = validate(form, account); } catch (err) { setError(err.message); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      let response;
      try { response = await fetch(`${API_URL}/users/me/reviewer-profile`, { method: "PUT", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }
      catch { setUncertain(true); throw new Error("Save outcome could not be confirmed. Close and reopen the profile to check before retrying."); }
      if (!response.ok) {
        if (response.status >= 500 || response.status === 408) { setUncertain(true); throw new Error("Save outcome could not be confirmed. Close and reopen the profile to check before retrying."); }
        throw new Error(response.status === 422 ? "Profile values are invalid. Check the field limits and try again." : "Profile save was rejected.");
      }
      let data;
      try { data = await response.json(); } catch { setUncertain(true); throw new Error("Profile was saved, but the response could not be read. Close and reopen the profile before making further changes."); }
      if (!data?.profile) { setUncertain(true); throw new Error("Profile was saved, but the response was incomplete. Close and reopen the profile before making further changes."); }
      const nextAccount = data.account || account; const value = fromProfile(data.profile, nextAccount); setAccount(nextAccount); setForm(value); setSaved(value); onDirtyChange(false); setMessage("Professional profile saved.");
    } catch (err) {
      setError(err.message || "Save outcome could not be confirmed. Close and reopen the profile to check before retrying.");
    } finally { setBusy(false); }
  };

  return <section className="reviewer-profile-panel" aria-label="My professional profile">
    <h2>My professional profile</h2><p>Information is self-reported and is not institutionally verified.</p>
    {loading && <p role="status">Loading profile…</p>}{error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {!loading && !available && <p>Return to this view to try loading again.</p>}
    {!loading && available && <form onSubmit={submit} noValidate>
      {account && <><label>Full Name<input value={form.full_name} onChange={e => change('full_name', e.target.value)} disabled={busy} required /></label><p>Email: {account.email || 'Unavailable'} (account sign-in email)</p><p>Email changes require a verified account change process.</p></>}
      {fields.map(([key, label, limit]) => <label key={key}>{label}<input value={form[key]} onChange={e => change(key, e.target.value)} disabled={busy} aria-describedby={`${key}-help`} /><small id={`${key}-help`}>Optional; up to {limit} characters.</small></label>)}
      {lists.map(([key, label]) => <label key={key}>{label}<textarea value={form[key]} onChange={e => change(key, e.target.value)} disabled={busy} rows={3} aria-describedby={`${key}-help`} /><small id={`${key}-help`}>One entry per line; up to 12 entries, 80 characters each.</small></label>)}
      <div className="reviewer-profile-actions"><button type="submit" disabled={busy || uncertain}>Save profile</button><button type="button" disabled={busy || !dirty} onClick={reset}>Discard changes</button></div>
    </form>}
  </section>;
}
