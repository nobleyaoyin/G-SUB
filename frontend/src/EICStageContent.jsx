import {workflowStatusLabel} from './workflowStatus';
import EICStageHistory from './EICStageHistory';
import EICReviewPolicyPanel from './EICReviewPolicyPanel';
import BlindReviewPanel from './BlindReviewPanel';
import FormattingPanel from './FormattingPanel';
import { InitialScreeningStageView, InitialEditorAssignmentView, InitialEditingReviewView, PeerReviewStageView, EICDecisionStageView, FinalEditorAssignmentView, FinalEditingReviewView } from './EICStageViews';

// The dashboard owns selection, authorization evidence and form state. These
// views only present the selected stage and reuse its existing action handlers.
function StageContent({stage, context, children}) {
  const {overview, formatting, status, currentStage, download} = context;
  return <div data-eic-stage={stage}>
    <div className="eic-workflow-grid">{children}</div>
    <EICStageHistory stage={stage} overview={overview} formatting={formatting?.status === status ? formatting : null} onDownload={download} />
    {stage !== currentStage && <p>Detailed stage records may be available in Activity History below.</p>}
  </div>;
}

export function SubmissionStage({context}) {
  const manuscript = context.overview.manuscript;
  const manuscriptId = context.selected ?? manuscript.manuscript_id;
  return <StageContent stage="Submission" context={context}>
    <section aria-label="Submission information"><h4>Submission information</h4>
      <p><strong>Manuscript:</strong> {manuscript.title || 'Title unavailable'} (#{manuscriptId})</p>
      <p><strong>Abstract:</strong> {manuscript.abstract || 'Abstract unavailable'}</p>
      <button type="button" onClick={() => context.download(`/manuscripts/${manuscriptId}/download`)}>Download submitted manuscript</button>
    </section>
  </StageContent>;
}
export function InitialScreeningStage({context:c}) {
  return <StageContent stage="Initial Screening" context={c}>{c.currentStage === 'Initial Screening' && c.status === 'submitted' && <InitialScreeningStageView {...c} />}</StageContent>;
}
export function InitialEditingStage({context:c}) {
  return <StageContent stage="Initial Editing" context={c}>
    {c.currentStage === 'Initial Editing' && c.status === 'initial_scan_passed' && <InitialEditorAssignmentView {...c} />}
    {c.currentStage === 'Initial Editing' && c.status === 'initial_editing' && c.approval.length > 0 && <div id={`eic-initial-review-${c.selected}`}>{c.approval.map(submission => <InitialEditingReviewView key={submission.submission_id} {...c} submission={submission} />)}</div>}
  </StageContent>;
}
export function PeerReviewStage({context:c}) {
  return <StageContent stage="Peer Review" context={c}>{c.currentStage === 'Peer Review' && ['ready_for_peer_review','revised'].includes(c.status) && <PeerReviewStageView overview={c.overview} />}</StageContent>;
}
export function EICDecisionStage({context:c}) {
  return <StageContent stage="EIC Decision" context={c}>
    {c.currentStage === 'Peer Review' && c.canDecide && <EICDecisionStageView {...c} />}
    {!c.canDecide && <p>{c.overview.review_progress?.blocked_reason || 'A decision action is not currently available.'}</p>}
  </StageContent>;
}
export function AuthorAgreementStage({context}) { return <StageContent stage="Author Agreement" context={context} />; }
export function FinalEditingStage({context:c}) {
  return <StageContent stage="Final Editing" context={c}>
    {c.currentStage === 'Final Editing' && c.status === 'final_editing' && c.overview.author_agreement?.status === 'accepted' && !c.activeFinal && <FinalEditorAssignmentView {...c} />}
    {c.currentStage === 'Final Editing' && c.status === 'final_editing' && c.latestFinal?.status === 'pending_eic' && <FinalEditingReviewView {...c} />}
  </StageContent>;
}
export function FormattingStage({context}) { return <StageContent stage="Formatting" context={context} />; }
export function ProofingStage({context}) { return <StageContent stage="Proofing" context={context} />; }
export function PublicationStage({context}) { return <StageContent stage="Publication" context={context} />; }

const views = {
  'Submission':SubmissionStage, 'Initial Screening':InitialScreeningStage,
  'Initial Editing':InitialEditingStage, 'Peer Review':PeerReviewStage,
  'EIC Decision':EICDecisionStage, 'Author Agreement':AuthorAgreementStage,
  'Final Editing':FinalEditingStage, 'Formatting':FormattingStage, 'Proofing':ProofingStage, 'Publication':PublicationStage,
};

export default function EICStageContent({stage, context}) {
  const View = Object.hasOwn(views, stage) ? views[stage] : null;
  return View ? <View context={context} /> : null;
}

// Kept mounted while browsing so existing in-progress panel state is preserved.
export function EICPeerReviewWorkspace({currentStage, selectedStage, overview, selected, round, status, token, refresh}) {
  return <div hidden={currentStage !== 'Peer Review' || selectedStage !== 'Peer Review'}><section className="eic-reviewer-management" id={`eic-reviewer-management-${selected}`}>
        <div className="eic-section-heading">
          <div>
            <span className="eic-eyebrow">PEER REVIEW</span>
            <h3>Reviewer Management</h3>
            <p>Manage review policies, assignments and review progress.</p>
          </div>
        </div>

        {overview.split_review && (
          <section className="eic-action-card eic-split-review-card">
            <h4>Review Recommendations · Round {overview.split_review.review_round}</h4>
            <p>Completed assignment records in this round: {overview.assignments.filter(item => item.review_round === overview.split_review.review_round && item.status === "completed").length}.</p>
            <p>
              {overview.split_review.eligible_completed} eligible completed reviews:
              {" "}{overview.split_review.recommendations.join(", ") || "none yet"}.
            </p>
            <p>Completed assignments do not automatically qualify. Recommendation eligibility requires a completed current-round assignment, an accepted invitation, a reviewer account, a matching round file, and a submitted review with a valid recommendation. Invalidated assignments are excluded. If a reviewer has more than one qualifying review in the round, none of that reviewer's qualifying reviews are counted here.</p>
            <p>
              {({
                split: "Opposing accept and reject recommendations; an additional review may be requested.",
                aligned: "The first two recommendations are aligned.",
                ambiguous: "Revision recommendations need editorial interpretation; no automatic split classification.",
                insufficient: "Waiting for two eligible reviews."
              })[overview.split_review.classification]}
            </p>
            {overview.split_review.additional_assignments.map(a => (
              <p key={a.assignment_id}>
                Additional invitation: {workflowStatusLabel(a.invitation_status)} · review: {workflowStatusLabel(a.review_status)}
              </p>
            ))}
          </section>
        )}

        <EICReviewPolicyPanel key={`policy-${selected}`} manuscriptId={selected} token={token} invitationCount={overview.assignments.length} onChanged={() => refresh(selected)} />
        <BlindReviewPanel
          key={selected}
          manuscriptId={selected}
          round={round}
          status={status}
          token={token}
          onChanged={() => refresh(selected)}
          splitReview={overview.split_review}
        />
      </section></div>;
}

export function EICFormattingWorkspace({currentStage, selectedStage, selected, token, latestFinal, refresh}) {
  const canOpen = ['Formatting', 'Proofing'].includes(currentStage) || (currentStage === 'Final Editing' && latestFinal?.status === 'author_approved');
  return <div hidden={!canOpen || !['Formatting', 'Proofing'].includes(selectedStage)}><section className="eic-formatting-section">
        <div className="eic-section-heading">
          <div>
            <span className="eic-eyebrow">PUBLICATION WORKFLOW</span>
            <h3>Formatting and Publication</h3>
            <p>Review formatted documents and manage publication.</p>
          </div>
        </div>
        <FormattingPanel
          key={`format-${selected}`}
          role="eic"
          token={token}
          manuscriptId={selected}
          canInvite={latestFinal?.status === "author_approved"}
          onChanged={() => refresh(selected)}
        />
      </section></div>;
}
