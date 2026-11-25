// Classify only records returned by the current editor's assignment endpoints.
// Categories are mutually exclusive; unknown or inconsistent data stays unknown.
export function assignmentStatistics(items, kind, userId) {
  if (!Array.isArray(items) || !['initial', 'final'].includes(kind)) return null;
  const validStatuses = new Set(['pending', 'accepted', 'declined', 'revoked']);
  if (items.some(item => !validStatuses.has(kind === 'initial' ? item?.invitation?.status : item?.status))) return null;
  const active = items.filter(item => ['pending', 'accepted'].includes(kind === 'initial' ? item?.invitation?.status : item?.status));
  if (kind === 'final' && active.length && !Number.isSafeInteger(userId)) return null;
  const ids = active.map(item => item?.manuscript_id);
  if (ids.some(id => !Number.isSafeInteger(id)) || new Set(ids).size !== ids.length) return null;
  const counts = {assigned: active.length, invitation: 0, work: 0, submitted: 0, completed: 0, unknown: 0};
  for (const item of active) {
    const invitation = kind === 'initial' ? item.invitation : item;
    if (invitation.status === 'pending') { counts.invitation++; continue; }
    if (!Array.isArray(item.submissions)) { counts.unknown++; continue; }
    if (kind === 'final' && (!Number.isSafeInteger(item.invitation_id) || item.submissions.some(s => s.invitation_id === item.invitation_id && s.editor_id !== userId))) { counts.unknown++; continue; }
    const own = kind === 'initial' ? item.submissions : item.submissions.filter(s => s.invitation_id === item.invitation_id && s.editor_id === userId);
    const latest = own[0];
    if (!latest) { counts.work++; continue; }
    const status = latest.status;
    if (kind === 'initial' && status === 'eic_approved' && latest.confirmation === 'confirm') { counts.completed++; continue; }
    if (kind === 'final' && status === 'author_approved') { counts.completed++; continue; }
    if (typeof status === 'string' && (status.endsWith('revision_requested') || latest.confirmation === 'request_revision')) { counts.work++; continue; }
    const waiting = kind === 'initial' ? ['pending_author','author_approved','editor_approved','eic_approved'] : ['pending_eic','pending_author'];
    if (waiting.includes(status)) { counts.submitted++; continue; }
    counts.unknown++;
  }
  return counts;
}
