// Display only fields supplied by the authorized invitation projection.
function recordedTime(value) {
  if (typeof value !== 'string' || !value.trim()) return 'Unavailable';
  const text = value.trim();
  if (!/(?:Z|[+-]\d\d:\d\d)$/i.test(text)) return `${text} (timezone not recorded)`;
  const date = new Date(text);
  return Number.isNaN(date.valueOf()) ? 'Unavailable' : date.toISOString();
}

export default function EditorInvitationSummary({title, status, stage, abstract, editor, invitedAt, respondedAt}) {
  return <details className="editor-invitation-summary">
    <summary>{stage} invitation information</summary>
    <p><strong>Manuscript:</strong> {typeof title === 'string' && title.trim() ? title : 'Title unavailable'} <small>(invitation record)</small></p>
    <p><strong>Invitation type:</strong> {stage}</p>
    <p><strong>Invited editor:</strong> {typeof editor === 'string' && editor.trim() ? editor : 'Unavailable'}</p>
    <p><strong>Invitation status:</strong> {typeof status === 'string' && status ? status.replaceAll('_', ' ') : 'Unavailable'}</p>
    <p><strong>Invited:</strong> {recordedTime(invitedAt)} · <strong>Responded:</strong> {recordedTime(respondedAt)}</p>
    {status === 'accepted' && typeof abstract === 'string' && abstract.trim() ? <p><strong>Abstract (author-provided):</strong> {abstract}</p> : <p>Abstract is unavailable in this invitation preview.</p>}
    <p>Subject, keywords, verified word and table counts, and document excerpt are unavailable in this invitation preview.</p>
    <p>Editing history and document access depend on the existing assignment authorization.</p>
  </details>;
}
