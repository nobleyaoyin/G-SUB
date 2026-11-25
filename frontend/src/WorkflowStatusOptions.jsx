import {WORKFLOW_STAGES, statusMainStage, workflowStatusLabel, workflowStageLabel} from './workflowStatus';

// Only show recorded status values; do not infer Formatting versus Proofing.
export default function WorkflowStatusOptions({items}) {
  const statuses = [...new Set(items.map(item => item?.status).filter(status => typeof status === 'string' && status))];
  const known = new Set(WORKFLOW_STAGES.flatMap(([, values]) => values));
  const other = statuses.filter(status => !known.has(status)).sort();
  return <>
    <optgroup label="Main stages">{WORKFLOW_STAGES.map(([stage]) =>
      <option key={stage} value={`stage:${stage}`}>{workflowStageLabel(stage)}</option>)}</optgroup>
    {WORKFLOW_STAGES.map(([stage, values]) => {
      const present = values.filter(value => statuses.includes(value) && statusMainStage(value) === stage);
      return present.length ? <optgroup key={stage} label={`${workflowStageLabel(stage)} statuses`}>{present.map(value => <option key={value} value={value}>{workflowStatusLabel(value)}</option>)}</optgroup> : null;
    })}
    {other.length > 0 && <optgroup label="Other or stage unavailable">{other.map(value => <option key={value} value={value}>{value === 'formatting' ? 'Formatting / proofing — stage unavailable' : workflowStatusLabel(value)}</option>)}</optgroup>}
  </>;
}
