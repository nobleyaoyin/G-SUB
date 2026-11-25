import {workflowStatusLabel} from './workflowStatus';
// Read-only summaries of records already returned to the authorized EIC.
const label = value => value ? workflowStatusLabel(value) : 'Unavailable';
const date = value => {
  if (!value || Number.isNaN(Date.parse(value))) return 'Date unavailable';
  return new Date(value).toLocaleString();
};
const records = value => Array.isArray(value) ? value : null;

export default function EICStageHistory({stage, overview, formatting, onDownload}) {
  const list = (value, empty, render, dateField) => {
    const entries = records(value);
    if (!entries) return <p>History information is unavailable.</p>;
    if (!entries.length) return <p>{empty}</p>;
    const ordered = [...entries].sort((a, b) => {
      const timestamp = item => { const n = Date.parse(item?.[dateField]); return Number.isFinite(n) ? n : Infinity; };
      return timestamp(a) - timestamp(b);
    });
    return <ul>{ordered.map(render)}</ul>;
  };
  let content = null;
  if (stage === 'Submission') content = <p>Manuscript created: {date(overview.manuscript?.created_at)}.</p>;
  if (stage === 'Initial Screening') content = list(overview.scans, 'No screening records are listed.', (item, i) => <li key={i}>Screening: {label(item.decision)} · {date(item.created_at)}</li>, 'created_at');
  if (stage === 'Initial Editing') content = <>
    <p>Invitation responses are recorded separately from document distribution. Distribution and delivery records are unavailable in this view.</p>
    <h5>Initial editor invitations</h5>
    {list(overview.invitations, 'No initial editor invitations are listed.', (item, i) => <li key={item.invitation_id ?? i}>Invitation #{item.invitation_id}: {label(item.status)} · invited {date(item.invited_at)} · response {date(item.responded_at)}{item.invitation_id === overview.invitations.at(-1)?.invitation_id ? ' · latest recorded' : ' · earlier record'}</li>, 'invited_at')}
    <h5>Editing submissions</h5>
    {list(overview.submissions, 'No initial editing submissions are listed.', (item, i) => <li key={item.submission_id ?? i}>Submission #{item.submission_id}: {label(item.status)} · {date(item.created_at)}</li>, 'created_at')}
    <h5>Author confirmations</h5>
    {list(overview.confirmations, 'No author confirmations are listed.', (item, i) => <li key={`${item.submission_id}-${i}`}>Submission #{item.submission_id}: {label(item.decision)} · {date(item.confirmed_at)}</li>, 'confirmed_at')}
  </>;
  if (stage === 'Peer Review') {
    const assignments = records(overview.assignments);
    if (!assignments) content = <p>Review history information is unavailable.</p>;
    else if (!assignments.length) content = <p>No review assignments are listed.</p>;
    else {
      const groups = new Map();
      assignments.forEach(item => { const round = Number.isInteger(item.review_round) && item.review_round > 0 ? item.review_round : null; groups.set(round, [...(groups.get(round) || []), item]); });
      content = [...groups.entries()].sort(([a],[b]) => (a ?? Infinity) - (b ?? Infinity)).map(([round, items]) => <div key={round ?? 'unknown'}><h5>{round == null ? 'Round unavailable' : `Round ${round}`}{round === overview.manuscript?.review_round ? ' · current round' : ''}</h5><ul>{items.map((item, i) => <li key={item.assignment_id ?? i}>{item.recorded_round_binding && item.recorded_round_binding.review_round === round ? `Incoming binding #${item.recorded_round_binding.round_file_id} recorded (${label(item.recorded_round_binding.source_kind)}); file integrity unverified` : 'Incoming document binding unavailable'} · Delivery unknown · Reviewed document attachment: unavailable · Invitation: {label(item.invitation_status)} · Assignment: {label(item.status)} · {item.review ? `Review submitted · ${date(item.review.submitted_at)}` : 'No submitted review record'}</li>)}</ul></div>);
    }
  }
  if (stage === 'EIC Decision') content = list(overview.decisions, 'No decision records are listed.', (item, i) => <li key={i}>Round {item.review_round ?? 'unavailable'}: {label(item.decision)} · {date(item.decided_at)}</li>, 'decided_at');
  if (stage === 'Author Agreement') content = overview.author_agreement ? <p>Agreement: {label(overview.author_agreement.status)} · Version: {overview.author_agreement.agreement_version || 'unavailable'} · Response: {date(overview.author_agreement.responded_at)}</p> : <p>Agreement record is unavailable or has not been created.</p>;
  if (stage === 'Final Editing') content = <>
    <p>Invitation response is not proof of document distribution or email delivery.</p>
    <h5>Final editor invitations</h5>{list(overview.final_invitations, 'No final editor invitations are listed.', (item,i) => <li key={item.invitation_id ?? i}>Invitation #{item.invitation_id}: {label(item.status)} · invited {date(item.invited_at)} · response {date(item.responded_at)}</li>, 'invited_at')}
    <h5>Final editing submissions</h5>{list(overview.final_workflow_submissions, 'No final editing submissions are listed.', (item,i) => <li key={item.submission_id ?? i}>Submission #{item.submission_id}: {label(item.status)} · {date(item.created_at)}</li>, 'created_at')}
  </>;
  if (stage === 'Formatting' || stage === 'Proofing') content = !formatting ? <p>Formatting history is unavailable.</p> : list(formatting.submissions, 'No formatting submissions are listed.', (item,i) => <li key={item.submission_id ?? i}>Submission #{item.submission_id}: {label(item.status)} · {date(item.created_at)}</li>, 'created_at');
  if (stage === 'Publication') content = !formatting ? <p>Publication record is unavailable.</p> : formatting.publication && overview.manuscript?.status === 'published' && formatting.status === 'published' ? <>
    <p>Publication recorded in the local prototype · {date(formatting.publication.published_at)}.</p>
    {Number.isInteger(formatting.publication.submission_id) && <button type="button" onClick={() => onDownload(`/formatting/submissions/${formatting.publication.submission_id}/download`)}>Download published document</button>}
  </> : <p>No confirmed publication record is available.</p>;
  return content ? <section aria-label={`${stage} history`}><h4>Stage history</h4>{content}</section> : null;
}
