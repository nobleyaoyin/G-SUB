import {displayError} from './displayError';
import {workflowStatusLabel} from './workflowStatus';
import { useState } from 'react';
import { API_URL } from './api';
import './EICCandidateVerification.css';

const items = [
  ['author_names', 'Author names'], ['affiliations', 'Institutional affiliations'],
  ['contact_information', 'Contact information'], ['document_metadata', 'Document metadata'],
  ['word_comments', 'Embedded comments'], ['revision_history', 'Revision history and tracked changes'],
  ['headers_footers', 'Headers and footers'], ['hidden_text', 'Hidden text'],
  ['figures_supplements', 'Figures and supplements'], ['acknowledgements_references', 'Acknowledgments and references'],
  ['filename_verified', 'Download filename'],
];

export default function EICCandidateVerification({ manuscriptId, token }) {
  const [candidates, setCandidates] = useState(null);
  const [selected, setSelected] = useState('');
  const [info, setInfo] = useState(null);
  const [checks, setChecks] = useState({});
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const root = `/eic/manuscripts/${manuscriptId}`;
  async function request(path, options = {}) {
    const res = await fetch(`${API_URL}${path}`, { ...options, headers: { Authorization: `Bearer ${token}`, ...options.headers } });
    if (!res.ok) { const body = await res.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`); }
    return res;
  }
  async function load() {
    setBusy(true); setError('');
    try { const data = await (await request(`${root}/reviewer-candidate-reconciliation`)).json(); setCandidates(data.candidates.filter(c => c.stored)); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function select(id) {
    setSelected(id); setInfo(null); setChecks({}); setReason(''); setMessage(''); setError('');
    if (!id) return;
    setBusy(true);
    try { setInfo(await (await request(`${root}/reviewer-candidates/${encodeURIComponent(id)}/processing`)).json()); }
    catch (e) { setError(`Processing information unavailable: ${e.message}`); } finally { setBusy(false); }
  }
  const base = `${root}/reviewer-candidates/${encodeURIComponent(selected)}`;
  const context = info && { expected_sha256: info.prepared_sha256, expected_artifact_version: info.artifact_version, expected_review_round: info.review_round };
  async function act(action, body) {
    if (!window.confirm(`${action === 'approve' ? 'Approve' : action === 'reject' ? 'Reject' : 'Record verification for'} this exact candidate?`)) return;
    setBusy(true); setError(''); setMessage('');
    try {
      await request(`${base}/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const updated = await (await request(`${base}/processing`)).json(); setInfo(updated); setMessage(`Candidate ${action === 'verify' ? 'verified' : action === 'approve' ? 'approved' : 'rejected'}.`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function download() {
    setBusy(true); setError('');
    try {
      const blob = await (await request(`${base}/content`)).blob(); const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = 'review-candidate.docx'; a.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <details className="eic-context-panel" onToggle={e => { if (e.currentTarget.open && candidates === null && !busy) load(); }}>
    <summary>Private reviewer document verification</summary>
    <div className="eic-context-content candidate-verification">
      <p>Inspect the document content and filename. Metadata preparation alone does not establish anonymity. Approval does not distribute the document.</p>
      {busy && <p role="status">Loading or saving…</p>}{error && <p role="alert">{displayError(error)}</p>}{message && <p role="status">{message}</p>}
      {candidates && !candidates.length && <p>No prepared candidates are available.</p>}
      {!!candidates?.length && <label>Candidate <select value={selected} onChange={e => select(e.target.value)} disabled={busy}><option value="">Select a candidate</option>{candidates.map(c => <option key={c.candidate_id} value={c.candidate_id}>{c.candidate_id} — {c.reserved_at}</option>)}</select></label>}
      {info && <>
        <p><strong>Manuscript:</strong> {info.manuscript_id} · <strong>Review round:</strong> {info.review_round} · <strong>Candidate version:</strong> {info.artifact_version}</p>
        <p><strong>Human review:</strong> {workflowStatusLabel(info.human_review.status)} · <strong>Approval:</strong> {workflowStatusLabel(info.approval.status)} · <strong>Filename:</strong> {workflowStatusLabel(info.filename_verification.status)}</p>
        <div className="candidate-digests"><section><h4>Source artifact</h4><p>Source ID: {info.source_id}</p><p>SHA-256: <code>{info.source_sha256}</code></p></section><section><h4>Prepared candidate</h4><p>Candidate ID: {info.candidate_id}</p><p>SHA-256: <code>{info.prepared_sha256}</code></p><p>Method: {info.method} · {info.processed_at}</p></section></div>
        <button type="button" disabled={busy} onClick={download}>Download private candidate</button>
        <p>Inspect the downloaded filename and all document contents before recording verification.</p>
        {info.human_review.status === 'pending' && <fieldset disabled={busy}><legend>Human verification checklist</legend>{items.map(([key, label]) => <label key={key} className="candidate-check"><input type="checkbox" checked={!!checks[key]} onChange={e => setChecks({...checks, [key]: e.target.checked})} /> I checked {label.toLowerCase()}.</label>)}
          <button type="button" disabled={!items.every(([key]) => checks[key])} onClick={() => act('verify', {...checks, ...context})}>Record human verification</button></fieldset>}
        {info.human_review.status === 'verified' && info.approval.status !== 'approved' && <button type="button" disabled={busy} onClick={() => act('approve', {...context, confirmed: true})}>Approve verified candidate</button>}
        {info.human_review.status !== 'rejected' && info.approval.status !== 'approved' && <div className="candidate-rejection"><label>Reason for rejection<textarea value={reason} onChange={e => setReason(e.target.value)} maxLength={1000} /></label><button type="button" disabled={busy || !reason.trim()} onClick={() => act('reject', {reason})}>Reject candidate</button></div>}
        <h4>Recorded history</h4><p>Verification: {info.human_review.verified_at || 'Unavailable'}{info.human_review.verifier_id ? ` · EIC ${info.human_review.verifier_id}` : ''}</p><p>Approval: {info.approval.approved_at || 'Unavailable'}{info.approval.approver_id ? ` · EIC ${info.approval.approver_id}` : ''}</p>{info.human_review.rejected_at && <p>Rejected {info.human_review.rejected_at} · EIC {info.human_review.rejected_by}: {info.human_review.reason}</p>}
      </>}
    </div>
  </details>;
}
