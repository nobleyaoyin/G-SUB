import {useEffect, useState} from 'react';
import {API_URL} from './api';
import CollapsibleStatistics from './CollapsibleStatistics';
import {assignmentStatistics} from './assignmentStatistics';
import {compareWorkflowStatuses, workflowStatusLabel} from './workflowStatus';

export default function EditorAssignmentStatistics({token, userId, revision, summary, statusItems, statusLoading, statusError}) {
  const [result, setResult] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    async function load(path, kind) {
      try {
        const response = await fetch(`${API_URL}${path}`, {headers:{Authorization:`Bearer ${token}`},signal:controller.signal});
        if (!response.ok) throw new Error('unavailable');
        return assignmentStatistics(await response.json(), kind, userId);
      } catch { return null; }
    }
    Promise.all([load('/eic/initial-editing/my','initial'), load('/final-workflow/my','final')]).then(([initial, final]) => {
      if (!controller.signal.aborted) setResult({token, revision, initial, final});
    });
    return () => controller.abort();
  }, [token, userId, revision]);
  const current = result?.token === token && result.revision === revision ? result : null;
  const statusCounts = new Map();
  for (const item of Array.isArray(statusItems) ? statusItems : []) {
    if (typeof item.status === 'string' && item.status) statusCounts.set(item.status, (statusCounts.get(item.status) || 0) + 1);
  }
  return <CollapsibleStatistics className="editor-stats-details">
    <div className="editor-stats-summary" aria-label="Assignment summary">
      {!current ? <p role="status">Loading assignment statistics…</p> : ['initial','final'].map(kind => <div key={kind}><span>{kind === 'initial' ? 'Initial' : 'Final'} assigned</span><strong>{current[kind] ? current[kind].assigned : 'Unavailable'}</strong></div>)}
      {summary && <div><span>Total manuscripts</span><strong>{summary.total_manuscripts ?? 'Unavailable'}</strong></div>}
    </div>
    <details className="editor-stats-breakdown"><summary>Detailed statistics</summary>
    {!current ? <p role="status">Loading assignment statistics…</p> : ['initial','final'].map(kind => {
      const stats = current[kind];
      return <section key={kind} aria-label={`${kind === 'initial' ? 'Initial' : 'Final'} editing statistics`}>
        <h3>{kind === 'initial' ? 'Initial' : 'Final'} editing assignments</h3>
        {!stats ? <p>Assignment statistics are unavailable.</p> : <div className="editor-stats">{[
          ['Assigned manuscripts', stats.assigned], ['Pending invitations', stats.invitation],
          ['Editing work pending', stats.work], ['Submitted for review', stats.submitted],
          ['Completed assignments', stats.completed], ['Status unavailable', stats.unknown],
        ].map(([label,value]) => <div className="editor-stat-card" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>}
      </section>;
    })}
    {summary && <section aria-label="General editor workload statistics"><h3>General editor workload</h3><div className="editor-stats">{[
      ['Total manuscripts', summary.total_manuscripts], ['Not assigned', summary.not_assigned],
      ['In progress', summary.in_progress], ['Ready for decision', summary.ready_for_decision],
      ['Revision required', summary.revision_required], ['Decision finalized', summary.decision_finalized],
    ].map(([label, value]) => <div className="editor-stat-card" key={label}><span>{label}</span><strong>{value ?? 'Unavailable'}</strong></div>)}</div></section>}
    {statusItems && <section aria-label="Combined editor and formatting manuscript status"><h3>Editor and formatting manuscript status</h3>
      {statusError ? <p>Status breakdown is unavailable.</p> : statusLoading ? <p role="status">Loading status breakdown…</p> : statusCounts.size ?
        <div className="editor-stats">{[...statusCounts].sort(([a],[b]) => compareWorkflowStatuses(a,b)).map(([status,count]) => <div className="editor-stat-card" key={status}><span>{workflowStatusLabel(status)}</span><strong>{count}</strong></div>)}</div> : <p>No manuscript statuses available.</p>}
    </section>}
    </details>
  </CollapsibleStatistics>;
}
