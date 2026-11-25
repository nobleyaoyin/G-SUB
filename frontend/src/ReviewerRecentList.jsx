import StatusBadge from './StatusBadge';

// Render only the assignment fields already supplied to the Reviewer overview.
export default function ReviewerRecentList({items, onOpen}) {
  return <ul className="author-recent-list reviewer-recent-list">
    {items.map((item, index) => {
      const title = item.title || item.manuscript_title || `Manuscript #${item.manuscript_id}`;
      const date = item.updated_at || item.created_at;
      return <li key={item.assignment_id || `${item.manuscript_id}-${index}`}>
        <div className="reviewer-recent-info">
          <div className="reviewer-recent-title"><strong>{title}</strong>{item.status && <StatusBadge status={item.status} />}</div>
          <p>Manuscript #{item.manuscript_id}{item.review_round != null && ` · Round ${item.review_round}`}</p>
          {(item.invitation_status || item.manuscript_status) && <p>
            {item.invitation_status && <>Invitation: <StatusBadge status={item.invitation_status} /></>}
            {item.invitation_status && item.manuscript_status && ' · '}
            {item.manuscript_status && <><strong>Workflow:</strong>{' '}<StatusBadge status={item.manuscript_status} /></>}
          </p>}
          {date && Number.isFinite(Date.parse(date)) && <p>{item.updated_at ? 'Updated' : 'Created'}: {new Date(date).toLocaleDateString()}</p>}
        </div>
        <button type="button" className="download-button manuscript-open-button" onClick={() => onOpen(item)}>Open manuscript</button>
      </li>;
    })}
  </ul>;
}
