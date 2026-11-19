// Presentation only: these messages do not grant access or change workflow state.
export function eicPrompt(overview, stale = false, formatting = null) {
  if (stale || !overview?.manuscript?.status) return {text: 'Workflow information is unavailable or may be stale. Refresh before acting.'};
  const status = overview.manuscript.status;
  if (status === 'submitted') return {text: 'Initial screening is pending. Check current stage actions.'};
  if (status === 'initial_scan_passed') return {text: 'Initial screening passed. Check the initial editor assignment controls.'};
  if (status === 'initial_editor_invited') {
    if (!Array.isArray(overview.invitations) || !overview.invitations.length) return {text:'Initial editor invitation information is unavailable.'};
    const invitation = overview.invitations.at(-1);
    if (invitation.status === 'pending') return {text:'Waiting for the invited initial editor to respond.'};
    if (invitation.status === 'declined') return {text:'The initial editor declined. Review the invitation status before proceeding.'};
    if (invitation.status === 'accepted') return {text:'The initial editor accepted. Waiting for the initial editing workflow.'};
    return {text:'Initial editor invitation status is unavailable.'};
  }
  if (status === 'initial_editing') {
    if (!Array.isArray(overview.submissions)) return {text:'Initial editing information is unavailable.'};
    if (overview.submissions.some(item => item.status === 'editor_approved')) return {text:'An editor-approved initial edit is recorded. Check current stage actions.'};
    return {text:'Initial editing is incomplete. Waiting for the next participant in the editing workflow.'};
  }
  if (status === 'pre_review_confirmation') return {text:'Waiting for the author to confirm the pre-review document.'};
  if (status === 'ready_for_peer_review' || status === 'revised') {
    if (!Number.isInteger(overview.manuscript.review_round) || overview.manuscript.review_round < 1 || !overview.review_progress || typeof overview.review_progress.can_decide !== 'boolean' || !Array.isArray(overview.decisions)) return {text:'Review decision eligibility is unavailable.'};
    if (overview.decisions.some(item => item.review_round === overview.manuscript.review_round)) return {text:'A decision for this review round has already been recorded.'};
    if (overview.review_progress.can_decide) return {text:'Required reviews are complete. Record the editorial decision.', action:true};
    if (typeof overview.review_progress.blocked_reason === 'string' && overview.review_progress.blocked_reason.trim()) return {text:`Decision is not ready: ${overview.review_progress.blocked_reason}`};
    return {text:'Review requirements are not yet complete. Check the review progress below.'};
  }
  if (status === 'revision_required' || status === 'initial_revision_required') return {text:'Waiting for the author to submit the requested revision.'};
  if (status === 'awaiting_author_agreement') return {text:'Waiting for the author to respond to the agreement.'};
  if (status === 'author_agreement_declined') return {text:'The author declined the agreement; final editing is on hold.'};
  if (status === 'final_editing') {
    if (!Array.isArray(overview.final_invitations) || !Array.isArray(overview.final_workflow_submissions)) return {text:'Final editing assignment information is unavailable.'};
    const submission = overview.final_workflow_submissions[0];
    if (submission?.status === 'pending_eic') return {text:'The final edit is awaiting EIC review.'};
    if (submission?.status === 'pending_author') return {text:'Waiting for the author to review the final edit.'};
    if (submission?.status === 'author_approved') return {text:'The author approved the final edit. Review the formatting workflow.'};
    const invitation = overview.final_invitations.at(-1);
    if (!invitation) return {text:'A final editor has not yet been invited.'};
    if (invitation.status === 'pending') return {text:'Waiting for the final editor to respond to the invitation.'};
    if (invitation.status === 'declined') return {text:'The final editor declined the invitation.'};
    if (invitation.status === 'accepted') return {text:'The final editor accepted. Waiting for the final editing workflow.'};
    return {text:'Final editing assignment information is unavailable.'};
  }
  if (status === 'formatting') {
    if (!formatting || formatting.manuscript_id !== overview.manuscript.manuscript_id || formatting.status !== status || !Array.isArray(formatting.invitations) || !Array.isArray(formatting.submissions)) return {text:'Formatting assignment information is unavailable or may be stale.'};
    const latest = formatting.submissions[0];
    if (latest?.status === 'pending_eic') return {text:'The formatted document is awaiting EIC review.'};
    if (latest?.status === 'pending_author') return {text:'Waiting for the author to review the formatted document.'};
    if (latest?.status === 'approved') return {text:'The formatted document has been approved. Check the publication controls.'};
    const active = formatting.invitations.find(item => ['pending','accepted'].includes(item.status));
    if (active?.status === 'pending') return {text:'Waiting for the formatter to respond to the invitation.'};
    if (active?.status === 'accepted') return {text:'Waiting for the assigned formatter to submit or revise the document.'};
    if (formatting.invitations[0]?.status === 'declined') return {text:'The most recent formatting invitation was declined.'};
    if (formatting.invitations.length === 0) return {text:'No formatting invitation is recorded.'};
    return {text:'Formatting assignment information is unavailable or may be stale.'};
  }
  if (status === 'withdrawn') return {text:'This manuscript has been withdrawn; no editorial action can be determined.'};
  if (status === 'accepted') return {text:'This manuscript was accepted through the legacy workflow.'};
  if (status === 'published') return {text:'Publication recorded in the local prototype.'};
  if (status === 'rejected' || status === 'initial_rejected') return {text:'This manuscript was rejected; the workflow has ended.'};
  return {text:'A next action cannot be determined from the available workflow information.'};
}

