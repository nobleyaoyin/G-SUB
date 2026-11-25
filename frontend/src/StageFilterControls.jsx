import './StageFilterControls.css';
import {WORKFLOW_STAGES, compareWorkflowStatuses, matchesWorkflowFilter, workflowStatusLabel, workflowStageLabel} from './workflowStatus';

const proofLabels = {
  formatter_invited: 'Formatter invitation pending',
  formatter_declined: 'Formatter invitation declined',
  awaiting_formatted_proof: 'Awaiting formatted proof',
  pending_author: 'Awaiting author proof review',
  pending_eic: 'Awaiting EIC proof review',
  approved: 'Proof approved',
  author_revision_requested: 'Author requested proof revision',
  eic_revision_requested: 'EIC requested proof revision',
};
export function StageFilterClear({onClear}) {
  return <button type="button" className="stage-filter-clear" onClick={onClear}>Clear filters</button>;
}
// Filter values remain presentation-only; status values are never written back.
export default function StageFilterControls({value, onChange, items, onClear}) {
  const [stageFilter, sub] = (value || '').split('|status:');
  const stage = stageFilter?.startsWith('stage:') ? stageFilter.slice(6) : '';
  const stageItems = stage ? items.filter(item => matchesWorkflowFilter(item, `stage:${stage}`)) : [];
  const statuses = stage ? [...new Set(stageItems
    .map(item => item.status).filter(status => typeof status === 'string' && status && status !== 'formatting'))].sort(compareWorkflowStatuses) : [];
  const proofs = [...new Set(stageItems.map(item => item.workflow_substage).filter(value => Object.hasOwn(proofLabels, value)))];
  const proofUnavailable = ['Formatting', 'Proofing'].includes(stage) && stageItems.some(item => !item.workflow_substage);
  return <>
    <label>Main stage <select className="stage-filter-select" value={stage} onChange={event => onChange(event.target.value ? `stage:${event.target.value}` : '')}>
      <option value="">All stages</option>{WORKFLOW_STAGES.map(([name]) => <option key={name} value={name}>{workflowStageLabel(name)}</option>)}
    </select></label>
    <label>Sub-stage <select className="stage-filter-select" value={sub || ''} disabled={!stage} onChange={event => onChange(`stage:${stage}${event.target.value ? `|status:${event.target.value}` : ''}`)}>
      <option value="">All sub-stages</option>{statuses.map(status => <option key={status} value={status}>{workflowStatusLabel(status)}</option>)}{proofs.map(proof => <option key={proof} value={`proof:${proof}`}>{proofLabels[proof]}</option>)}
    </select></label>
    {proofUnavailable && <small>Some proof review sub-stages are unavailable in this list.</small>}
    {onClear && <StageFilterClear onClear={onClear} />}
  </>;
}
