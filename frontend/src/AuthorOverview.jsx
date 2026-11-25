import StatusBadge from './StatusBadge';
import { manuscriptDate, selectManuscripts } from './authorManuscriptView';

export default function AuthorOverview({manuscripts, loading, error, onOpen, onNavigate}) {
  const recent=selectManuscripts(manuscripts).slice(0,3);
  return <section className="author-overview" aria-label="Author overview">
    <h2>Dashboard Overview</h2>
    {loading && <p role="status">Loading manuscripts…</p>}
    {error && <p role="alert">Manuscript information could not be refreshed.</p>}
    {!loading && <>
      <section className="author-overview-card"><div className="section-header"><h3>Recent Manuscripts</h3><button type="button" className="author-text-action" onClick={()=>onNavigate('manuscripts')}>View all manuscripts</button></div>
        {recent.length ? <ul className="author-recent-list">{recent.map(item=><li key={item.manuscript_id}><div><strong>{item.title?.trim() || `Manuscript #${item.manuscript_id}`}</strong><p>Manuscript #{item.manuscript_id} · <StatusBadge status={item.status} />{item.updated_at ? ` · Updated ${manuscriptDate(item.updated_at)}` : ''}</p></div><button type="button" className="manuscript-open-button" onClick={()=>onOpen(item.manuscript_id)}>Open manuscript</button></li>)}</ul> : <p>No manuscripts yet.</p>}
      </section>
    </>}
  </section>;
}
