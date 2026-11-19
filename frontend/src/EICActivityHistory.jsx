// Existing EIC overview records only. No comment text or reviewer identity.
const label = value => typeof value === 'string' && value ? value.replaceAll('_', ' ') : 'unavailable';
const date = value => {
  const ms = value ? Date.parse(value) : NaN;
  return Number.isFinite(ms) ? ms : null;
};

export function eicActivity(overview, formatting = null, distribution = null) {
  const events = [];
  const ids = new Set();
  const add = (kind, id, timestamp, text, download) => {
    const key = `${kind}:${id}`;
    if (ids.has(key)) return;
    ids.add(key);
    events.push({key, timestamp, text, download});
  };
  const each = (name, fn) => (Array.isArray(overview[name]) ? overview[name] : []).forEach(fn);
  if (overview.manuscript?.created_at) add('manuscript', overview.manuscript.manuscript_id, overview.manuscript.created_at, 'Manuscript created');
  each('scans', (s,i) => add('scan', s.scan_id ?? i, s.created_at, `Initial screening: ${label(s.decision)}`));
  each('invitations', (v,i) => {
    add('initial-invitation', v.invitation_id ?? i, v.invited_at, `Initial editor invitation #${v.invitation_id ?? 'unavailable'} · Editor: ${v.editor || 'unavailable'} · Status: ${label(v.status)}`);
    if (v.responded_at && ['accepted','declined'].includes(v.status)) add('initial-response', v.invitation_id ?? i, v.responded_at, `Initial editor invitation ${label(v.status)}`);
  });
  each('submissions', (v,i) => add('initial-submission', v.submission_id ?? i, v.created_at, `Initial editing submission #${v.submission_id ?? 'unavailable'} · Editor: ${v.editor || 'unavailable'} · Status: ${label(v.status)}`, Number.isInteger(v.submission_id) ? `/eic/initial-editing/submissions/${v.submission_id}/download` : null));
  each('confirmations', (v,i) => add('confirmation', v.confirmation_id ?? i, v.confirmed_at, `Author confirmation for submission #${v.submission_id ?? 'unavailable'}: ${label(v.decision)}`));
  each('assignments', (v,i) => {
    add('assignment', v.assignment_id ?? i, null, `Reviewer assignment #${v.assignment_id ?? 'unavailable'} · Round ${v.review_round ?? 'unavailable'} · Invitation: ${label(v.invitation_status)} · Assignment: ${label(v.status)} · Assigned by: ${v.assigned_by || 'unavailable'}`);
    if (v.review) add('review', v.assignment_id ?? i, v.review.submitted_at, `Review submitted · Round ${v.review_round ?? 'unavailable'}`);
  });
  each('decisions', (v,i) => add('decision', v.decision_id ?? i, v.decided_at, `EIC decision · Round ${v.review_round ?? 'unavailable'}: ${label(v.decision)}`));
  if (overview.author_agreement) add('agreement', 'current', overview.author_agreement.responded_at, `Author agreement · Version: ${overview.author_agreement.agreement_version || 'unavailable'} · Current status: ${label(overview.author_agreement.status)}`);
  each('final_invitations', (v,i) => {
    add('final-invitation', v.invitation_id ?? i, v.invited_at, `Final editor invitation #${v.invitation_id ?? 'unavailable'} · Editor: ${v.editor || 'unavailable'} · Status: ${label(v.status)}`);
    if (v.responded_at && ['accepted','declined'].includes(v.status)) add('final-response', v.invitation_id ?? i, v.responded_at, `Final editor invitation ${label(v.status)}`);
  });
  each('final_submissions', (v,i) => add('final-submission', v.submission_id ?? i, v.created_at, `Final editing submission #${v.submission_id ?? 'unavailable'} · Editor: ${v.editor || 'unavailable'} · Status: ${label(v.status)}`, Number.isInteger(v.submission_id) ? `/eic/final-editing/submissions/${v.submission_id}/download` : null));
  if (formatting?.manuscript_id === overview.manuscript?.manuscript_id) {
    (Array.isArray(formatting.submissions) ? formatting.submissions : []).forEach((v,i) => add('formatting-submission', v.submission_id ?? i, v.created_at, `Formatting submission #${v.submission_id ?? 'unavailable'} · Status: ${label(v.status)}`));
    if (formatting.publication?.published_at) add('publication', formatting.publication.submission_id ?? 'unknown', formatting.publication.published_at, `Publication recorded · Formatting submission #${formatting.publication.submission_id ?? 'unavailable'}`);
  }
  (Array.isArray(distribution) ? distribution : []).forEach(v => {
    if (typeof v.grant_id !== 'string' || !v.grant_id) return;
    if (v.created_at) add('distribution', v.grant_id, v.created_at, `Document access granted · Version ${v.version ?? 'unavailable'} · ${label(v.invitation_kind)} editor assignment #${v.invitation_id ?? 'unavailable'}`);
    if (v.revoked_at) add('revocation', v.grant_id, v.revoked_at, `Document access revoked · Version ${v.version ?? 'unavailable'}`);
  });
  return events.sort((a,b) => {
    const at=date(a.timestamp), bt=date(b.timestamp);
    if (at === null && bt !== null) return 1;
    if (bt === null && at !== null) return -1;
    if (at !== bt) return bt - at;
    return a.key.localeCompare(b.key, 'en');
  });
}

export default function EICActivityHistory({overview, formatting, distribution, onDownload}) {
  const events=eicActivity(overview, formatting, distribution);
  const incomplete=['scans','invitations','submissions','confirmations','assignments','decisions','final_invitations','final_submissions'].some(key => !Array.isArray(overview[key]));
  return <details className="eic-history-collapsible"><summary>Activity History<span> / Timeline</span> <span className="eic-history-count">{events.length} records</span></summary>
    <div className="eic-history-content"><p>Newest recorded dates first; undated records follow. Statuses reflect the current record.</p>
      {!formatting && <p>Formatting and publication history is not loaded in this view.</p>}
      {!Array.isArray(distribution) && <p>Distribution history is unavailable in this view.</p>}
      {incomplete && <p>Some activity records are unavailable.</p>}
      {!events.length ? <p>No activity records are available.</p> : <ol>{events.map(event => <li className="eic-history-item" key={event.key}>
        <span>{event.text}</span>{date(event.timestamp) === null ? <small>Date unavailable</small> : <time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleString()}</time>}
        {event.download && <button type="button" onClick={() => onDownload(event.download)}>Download {event.key.startsWith('initial-') ? 'initial' : 'final'} editing document</button>}
      </li>)}</ol>}
    </div>
  </details>;
}
