import { useEffect, useRef, useState } from "react";
import { API_URL, submitAction, actionFailureMessage } from "./api";

export default function OnlineDocumentEditor({ manuscriptId, token, onChanged, onDirtyChange, stage, onUseSaved, onVersion }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [note, setNote] = useState('');
  const onVersionRef = useRef(onVersion);
  useEffect(() => { onVersionRef.current = onVersion; }, [onVersion]);
  const endpoint = stage ? `/eic/manuscripts/${manuscriptId}/online-text/${stage}` : `/manuscripts/${manuscriptId}/online-text`;
  const dirty = data !== null && text !== data.content;
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    fetch(`${API_URL}${endpoint}`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async response => { const value = await response.json(); if (!response.ok) throw new Error(value.detail || 'Document unavailable'); return value; })
      .then(value => { if (!controller.signal.aborted) { setData(value); setText(value.content); setUncertain(false); onVersionRef.current?.(value.history.some(item => item.is_current) ? value.version : null); } })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [open, endpoint, token]);
  useEffect(() => {
    if (!dirty) return;
    const warn = event => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const close = () => {
    if (dirty && !window.confirm('Discard unsaved document edits?')) return;
    setOpen(false); setData(null); setError(''); setMessage(''); onDirtyChange?.(false);
  };
  const save = async () => {
    if (!data || busy || uncertain || !dirty) return;
    setBusy(true); setError(''); setMessage('');
    try {
      await submitAction(`${API_URL}${endpoint}`, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ content: text, expected_version: data.version, change_note: note || null }) });
      const response = await fetch(`${API_URL}${endpoint}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error('Version saved, but the document could not be reloaded. Close and reopen it.');
      const value = await response.json(); setData(value); setText(value.content); setNote(''); onVersion?.(value.version); onDirtyChange?.(false); setMessage('Version saved. Submission and approval are separate.');
      await onChanged?.();
    } catch (e) { setError(actionFailureMessage(e)); setUncertain(true); }
    finally { setBusy(false); }
  };
  const versionPath = item => stage ? `${endpoint}/${encodeURIComponent(item.filename)}` : `${endpoint}/versions/${encodeURIComponent(item.id)}`;
  const download = async item => {
    try {
      const response = await fetch(`${API_URL}${versionPath(item)}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error('Version download unavailable');
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a');
      link.href = url; link.download = item.filename; link.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(e.message); }
  };
  const reopen = async item => {
    if (dirty && !window.confirm('Discard unsaved document edits?')) return;
    setBusy(true); setError('');
    try {
      const response = await fetch(`${API_URL}${versionPath(item)}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error('Version unavailable');
      const content = await response.text();
      setText(content); onDirtyChange?.(content !== data.content);
      setMessage('Historical draft opened. Save to create a new version.');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const useSaved = async () => {
    if (!data || dirty || busy || uncertain) return;
    setBusy(true); setError('');
    try {
      const response = await fetch(`${API_URL}${endpoint}`, {headers:{Authorization:`Bearer ${token}`}});
      if (!response.ok) throw new Error('Saved draft is unavailable; reopen the editor.');
      const latest = await response.json();
      if (latest.version !== data.version) throw new Error('Draft changed; reopen the editor before selecting it.');
      onUseSaved?.(new File([latest.content], 'online-edit.txt', {type:'text/plain'}), latest.version);
      setMessage('Saved draft selected for the submission form. Submit separately when ready.');
    } catch (e) { setError(e.message); setUncertain(true); }
    finally { setBusy(false); }
  };
  if (!open) return <button type="button" onClick={() => { setOpen(true); setError(''); }}>Edit document (TXT)</button>;
  return <section data-online-editor aria-label="Online manuscript editor"><h4>Online document editor</h4><p>UTF-8 TXT only. Saving creates a draft file; it does not submit or approve it.</p>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {data && <><label>Document text<textarea value={text} onChange={event => { setText(event.target.value); onDirtyChange?.(event.target.value !== data.content); }} rows={14} /></label>
      <label>Change note (optional)<input value={note} maxLength={500} onChange={event => setNote(event.target.value)} /></label>
      <button type="button" onClick={save} disabled={busy || !dirty || uncertain}>Save Version</button>
      {onUseSaved && data.history.length > 0 && <button type="button" onClick={useSaved} disabled={busy || dirty || uncertain}>Use saved draft</button>}
      <details><summary>Version History</summary><p>Saved drafts; submission and approvals are separate.</p>{data.history.length ? <ol>{data.history.map((item, index) => (
          <li key={item.id ?? `${item.filename ?? "version"}-${item.number ?? index}`}>Version {item.number} · {item.saved_at} · {item.editor}{item.is_current ? ' · latest' : ''}{item.change_note ? ` · ${item.change_note}` : ''} <button type="button" disabled={busy} onClick={() => reopen(item)}>Open version</button> <button type="button" onClick={() => download(item)}>Download</button></li>))}</ol> : <p>No online versions saved yet.</p>}</details>
    </>}
    <button type="button" onClick={close} disabled={busy}>Cancel</button>
  </section>;
}
