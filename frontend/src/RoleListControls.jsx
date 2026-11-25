import {matchesWorkflowFilter} from './workflowStatus';
import StageFilterControls, {StageFilterClear} from './StageFilterControls';
export function selectRoleItems(items, search, status, sort) {
  const query = search.trim().toLowerCase();
  return items.filter(item => (!query || String(item.manuscript_id).includes(query) || String(item.title || item.manuscript_title || '').toLowerCase().includes(query)) && matchesWorkflowFilter(item, status))
    .slice().sort((a,b) => {
      if (sort === 'title') return String(a.title || a.manuscript_title || '').localeCompare(String(b.title || b.manuscript_title || ''));
      const getDate = item => Date.parse(item.updated_at || item.created_at || '') || 0;
      return sort === 'oldest' ? getDate(a) - getDate(b) : getDate(b) - getDate(a);
    });
}
export default function RoleListControls({items, search, setSearch, status, setStatus, sort, setSort, projection}) {
  return <div className="role-list-controls">
    <label>Search manuscripts <input type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Title or manuscript ID" /></label>
    <StageFilterControls value={status} onChange={setStatus} items={items} />
    <label>Sort by <select value={sort} onChange={e=>setSort(e.target.value)}><option value="recent">Most recently updated</option><option value="oldest">Oldest updated</option><option value="title">Title</option></select></label>
    <StageFilterClear onClear={() => {setSearch('');setStatus('');setSort('recent');}} />
    {projection && <p role="status">{projection.loading || projection.unavailable ? 'Result count unavailable' : `${selectRoleItems(items, search, status, sort).length} matching results`}</p>}
  </div>;
}
