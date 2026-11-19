import { statusLabel, statusValue } from './eicManuscriptList';

const groups = [
  ['Screening', ['submitted']],
  ['Initial editing', ['initial_scan_passed','initial_editor_invited','initial_editing']],
  ['Awaiting author response', ['initial_revision_required','revision_required','pre_review_confirmation','awaiting_author_agreement']],
  ['Peer review', ['ready_for_peer_review','revised']],
  ['Final editing', ['final_editing']],
  ['Formatting', ['formatting']],
  ['Closed or published', ['rejected','initial_rejected','published']],
];

export function groupQueue(items) {
  const result = new Map();
  const seen = new Set();
  for (const item of items) {
    if (seen.has(item.manuscript_id)) continue;
    seen.add(item.manuscript_id);
    const status = statusValue(item);
    const group = groups.find(([, values]) => values.includes(status))?.[0] || 'Other / unavailable';
    if (!result.has(group)) result.set(group, []);
    result.get(group).push(item);
  }
  return [...groups.map(([name]) => name), 'Other / unavailable']
    .filter(name => result.has(name)).map(name => ({name, items:result.get(name)}));
}

export default function EICWorkQueue({items, state, onOpen, unread, onOpenNotifications, onRetry}) {
  return <section className="eic-work-queue" aria-label="EIC work queue">
    <h2>Work queue</h2>
    <p>Workflow groups use the accessible manuscript list. Action eligibility is not included; open a manuscript to check.</p>
    <div className="eic-queue-alerts">
      <strong>Notifications</strong>{' '}
      {unread?.state === 'ready' ? <span>{unread.count} unread</span> : unread?.state === 'error' ? <span>Notifications unavailable</span> : <span>Loading notifications…</span>}
      <button type="button" onClick={onOpenNotifications}>Open notifications</button>
    </div>
    {state === 'loading' ? <p role="status">Loading workflow groups…</p> : state === 'error' ? <div><p>Workflow groups are unavailable.</p><button type="button" onClick={onRetry}>Retry work queue</button></div> : !items.length ? <p>The work queue is empty.</p> : <>
      <p className="eic-queue-note">Waiting or action eligibility unconfirmed. No decision-ready count is inferred from status.</p>
      {groupQueue(items).map(group => <section className="eic-queue-group" key={group.name}>
        <h3>{group.name} <span>({group.items.length})</span></h3>
        <ul>{group.items.slice(0,2).map(item => <li key={item.manuscript_id}>
          <button type="button" aria-label={`Open ${item.title || 'untitled manuscript'} (manuscript ${item.manuscript_id}) from work queue`} onClick={() => onOpen(item.manuscript_id)}>#{item.manuscript_id} {item.title || 'Title unavailable'}</button>
          <small>{statusLabel(statusValue(item))}</small>
        </li>)}</ul>
        {group.items.length > 2 && <p>{group.items.length - 2} more in Manuscripts.</p>}
      </section>)}
    </>}
  </section>;
}
