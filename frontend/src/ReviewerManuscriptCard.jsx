import {workflowStatusLabel} from './workflowStatus';
import StatusBadge from './StatusBadge';

// Uses only the assignment fields already provided to the authenticated Reviewer.
export default function ReviewerManuscriptCard({assignment, onOpen, includeId = true, allowOverviewTitle = false}) {
  const {assignment_id: assignmentId, manuscript_id: manuscriptId} = assignment;
  const suppliedTitle = allowOverviewTitle ? assignment.title || assignment.manuscript_title : assignment.manuscript_title;
  const title = suppliedTitle || `Manuscript #${manuscriptId}`;
  const date = assignment.updated_at || assignment.created_at;
  return <div id={includeId ? `assignment-${assignmentId}` : undefined} className="manuscript-card reviewer-card" data-manuscript-id={manuscriptId}>
    <div className="manuscript-card-top">
      <h3>{title}</h3>
      {assignment.status && <StatusBadge status={assignment.status} />}
    </div>
    {(suppliedTitle || assignment.review_round != null) && <p>{suppliedTitle && `Manuscript #${manuscriptId}`}{assignment.review_round != null && `${suppliedTitle ? ' · ' : ''}Round ${assignment.review_round}`}</p>}
    {(assignment.invitation_status || assignment.manuscript_status) && <p>
      {assignment.invitation_status && <>Invitation: {workflowStatusLabel(assignment.invitation_status)}</>}
      {assignment.invitation_status && assignment.manuscript_status && ' · '}
      {assignment.manuscript_status && <><strong>Workflow:</strong>{' '}<StatusBadge status={assignment.manuscript_status} /></>}
    </p>}
    {date && Number.isFinite(Date.parse(date)) && <p>{assignment.updated_at ? 'Updated' : 'Created'}: {new Date(date).toLocaleDateString()}</p>}
    <button type="button" className="download-button manuscript-open-button" onClick={() => onOpen(assignment)}>Open manuscript</button>
  </div>;
}