export function authorPrompt(manuscript, stale = false) {
  if (stale || !manuscript?.status) return 'Manuscript information is unavailable or may be stale.';
  const messages = {
    draft:'Complete your draft and submit it when ready.', submitted:'Your manuscript is awaiting initial editorial screening.',
    initial_revision_required:'Revise and resubmit the manuscript requested at screening.', revision_required:'Your manuscript requires revision. Complete and submit the requested changes.',
    revised:'Your revision was submitted and is awaiting editorial review.', pre_review_confirmation:'Review and confirm the pre-review document in the initial editing workflow.',
    initial_scan_passed:'Waiting for initial editor assignment.', initial_editor_invited:'Waiting for the initial editor to respond.',
    initial_editing:'Initial editing is underway. Check the initial editing workflow for any action assigned to you.',
    ready_for_peer_review:'Your manuscript is in the peer review workflow.', awaiting_author_agreement:'Review and respond to the author agreement.',
    author_agreement_declined:'Your agreement response was declined; contact the editorial team.', final_editing:'Check the final editing workflow for any review assigned to you.',
    formatting:'Check the formatting workflow for any review assigned to you.', accepted:'Your manuscript was accepted through the legacy workflow.',
    published:'Publication is recorded in the local prototype.', rejected:'Your manuscript was rejected.', initial_rejected:'Your manuscript was rejected at screening.', withdrawn:'This manuscript is withdrawn.'
  };
  return messages[manuscript.status] || 'A next action cannot be determined from the available manuscript information.';
}

export function initialEditingPrompt(item, role, stale = false) {
  if (stale || !item || !Array.isArray(item.submissions)) return 'Initial editing information is unavailable or may be stale.';
  const submission = item.submissions[0];
  if (role === 'editor') {
    const invitation = item.invitation?.status;
    if (invitation === 'declined') return 'You declined the initial editor invitation.';
    if (invitation === 'pending' && item.status === 'initial_editor_invited') return 'An initial editor invitation is pending. Current assignment eligibility is unconfirmed.';
    if (invitation !== 'accepted') return 'No current initial editing action can be confirmed.';
    if (item.status === 'ready_for_peer_review') return 'The manuscript is in peer review. Reviewer assignment eligibility is unconfirmed.';
    if (item.status === 'pre_review_confirmation') return 'Waiting for author confirmation of the pre-review document.';
    if (item.status !== 'initial_editing') return 'No current initial editing action can be confirmed.';
    if (!submission || submission.status?.endsWith('revision_requested') || submission.confirmation === 'request_revision') return 'Your initial editor invitation is accepted. Current upload eligibility is unconfirmed.';
    if (submission.status === 'pending_author') return 'Waiting for the author to review the initial edit.';
    if (submission.status === 'author_approved') return 'An author-approved initial edit is recorded. Current review eligibility is unconfirmed.';
    if (submission.status === 'editor_approved') return 'Waiting for the EIC to review the initial edit.';
    return 'Initial editing action cannot be determined from the available information.';
  }
  if (role === 'author' && item.status === 'pre_review_confirmation' && submission?.status === 'eic_approved' && !submission.confirmation) return 'Confirm the EIC-approved pre-review document.';
  if (role === 'author' && item.status === 'initial_editing' && submission?.status === 'pending_author') return 'Review the initial editing document.';
  return 'Check the initial editing workflow for the current status.';
}

