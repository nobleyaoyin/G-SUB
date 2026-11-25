import CollapsibleStatistics from './CollapsibleStatistics';
import {compareWorkflowStatuses, workflowStatusLabel} from './workflowStatus';
import './RoleStatistics.css';

// The caller supplies only records already authorized for this user's dashboard.
export default function RoleStatistics({items, label = 'Accessible manuscripts', loading, error, authorStyle = false}) {
  const records = Array.isArray(items) ? items : [];
  const counts = new Map();
  for (const item of records) {
    if (typeof item.status === 'string' && item.status) counts.set(item.status, (counts.get(item.status) || 0) + 1);
  }
  return <CollapsibleStatistics className={authorStyle ? 'dashboard-collapsible' : 'role-statistics'}>
    {error ? <p role="alert">Statistics are unavailable.</p> : loading ? <p role="status">Loading statistics…</p> :
      <div className={authorStyle ? 'stats-grid' : 'role-statistics-grid'}><div className={authorStyle ? 'stat-card' : undefined}><span>{label}</span><strong>{records.length}</strong></div>
        {[...counts.keys()].sort(compareWorkflowStatuses).map(status => <div className={authorStyle ? 'stat-card' : undefined} key={status}><span>{workflowStatusLabel(status)}</span><strong>{counts.get(status)}</strong></div>)}
      </div>}
  </CollapsibleStatistics>;
}
