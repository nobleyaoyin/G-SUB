import {workflowStatusLabel} from './workflowStatus';
import {recordedTimestamp} from './recordedTimestamp';

// Display only fields supplied by the authorized invitation projection.

export default function EditorInvitationSummary({title, status, stage, abstract, metadata, editor, invitedAt, respondedAt, showManuscriptTitle = true}) {
  return <details className="editor-invitation-summary">
    <summary>{stage} invitation information</summary>
    {showManuscriptTitle && <p><strong>Manuscript:</strong> {typeof title === 'string' && title.trim() ? title : 'Title unavailable'} <small>(invitation record)</small></p>}
    <p><strong>Invitation type:</strong> {stage}</p>
    <p><strong>Invited editor:</strong> {typeof editor === 'string' && editor.trim() ? editor : 'Unavailable'}</p>
    <p><strong>Invitation status:</strong> {workflowStatusLabel(status)}</p>
    <p><strong>Invited:</strong> {recordedTimestamp(invitedAt)} · <strong>Responded:</strong> {recordedTimestamp(respondedAt)}</p>
    {status === 'accepted' && typeof abstract === 'string' && abstract.trim() ? <p><strong>Abstract (author-provided):</strong> {abstract}</p> : <p>Abstract is unavailable in this invitation preview.</p>}
    {['pending', 'accepted'].includes(status) && Number.isSafeInteger(metadata?.word_count) && metadata.word_count >= 0 && metadata.word_count <= 2_000_000 && typeof metadata.word_count_source === 'string' && metadata.word_count_source.trim() ? <p><strong>Word count:</strong> {metadata.word_count} <small>({metadata.word_count_source}; estimate, not current editing version)</small></p> : <p><strong>Word count:</strong> Unavailable.</p>}
    <p><strong>Figure count:</strong> Unavailable.</p>
    <p>Subject, keywords, table count, and document excerpt are unavailable in this invitation preview.</p>
    <p>Initial and final editor are workflow assignments for Editor accounts, not separate sign-in choices. Editing history and document access depend on the existing assignment authorization.</p>
  </details>;
}