export function finalEditingPrompt(item, role, stale = false) {
  if (stale || !item || !Array.isArray(item.submissions)) return 'Final editing information is unavailable or may be stale.';
  const latest = item.submissions[0];
  if (role === 'editor') {
    if (item.status === 'pending') return 'A final editor invitation is pending. Current assignment eligibility is unconfirmed.';
    if (item.status === 'declined') return 'You declined the final editor invitation.';
    if (item.status !== 'accepted') return 'No current final editing assignment can be confirmed.';
    if (item.manuscript_status !== 'final_editing') return 'No final editing action is currently available.';
    if (!latest || ['eic_revision_requested','author_revision_requested'].includes(latest.status)) return 'Your final editor invitation is accepted. Current upload eligibility is unconfirmed.';
    if (latest.status === 'pending_eic') return 'Waiting for the EIC to review the final edit.';
    if (latest.status === 'pending_author') return 'Waiting for the author to review the final edit.';
    if (latest.status === 'author_approved') return 'Final edits were confirmed by the author.';
    return 'Final editing action cannot be determined from the available information.';
  }
  if (role === 'author' && item.manuscript_status === 'final_editing' && latest?.status === 'pending_author') return 'Review and respond to the final editing document.';
  return 'Check the final editing workflow for the current status.';
}

export function formatterPrompt(item, stale = false) {
  if (stale || !item || !Array.isArray(item.invitations) || !Array.isArray(item.submissions)) return 'Formatting information is unavailable or may be stale.';
  const active = item.invitations.find(i => ['pending','accepted'].includes(i.status));
  if (active?.status === 'pending') return 'A formatting invitation is pending. Current assignment eligibility is unconfirmed.';
  if (!active) return item.invitations.some(i => i.status === 'declined') ? 'The formatting invitation was declined.' : 'No active formatting assignment is available.';
  const latest = item.submissions[0];
  if (item.status === 'published') return 'Publication is recorded in the local prototype.';
  if (latest?.status === 'approved') return 'The formatted document has been approved.';
  if (latest?.status === 'pending_author') return 'Waiting for the author to review the formatted document.';
  if (latest?.status === 'pending_eic') return 'Waiting for the EIC to review the formatted document.';
  if (item.status === 'formatting' && (!latest || latest.status?.endsWith('revision_requested'))) return 'Your formatting invitation is accepted. Current submission eligibility is unconfirmed.';
  return 'No current formatting action can be confirmed.';
}

export function reviewerPrompt(assignment, stale = false) {
  if (stale || !assignment) return 'Assignment information is unavailable or may be stale.';
  if (assignment.invitation_status === 'declined') return 'You declined this review invitation.';
  if (assignment.invitation_status === 'pending') return 'A review invitation is pending. Current review-round eligibility is unconfirmed.';
  if (!['accepted','legacy'].includes(assignment.invitation_status)) return 'Review invitation information is unavailable.';
  if (assignment.status === 'completed') return 'Your review is complete. Wait for the editorial team.';
  if (assignment.status === 'assigned' && assignment.review_file_available === true) return 'A review file is available. Current review-round submission eligibility is unconfirmed.';
  if (assignment.status === 'assigned') return 'Review file availability is unconfirmed. Contact the editorial team.';
  return 'No current review action can be determined from this assignment.';
}
