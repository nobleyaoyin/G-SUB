import { useEffect, useState } from 'react';
import { API_URL } from './api';
import { workflowStageLabel } from './workflowStatus';
import { recordedMessage } from './recordedDisplay';
import './ManuscriptTimeline.css';

export function sortActivityEvents(events) {
  return events.map((event, index) => ({event, index, date: Date.parse(event.timestamp)}))
    .sort((a, b) => {
      const aValid = Number.isFinite(a.date), bValid = Number.isFinite(b.date);
      if (aValid !== bValid) return aValid ? -1 : 1;
      if (aValid && a.date !== b.date) return b.date - a.date;
      const keyOrder = String(a.event.key ?? '').localeCompare(String(b.event.key ?? ''));
      return keyOrder || a.index - b.index;
    }).map(({event}) => event);
}

// The server returns a role-filtered projection, never comment bodies.
export default function ManuscriptTimeline({ manuscriptId, token, revision = 0 }) {
  const [result, setResult] = useState({});
  const [open, setOpen] = useState(false);
  const scope = `${token}:${manuscriptId}`;
  useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    setResult({ scope, loading: true });
    fetch(`${API_URL}/manuscripts/${manuscriptId}/timeline`, {
      headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error('Timeline unavailable');
      const data = await response.json();
      if (data?.manuscript_id !== manuscriptId || !Array.isArray(data.events)) throw new Error('Timeline unavailable');
      if (!controller.signal.aborted) setResult({ scope, data });
    }).catch(() => { if (!controller.signal.aborted) setResult({ scope, error: true }); });
    return () => controller.abort();
  }, [scope, manuscriptId, token, revision, open]);
  const state = result.scope === scope ? result : { loading: true };
  return <details onToggle={event => setOpen(event.currentTarget.open)} className="workspace-context manuscript-activity-timeline" aria-label="Manuscript activity timeline">
    <summary>Activity Timeline</summary>
    {state.loading && <p role="status">Loading activity…</p>}
    {state.error && <div role="alert">Activity history is unavailable.</div>}
    {state.data && <div>
      {state.data.events.length === 0 ? <p>No recorded activity is available.</p> : <ol>
        {sortActivityEvents(state.data.events).map((event, index) => <li key={event.key} value={index + 1}>
          <strong>{recordedMessage(event.description)}</strong> · <span>{workflowStageLabel(event.stage)}</span>{event.review_round != null && ` · Round ${event.review_round}`}
          {' · '}<time dateTime={event.timestamp}>{Number.isFinite(Date.parse(event.timestamp)) ? new Date(event.timestamp).toLocaleString() : 'Date unavailable'}</time>
        </li>)}
      </ol>}
    </div>}
  </details>;
}
