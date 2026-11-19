import useReturnRefresh from "./useReturnRefresh";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useState } from "react";
import { finalEditingPrompt } from "./participantPrompts";
import EditorInvitationSummary from "./EditorInvitationSummary";
import { API_URL } from "./api";
import "./InitialEditingPanel.css";
import OnlineDocumentEditor from "./OnlineDocumentEditor";
import OnlineDocxEditor from "./OnlineDocxEditor";

const readable = value => (value || "unknown").replaceAll("_", " ");

function FinalItem({ item, role, busy, perform, download, token, onOnlineDirtyChange, showTitle, stale }) {
  const [comments, setComments] = useState("");
  const [decision, setDecision] = useState("");
  const [file, setFile] = useState(null);
  const [onlineVersion, setOnlineVersion] = useState(null);
  const [fileKey, setFileKey] = useState(0);
  const visibleSubmissions = role === "editor" && item.status !== "accepted" ? [] : item.submissions;
  const latest = visibleSubmissions[0];
  const canUpload = role === "editor" && item.status === "accepted" && item.manuscript_status === "final_editing" && (!latest || ["eic_revision_requested", "author_revision_requested"].includes(latest.status));
  const upload = async e => {
    e.preventDefault(); const data = new FormData(); data.append("file", file); data.append("comments", comments);
    if (onlineVersion) data.append("expected_online_version", onlineVersion);
    if (await perform(`/eic/final-editing/${item.manuscript_id}/submit`, data)) { setComments(""); setFile(null); setOnlineVersion(null); setFileKey(x => x + 1); }
  };
  const confirm = async e => {
    e.preventDefault(); if (await perform(`/final-workflow/submissions/${latest.submission_id}/author-review`, { decision, comments })) { setComments(""); setDecision(""); }
  };

  return <article className="initial-editing-item">{showTitle && <h3>#{item.manuscript_id} {item.title}</h3>}<p>Manuscript status: {readable(item.manuscript_status)}</p>
    {role === "editor" && <EditorInvitationSummary title={item.title} status={item.status} abstract={item.invitation_abstract} editor={item.editor} invitedAt={item.invited_at} respondedAt={item.responded_at} stage="Final editor" />}
    {role === "editor" && <p>Final editor invitation: {readable(item.status)}</p>}<p><strong>{showTitle ? "Next action:" : "Stage guidance:"}</strong> {finalEditingPrompt(item, role, stale)}</p>
    {role === "editor" && item.status === "pending" && <div><button type="button" disabled={busy} onClick={() => perform(`/final-workflow/invitations/${item.invitation_id}/respond`, { decision: "accept" })}>Accept final editor invitation</button> <button type="button" disabled={busy} onClick={() => perform(`/final-workflow/invitations/${item.invitation_id}/respond`, { decision: "decline" })}>Decline final editor invitation</button></div>}
    {visibleSubmissions.map(s => <div key={s.submission_id} className="initial-editing-submission"><p>Final edit #{s.submission_id} · {readable(s.status)} — {s.comments}</p>{s.eic_comments && <p>EIC: {s.eic_comments}</p>}{s.author_comments && <p>Author: {s.author_comments}</p>}<button type="button" disabled={busy} onClick={() => download(s.submission_id)}>Download final editing document</button></div>)}
    {canUpload && <OnlineDocumentEditor manuscriptId={item.manuscript_id} token={token} stage="final" onUseSaved={(selected, version) => { setFile(selected); setOnlineVersion(version); }} onDirtyChange={dirty => onOnlineDirtyChange?.(`final-${item.manuscript_id}`, dirty)} />}
    {canUpload && <OnlineDocxEditor manuscriptId={item.manuscript_id} token={token} stage="final" onUseSaved={(selected, version) => { setFile(selected); setOnlineVersion(version); }} onDirtyChange={dirty => onOnlineDirtyChange?.(`docx-final-${item.manuscript_id}`, dirty)} />}
    {canUpload && <form className="initial-editing-form" onSubmit={upload}><h4>Upload final editing document</h4><label>PDF, DOCX, DOC, or UTF-8 TXT file <input key={fileKey} type="file" accept=".pdf,.docx,.doc,.txt,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" required={!file} onChange={e => { setFile(e.target.files[0] || null); setOnlineVersion(null); }} /></label>{file?.name === 'online-edit.txt' && <p>Saved online TXT draft selected.</p>}{file?.name === 'online-edit.docx' && <p>Saved online DOCX draft selected.</p>}<label>Editing comments <textarea required maxLength={5000} value={comments} onChange={e => setComments(e.target.value)} /></label><button disabled={busy || !file}>Submit final editing document</button></form>}
    {role === "author" && item.manuscript_status === "final_editing" && latest?.status === "pending_author" && <form className="initial-editing-form" onSubmit={confirm}><h4>Review final edits</h4><label>Decision <select required value={decision} onChange={e => setDecision(e.target.value)}><option value="">Choose</option><option value="approve">Approve final edits</option><option value="request_revision">Request corrections</option></select></label><label>Comments <textarea required maxLength={5000} value={comments} onChange={e => setComments(e.target.value)} /></label><button disabled={busy}>Submit final edit confirmation</button></form>}
  </article>;
}

const FinalEditingPanel = forwardRef(function FinalEditingPanel({ role, token, onChanged, manuscriptId, onOnlineDirtyChange }, ref) {
  const [items, setItems] = useState([]); const [error, setError] = useState(""); const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const load = useCallback(async () => { const response = await fetch(`${API_URL}/final-workflow/my`, { headers: { Authorization: `Bearer ${token}` } }); if (!response.ok) throw new Error(`Could not load final editing (${response.status}).`); setItems(await response.json()); }, [token]);
  useImperativeHandle(ref, () => ({ refresh: load }), [load]);
  useEffect(() => { load().catch(e => setError(e.message)); }, [load]);
  useReturnRefresh(() => load().catch(e => setError(e.message)), busy || dirty);
  const perform = async (path, data) => {
    setBusy(true); setError(""); setMessage("");
    try { const form = data instanceof FormData; const response = await fetch(`${API_URL}${path}`, { method: "POST", headers: { Authorization: `Bearer ${token}`, ...(form ? {} : { "Content-Type": "application/json" }) }, body: form ? data : JSON.stringify(data) }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}).`); setMessage("Action completed."); setDirty(false); try { await load(); await onChanged(); } catch { setError("Action saved, but the latest state is unavailable. Return to this view to check it."); } return true; } catch (e) { setError(e.message); return false; } finally { setBusy(false); }
  };
  const download = async id => { try { const response = await fetch(`${API_URL}/eic/final-editing/submissions/${id}/download`, { headers: { Authorization: `Bearer ${token}` } }); if (!response.ok) throw new Error("Final edit is unavailable."); const blob = await response.blob(); const url = URL.createObjectURL(blob); const disposition = response.headers.get("content-disposition") || ""; const a = document.createElement("a"); a.href = url; a.download = disposition.match(/filename="?([^";]+)"?/i)?.[1] || `final-edit-${id}${(response.headers.get("content-type") || "").startsWith("text/plain") ? ".txt" : (response.headers.get("content-type") || "").includes("wordprocessingml") ? ".docx" : (response.headers.get("content-type") || "").includes("msword") ? ".doc" : ".pdf"}`; a.click(); URL.revokeObjectURL(url); } catch (e) { setError(e.message); } };
  const visibleItems = manuscriptId == null ? items : items.filter(item => item.manuscript_id === manuscriptId);
  if (!visibleItems.length && !error && !message) return null;
  return <section className="initial-editing-panel" aria-label="Final editing workflow" onChangeCapture={() => setDirty(true)}><div className="initial-editing-heading"><h2>Final editing workflow</h2></div>{error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}{visibleItems.length ? visibleItems.map(item => <FinalItem showTitle={manuscriptId == null} key={item.invitation_id || item.manuscript_id} item={item} role={role} token={token} onOnlineDirtyChange={onOnlineDirtyChange} busy={busy} perform={perform} download={download} stale={Boolean(error)} />) : <p>No final editing items.</p>}</section>;
});

export default FinalEditingPanel;
