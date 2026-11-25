import {workflowStatusLabel} from './workflowStatus';
import './StatusBadge.css';

const tones = {
  draft: 'neutral', submitted: 'active', initial_scan_passed: 'active',
  initial_editor_invited: 'active', initial_editing: 'active',
  ready_for_peer_review: 'active', final_editing: 'active', formatting: 'active',
  revised: 'active', assigned: 'active', pending: 'active',
  revision_required: 'attention', initial_revision_required: 'attention',
  accepted: 'positive', completed: 'positive', published: 'positive',
  rejected: 'negative', initial_rejected: 'negative', declined: 'negative',
};

export default function StatusBadge({status}) {
  return <span className="status-badge workflow-status-badge" data-tone={tones[status] || 'neutral'}>{workflowStatusLabel(status)}</span>;
}
