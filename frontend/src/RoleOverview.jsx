import StatusBadge from './StatusBadge';
import RoleStatistics from './RoleStatistics';
import ReviewerRecentList from './ReviewerRecentList';
import './RoleOverview.css';

// Counts use only records already returned to the current role's dashboard.
export default function RoleOverview({label, items, loading, error, onOpen, onNavigate, hideStatistics = false}) {
  const records = Array.isArray(items) ? items : [];
  const hasDates = records.some(item => Number.isFinite(Date.parse(item.updated_at || item.created_at || "")));
  const recent = [...records].sort((a,b) => {
    const date = item => Date.parse(item.updated_at || item.created_at || '') || 0;
    return date(b) - date(a);
  }).slice(0,3);
  const header = <>
    <h2>Dashboard Overview</h2>
    {loading && <p role="status">Loading {label.toLowerCase()} information…</p>}
    {error && <p role="alert">Information could not be refreshed.</p>}
  </>;
  const statistics = !hideStatistics && <RoleStatistics items={records} label={label === 'Reviewer' ? 'Review assignments' : 'Accessible manuscripts'} loading={loading} error={error} authorStyle={label === 'Reviewer'} />;
  const sidebarOverview = !hideStatistics && (label === 'Reviewer' || label === 'EIC');
  const recentContent = !loading && !error && <>
      <section className={label === 'Reviewer' ? 'author-overview-card' : 'role-recent-card'}><div className={label === 'Reviewer' ? 'section-header' : 'role-recent-heading'}><h3>{hasDates || label === 'Reviewer' ? 'Recent Manuscripts' : 'Manuscripts'}</h3><button type="button" className={label === 'Reviewer' ? 'author-text-action' : undefined} onClick={()=>onNavigate('manuscripts')}>View all manuscripts</button></div>
        {recent.length ? label === 'Reviewer' ? <ReviewerRecentList items={recent} onOpen={onOpen} /> : <ul>{recent.map((item,index)=><li key={item.assignment_id || `${item.manuscript_id}-${index}`}><div><strong>{item.title || item.manuscript_title || `Manuscript #${item.manuscript_id}`}</strong><p>Manuscript #{item.manuscript_id} · <StatusBadge status={item.status} />{Number.isFinite(Date.parse(item.updated_at || item.created_at || '')) ? ` · ${new Date(item.updated_at || item.created_at).toLocaleDateString()}` : ''}</p></div><button type="button" className="manuscript-open-button" onClick={()=>onOpen(item)}>Open manuscript</button></li>)}</ul> : <p>No accessible manuscripts.</p>}
      </section>
    </>;
  return <section className={`role-overview${sidebarOverview ? label === 'Reviewer' ? ' reviewer-overview-layout' : ' eic-overview-layout' : ''}`} aria-label={`${label} overview`}>
    {sidebarOverview ? <>
      <div className="reviewer-overview-content">{header}{recentContent}</div>
      <aside className={label === 'Reviewer' ? 'reviewer-overview-statistics author-statistics-sidebar' : 'eic-overview-statistics'} aria-label={`${label} overview statistics`}>{statistics}</aside>
    </> : <>{header}{statistics}{recentContent}</>}
  </section>;
}
