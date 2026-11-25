// Presentation order follows the existing server progress mapping. Unknown
// states remain visible after known states and are never assigned a new status.
const orderedStatuses = [
  'draft', 'submitted', 'initial_revision_required', 'initial_rejected',
  'initial_scan_passed', 'initial_editor_invited', 'initial_editing', 'pre_review_confirmation',
  'ready_for_peer_review', 'revision_required', 'revised',
  'accepted', 'rejected', 'awaiting_author_agreement', 'author_agreement_declined',
  'final_editing', 'formatting', 'published',
];
const order = new Map(orderedStatuses.map((status, index) => [status, index]));
export function workflowStatusLabel(status) {
  if (status === 'ready_for_peer_review') return 'Currently in review';
  if (typeof status !== 'string' || !status.trim()) return 'Status unavailable';
  const text = status.replaceAll('_', ' ').trim()
    .replace(/\bg[ -]sub\b/gi, 'G-SUB')
    .replace(/\b(eic|pdf|docx|doc|txt|api|ai)\b/gi, word => word.toUpperCase());
  return text.charAt(0).toLocaleUpperCase() + text.slice(1);
}
// Stage keys are also used by navigation and filtering; format only for display.
export function workflowStageLabel(stage) {
  const labels = {'Initial Screening':'Initial screening', 'Initial Editing':'Initial editing', 'Peer Review':'Peer review', 'EIC Decision':'EIC decision', 'Author Agreement':'Author agreement', 'Final Editing':'Final editing'};
  return labels[stage] || workflowStatusLabel(stage);
}
export function workflowMilestoneLabel(name) {
  const labels = {'Editor Invitation':'Editor invitation', 'Editor Submission':'Editor submission', 'Author Approval':'Author approval', 'Editor Approval':'Editor approval', 'EIC Approval':'EIC approval', 'Pre-review Author Confirmation':'Pre-review author confirmation'};
  return labels[name] || name;
}
export function compareWorkflowStatuses(a, b) {
  const difference = (order.get(a) ?? orderedStatuses.length) - (order.get(b) ?? orderedStatuses.length);
  return difference || String(a).localeCompare(String(b));
}

// Only statuses whose main stage follows directly from the progress API are
// mapped here. 'formatting' is intentionally ambiguous without proof evidence.
export const WORKFLOW_STAGES = [
  ['Submission', ['draft']],
  ['Initial Screening', ['submitted', 'initial_revision_required', 'initial_rejected']],
  ['Initial Editing', ['initial_scan_passed', 'initial_editor_invited', 'initial_editing', 'pre_review_confirmation']],
  ['Peer Review', ['ready_for_peer_review', 'revision_required', 'revised']],
  ['EIC Decision', ['accepted', 'rejected']],
  ['Author Agreement', ['awaiting_author_agreement', 'author_agreement_declined']],
  ['Final Editing', ['final_editing']],
  ['Formatting', []], ['Proofing', []], ['Publication', ['published']],
];
const stageByStatus = new Map(WORKFLOW_STAGES.flatMap(([stage, statuses]) => statuses.map(status => [status, stage])));
export function statusMainStage(status) { return stageByStatus.get(status) || null; }
export function matchesWorkflowFilter(item, filter) {
  if (!filter || filter === 'all') return true;
  if (filter.startsWith('stage:')) {
    const [stageName, substage] = filter.slice(6).split('|status:');
    const stage = Object.hasOwn(item || {}, 'workflow_stage') ? item.workflow_stage : statusMainStage(item?.status);
    return stage === stageName && (!substage || (substage.startsWith('proof:')
      ? item?.workflow_substage === substage.slice(6) : item?.status === substage));
  }
  return item?.status === filter;
}
