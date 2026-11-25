// Invitation endpoints return only invitations addressed to the authenticated editor.
// Pending invitations are not general manuscript access and must use an invitation-only workspace.
export function pendingEditorInvitations(initialItems, finalItems) {
  const pending = new Map();
  const add = (item, kind, status) => {
    if (!Number.isInteger(item?.manuscript_id) || item.manuscript_id <= 0 || !status || status === 'draft') return;
    const id = item.manuscript_id;
    const existing = pending.get(id);
    if (existing) { if (!existing.invitationKinds.includes(kind)) existing.invitationKinds.push(kind); return; }
    pending.set(id, {
      manuscript_id: id,
      title: typeof item.title === 'string' ? item.title : '',
      status,
      invitationOnly: true,
      invitationKinds: [kind],
    });
  };
  for (const item of initialItems) if (item?.invitation?.status === 'pending') add(item, 'initial', item.status);
  for (const item of finalItems) if (item?.status === 'pending') add(item, 'final', item.manuscript_status);
  return [...pending.values()];
}
