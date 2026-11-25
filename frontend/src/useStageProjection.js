import {createElement, useEffect, useState} from 'react';
import {API_URL} from './api';
import {WORKFLOW_STAGES} from './workflowStatus';

// Use the existing role-authorized progress endpoint only where list status
// cannot identify the current stage. Unknown or stale results fail closed.
export default function useStageProjection(items, token, filter, reviewer = false) {
  const active = typeof filter === 'string' && filter.startsWith('stage:');
  const mainFilter = typeof filter === 'string' ? filter.split('|status:')[0] : '';
  const needsProof = mainFilter === 'stage:Formatting' || mainFilter === 'stage:Proofing';
  const ambiguous = active ? items.filter(item => reviewer || (needsProof && item.status === 'formatting')) : [];
  const requested = ambiguous.filter(item => Number.isSafeInteger(item.manuscript_id));
  const signature = JSON.stringify([...new Map(requested.map(item => [item.manuscript_id, [item.manuscript_id, item.status]])).values()]);
  const [result, setResult] = useState(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    const refresh = () => { if (document.visibilityState === 'visible') setRevision(value => value + 1); };
    window.addEventListener('focus', refresh);
    return () => window.removeEventListener('focus', refresh);
  }, [active]);
  useEffect(() => {
    if (!active || !token) { setResult(null); return undefined; }
    const controller = new AbortController();
    const work = JSON.parse(signature);
    let cursor = 0;
    const stages = {};
    async function worker() {
      while (cursor < work.length && !controller.signal.aborted) {
        const [id, expected] = work[cursor++];
        try {
          const response = await fetch(`${API_URL}/manuscripts/${id}/progress`, {headers:{Authorization:`Bearer ${token}`},signal:controller.signal});
          if (!response.ok) throw new Error('unavailable');
          const data = await response.json();
          if (data.manuscript_id !== id || (!reviewer && data.status !== expected) || !WORKFLOW_STAGES.some(([name]) => name === data.current_stage)) throw new Error('invalid');
          const permittedSubstages = ['formatter_invited', 'formatter_declined', 'awaiting_formatted_proof', 'pending_author', 'pending_eic', 'approved', 'author_revision_requested', 'eic_revision_requested'];
          stages[id] = {stage: data.current_stage, substage: permittedSubstages.includes(data.formatting_substage) ? data.formatting_substage : null};
        } catch (error) { if (error?.name === 'AbortError') return; stages[id] = null; }
      }
    }
    Promise.all(Array.from({length: Math.min(5, work.length)}, worker)).then(() => {
      if (!controller.signal.aborted) setResult({token, signature, reviewer, filter:mainFilter, revision, stages});
    });
    return () => controller.abort();
  }, [active, token, signature, reviewer, mainFilter, revision]);
  const current = active && result?.token === token && result.signature === signature && result.reviewer === reviewer && result.filter === mainFilter && result.revision === revision ? result : null;
  const loading = active && requested.length > 0 && !current;
  const proofFilter = typeof filter === 'string' && filter.includes('|status:proof:');
  const targetStage = mainFilter.slice(6);
  const unavailable = ambiguous.length !== requested.length || (current ? Object.values(current.stages).some(entry => entry === null || (proofFilter && entry.stage === targetStage && !entry.substage)) : false);
  return {items: items.map(item => {
    if (!active || !(reviewer || (needsProof && item.status === 'formatting'))) return item;
    return {...item, workflow_stage: current?.stages[item.manuscript_id]?.stage || null,
      workflow_substage: current?.stages[item.manuscript_id]?.substage || null};
  }), loading, unavailable};
}

export function StageProjectionNotice({projection}) {
  if (projection.loading) return createElement('p', {role:'status'}, 'Checking authorized manuscript stages…');
  if (projection.unavailable) return createElement('p', {role:'status'}, 'Some manuscript stages are unavailable and are not included in stage-filter results.');
  return null;
}
