import {matchesWorkflowFilter} from './workflowStatus';
const revisions = new Set(['revision_required', 'initial_revision_required']);
const rejections = new Set(['rejected', 'initial_rejected']);
const inProgress = new Set(['submitted', 'initial_scan_passed', 'initial_editor_invited', 'initial_editing', 'ready_for_peer_review', 'revised', 'awaiting_author_agreement', 'final_editing', 'formatting']);
export function manuscriptGroup(status) {
  if (status === 'draft') return 'draft';
  if (revisions.has(status)) return 'revision';
  if (rejections.has(status)) return 'rejected';
  if (status === 'accepted') return 'accepted';
  if (inProgress.has(status)) return 'progress';
  return 'other';
}
export function manuscriptTime(item) {
  const value = item?.updated_at || item?.created_at;
  const timestamp = typeof value === 'string' ? Date.parse(value) : NaN;
  return Number.isFinite(timestamp) ? timestamp : null;
}
export function manuscriptDate(value) {
  const date = typeof value === 'string' ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString() : 'Unavailable';
}
export function selectManuscripts(items, search='', filter='all', sort='recent') {
  const query=search.trim().toLocaleLowerCase();
  return items.filter(item => (filter==='all' || manuscriptGroup(item.status)===filter || (filter !== 'progress' && filter !== 'revision' && matchesWorkflowFilter(item, filter))) &&
    (!query || String(item.title || '').toLocaleLowerCase().includes(query) || String(item.manuscript_id).includes(query)))
    .slice().sort((a,b)=>{
      if(sort==='title') return String(a.title || '').localeCompare(String(b.title || '')) || a.manuscript_id-b.manuscript_id;
      const left=manuscriptTime(a), right=manuscriptTime(b);
      if(left===null && right===null) return a.manuscript_id-b.manuscript_id;
      if(left===null) return 1;if(right===null) return -1;
      return (sort==='oldest' ? left-right : right-left) || a.manuscript_id-b.manuscript_id;
    });
}
