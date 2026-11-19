import useReturnRefresh from "./useReturnRefresh";
import { useCallback, useEffect, useState } from "react";
import { API_URL } from "./api";
import "./InitialEditingPanel.css";
import OnlineDocumentEditor from "./OnlineDocumentEditor";
import OnlineDocxEditor from "./OnlineDocxEditor";
import { initialEditingPrompt } from "./participantPrompts";
import EditorInvitationSummary from "./EditorInvitationSummary";

const readable = value => (value || "unknown").replaceAll("_", " ");

function EditingItem({ item, role, perform, download, busy, token, onOnlineDirtyChange, showTitle, stale }) {
  const [decision, setDecision] = useState("");
  const [comments, setComments] = useState("");
  const [file, setFile] = useState(null);
  const [onlineVersion, setOnlineVersion] = useState(null);
  const [fileKey, setFileKey] = useState(0);
  const accepted = item.invitation?.status === "accepted";
  const visibleSubmissions = role === "editor" && !accepted ? [] : item.submissions;
  const current = visibleSubmissions[0];
  const needsUpload = !current || current.status.endsWith("revision_requested") || current.confirmation === "request_revision";
  const canUpload = role === "editor" && accepted && item.status === "initial_editing" && needsUpload;
  const review = role === "author" && item.status === "initial_editing" && current?.status === "pending_author";
  const editorApproval = role === "editor" && accepted && item.status === "initial_editing" && current?.status === "author_approved";
  const confirmation = role === "author" && item.status === "pre_review_confirmation" && current?.status === "eic_approved" && !current.confirmation;
  const submitDecision = async event => {
    event.preventDefault();
    const action = review ? "author-review" : editorApproval ? "editor-approval" : "pre-review-confirmation";
    if (await perform(`/eic/initial-editing/submissions/${current.submission_id}/${action}`, { decision, comments })) {
      setDecision(""); setComments("");
    }
  };
  const upload = async event => {
    event.preventDefault();
    const data = new FormData(); data.append("file", file); data.append("comments", comments);
    if (onlineVersion) data.append("expected_online_version", onlineVersion);
    if (await perform(`/eic/initial-editing/${item.manuscript_id}/submit`, data)) {
      setComments(""); setFile(null); setOnlineVersion(null); setFileKey(key => key + 1);
    }
  };
  return <article className="initial-editing-item">
    {showTitle && <h3>#{item.manuscript_id} {item.title}</h3>}
    <p><strong>Manuscript status:</strong> {readable(item.status)}</p>
    {role === "editor" && item.invitation && <EditorInvitationSummary title={item.title} status={item.invitation.status} abstract={item.invitation_abstract} editor={item.invitation.editor} invitedAt={item.invitation.invited_at} respondedAt={item.invitation.responded_at} stage="Initial editor" />}
    {item.invitation && <p><strong>Initial editor:</strong> {item.invitation.editor} · {readable(item.invitation.status)}</p>}
    <p><strong>{showTitle ? "Next action:" : "Stage guidance:"}</strong> {initialEditingPrompt(item, role, stale)}</p>
    {role === "editor" && item.status === "initial_editor_invited" && item.invitation?.status === "pending" && <div className="initial-editing-buttons">
      <button type="button" disabled={busy} onClick={() => perform(`/eic/initial-editor/invitations/${item.invitation.invitation_id}/respond`, { decision: "accept" })}>Accept invitation</button>
      <button type="button" disabled={busy} onClick={() => perform(`/eic/initial-editor/invitations/${item.invitation.invitation_id}/respond`, { decision: "decline" })}>Decline invitation</button>
    </div>}
    {visibleSubmissions.map(submission => <div className="initial-editing-submission" key={submission.submission_id}>
      <p><strong>Initial-editing document #{submission.submission_id}:</strong> {readable(submission.status)}{submission.confirmation && ` · author confirmation: ${readable(submission.confirmation)}`}</p>
      <p>Editor: {submission.comments}{submission.author_comments && ` · Author: ${submission.author_comments}`}{submission.editor_comments && ` · Editor approval: ${submission.editor_comments}`}{submission.eic_comments && ` · EIC: ${submission.eic_comments}`}</p>
      <button type="button" disabled={busy} onClick={() => download(submission.submission_id)}>Download initial-editing document</button>
    </div>)}
    {canUpload && <OnlineDocumentEditor manuscriptId={item.manuscript_id} token={token} stage="initial" onUseSaved={(selected, version) => { setFile(selected); setOnlineVersion(version); }} onDirtyChange={dirty => onOnlineDirtyChange?.(`initial-${item.manuscript_id}`, dirty)} />}
    {canUpload && <OnlineDocxEditor manuscriptId={item.manuscript_id} token={token} stage="initial" onUseSaved={(selected, version) => { setFile(selected); setOnlineVersion(version); }} onDirtyChange={dirty => onOnlineDirtyChange?.(`docx-initial-${item.manuscript_id}`, dirty)} />}
    {canUpload && <form onSubmit={upload} className="initial-editing-form"><h4>Upload initial-editing document</h4>
      <label>PDF, DOCX, DOC, or UTF-8 TXT file <input key={fileKey} type="file" accept=".pdf,.docx,.doc,.txt,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" required={!file} onChange={e => { setFile(e.target.files[0] || null); setOnlineVersion(null); }} /></label>
      {file?.name === 'online-edit.txt' && <p>Saved online TXT draft selected.</p>}
      {file?.name === 'online-edit.docx' && <p>Saved online DOCX draft selected.</p>}
      <label>Editing comments <textarea required maxLength={5000} value={comments} onChange={e => setComments(e.target.value)} /></label>
      <button disabled={busy || !file}>Submit initial-editing document</button></form>}
    {(review || editorApproval || confirmation) && <form onSubmit={submitDecision} className="initial-editing-form"><h4>{review ? "Review initial editing" : editorApproval ? "Editor approval" : "Confirm pre-review version"}</h4>
      <label>Decision <select required value={decision} onChange={e => setDecision(e.target.value)}><option value="">Choose decision</option>
        <option value={confirmation ? "confirm" : "approve"}>{confirmation ? "Confirm" : "Approve"}</option><option value="request_revision">Request revision</option></select></label>
      <label>Comments <textarea required maxLength={5000} value={comments} onChange={e => setComments(e.target.value)} /></label>
      <button disabled={busy}>Submit {confirmation ? "confirmation" : editorApproval ? "editor approval" : "author review"}</button></form>}
  </article>;
}

export default function InitialEditingPanel({ role, token, onChanged, manuscriptId, onOnlineDirtyChange }) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const load = useCallback(async () => {
    const response = await fetch(`${API_URL}/eic/initial-editing/my`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new Error(`Could not load initial editing (${response.status}).`);
    setItems(await response.json());
  }, [token]);
  useEffect(() => { load().catch(e => setError(e.message)); }, [load]);
  useReturnRefresh(() => load().catch(e => setError(e.message)), busy || dirty);
  const perform = async (path, data) => {
    setBusy(true); setError(""); setMessage("");
    try {
      const isForm = data instanceof FormData;
      const response = await fetch(`${API_URL}${path}`, { method: "POST", headers: { Authorization: `Bearer ${token}`, ...(isForm ? {} : { "Content-Type": "application/json" }) }, body: isForm ? data : JSON.stringify(data) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}).`);
      setMessage("Action completed.");
      setDirty(false);
      try { await load(); await onChanged(); } catch { setError("Action saved, but refresh failed. Return to this view before taking another action."); }
      return true;
    } catch (e) { setError(e.message); return false; } finally { setBusy(false); }
  };
  const download = async submissionId => {
    setError("");
    try {
      const response = await fetch(`${API_URL}/eic/initial-editing/submissions/${submissionId}/download`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Download failed (${response.status}).`); }
      const blob = await response.blob(); const url = URL.createObjectURL(blob);
      const disposition = response.headers.get("content-disposition") || "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || `initial-editing-${submissionId}${(response.headers.get("content-type") || "").includes("wordprocessingml") ? ".docx" : (response.headers.get("content-type") || "").includes("msword") ? ".doc" : (response.headers.get("content-type") || "").startsWith("text/plain") ? ".txt" : ".pdf"}`;
      const link = document.createElement("a"); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(e.message); }
  };
  const visibleItems = manuscriptId == null ? items : items.filter(item => item.manuscript_id === manuscriptId);
  if (!visibleItems.length && !error && !message) return null;
  return <section className="initial-editing-panel" aria-label="Initial editing workflow" onChangeCapture={() => setDirty(true)}><div className="initial-editing-heading"><h2>Initial editing workflow</h2></div>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {!visibleItems.length ? <p>No initial editing items.</p> : visibleItems.map(item => <EditingItem showTitle={manuscriptId == null} key={item.manuscript_id} item={item} role={role} token={token} onOnlineDirtyChange={onOnlineDirtyChange} perform={perform} download={download} busy={busy} stale={Boolean(error)} />)}
  </section>;
}
